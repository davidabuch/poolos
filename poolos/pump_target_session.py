"""Unit-aware pump target session and manual override state.

This runtime mirrors the established pump-speed session contract but treats the
configured PMPCIRC target as an exact (unit, value) pair.  It is intentionally
separate from PumpSpeedSessionRuntime so the commissioned RPM-only path can
remain unchanged while GPM support is introduced incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from .pump_operating_target import (
    PumpOperatingTarget,
    PumpOperatingTargetPolicy,
)
from .pump_speed_session import (
    PumpSpeedOverrideSource,
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionPurpose,
)


@dataclass(frozen=True, slots=True)
class PumpTargetSessionEvidence:
    observed_at: datetime
    body: PumpSpeedSessionBody | None
    purpose: PumpSpeedSessionPurpose | None
    pump_circuit_id: str | None
    configured_target: PumpOperatingTarget | None
    connection_generation: int
    evidence_usable: bool

    def __post_init__(self) -> None:
        _require_aware(self.observed_at)
        if self.connection_generation < 0:
            raise ValueError("connection_generation must be nonnegative")


@dataclass(frozen=True, slots=True)
class PumpTargetSessionSnapshot:
    active: bool
    evidence_usable: bool
    session_id: str | None
    generation: int
    body: PumpSpeedSessionBody | None
    purpose: PumpSpeedSessionPurpose | None
    pump_circuit_id: str | None
    configured_baseline_target: PumpOperatingTarget | None
    effective_target: PumpOperatingTarget | None
    override_state: PumpSpeedOverrideState
    override_source: PumpSpeedOverrideSource
    pending_requested_target: PumpOperatingTarget | None
    verified_override_target: PumpOperatingTarget | None
    last_session_transition_reason: str
    last_override_transition_reason: str
    reset_on_runtime_start: bool = True


@dataclass(frozen=True, slots=True)
class PumpTargetManualRequest:
    token_id: str
    request_id: str
    session_id: str
    body: PumpSpeedSessionBody
    pump_circuit_id: str
    requested_target: PumpOperatingTarget
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class PumpTargetNativeTransition:
    concept: str
    native_object_id: str
    previous_target: PumpOperatingTarget
    new_target: PumpOperatingTarget
    observed_at: datetime
    correlated_request_id: str | None = None
    positive_operator_intent: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.observed_at)


@dataclass(slots=True)
class _TargetOverride:
    state: PumpSpeedOverrideState = PumpSpeedOverrideState.NONE
    source: PumpSpeedOverrideSource = PumpSpeedOverrideSource.NONE
    requested_target: PumpOperatingTarget | None = None
    verified_target: PumpOperatingTarget | None = None
    request_id: str | None = None
    token_id: str | None = None
    requested_at: datetime | None = None
    accepted_at: datetime | None = None
    outcome_unknown_at: datetime | None = None
    expires_at: datetime | None = None
    correlated_at: datetime | None = None
    correlated_target: PumpOperatingTarget | None = None

    def copy(self) -> "_TargetOverride":
        return _TargetOverride(
            state=self.state,
            source=self.source,
            requested_target=self.requested_target,
            verified_target=self.verified_target,
            request_id=self.request_id,
            token_id=self.token_id,
            requested_at=self.requested_at,
            accepted_at=self.accepted_at,
            outcome_unknown_at=self.outcome_unknown_at,
            expires_at=self.expires_at,
            correlated_at=self.correlated_at,
            correlated_target=self.correlated_target,
        )


@dataclass(slots=True)
class PumpTargetSessionRuntime:
    """Bound one exact body/purpose/PMPCIRC target session."""

    targets: PumpOperatingTargetPolicy
    pending_ttl: timedelta = timedelta(seconds=45)
    observation_freshness: timedelta = timedelta(seconds=30)
    _runtime_id: str = field(default_factory=lambda: uuid4().hex, init=False)
    _generation: int = field(default=0, init=False)
    _session_id: str | None = field(default=None, init=False)
    _body: PumpSpeedSessionBody | None = field(default=None, init=False)
    _purpose: PumpSpeedSessionPurpose | None = field(default=None, init=False)
    _pump_circuit_id: str | None = field(default=None, init=False)
    _connection_generation: int | None = field(default=None, init=False)
    _established_at: datetime | None = field(default=None, init=False)
    _last_observed_at: datetime | None = field(default=None, init=False)
    _last_configured_target: PumpOperatingTarget | None = field(default=None, init=False)
    _evidence_usable_current: bool = field(default=False, init=False)
    _last_session_reason: str = field(default="runtime_started", init=False)
    _last_override_reason: str = field(default="runtime_started_without_override", init=False)
    _override: _TargetOverride = field(default_factory=_TargetOverride, init=False)
    _prior_override_by_token: dict[str, _TargetOverride] = field(
        default_factory=dict, init=False, repr=False
    )
    _baseline_cancellation_request: PumpTargetManualRequest | None = field(
        default=None, init=False, repr=False
    )
    _last_native_transition_at: datetime | None = field(
        default=None, init=False, repr=False
    )

    def observe(self, evidence: PumpTargetSessionEvidence) -> PumpTargetSessionSnapshot:
        self._expire_pending(evidence.observed_at)
        if self._last_observed_at is not None and evidence.observed_at <= self._last_observed_at:
            return self.snapshot
        if not evidence.evidence_usable:
            self._evidence_usable_current = False
            self._last_observed_at = evidence.observed_at
            self._last_session_reason = "session_evidence_unusable_preserved"
            return self.snapshot
        self._evidence_usable_current = True
        self._last_observed_at = evidence.observed_at
        if (
            evidence.body is None
            or evidence.purpose is None
            or evidence.pump_circuit_id is None
            or evidence.configured_target is None
        ):
            self._end_session("authoritative_body_or_purpose_inactive")
            return self.snapshot

        # Unit is part of semantic session identity. A real controller mode
        # transition therefore starts a new pump-target session and clears any
        # previous-unit override instead of comparing ambiguous numbers.
        key = (
            evidence.body,
            evidence.purpose,
            evidence.pump_circuit_id,
            evidence.configured_target.unit,
        )
        current = (
            self._body,
            self._purpose,
            self._pump_circuit_id,
            None if self._last_configured_target is None else self._last_configured_target.unit,
        )
        generation_changed = (
            self._connection_generation is not None
            and evidence.connection_generation != self._connection_generation
        )
        if self._session_id is None or key != current or generation_changed:
            reason = (
                "connection_generation_changed"
                if generation_changed
                else "semantic_session_established"
                if self._session_id is None
                else "semantic_body_purpose_or_unit_changed"
            )
            self._start_session(evidence, reason)
            return self.snapshot
        self._last_configured_target = evidence.configured_target
        return self.snapshot

    def begin_manual_request(
        self,
        *,
        body: PumpSpeedSessionBody,
        pump_circuit_id: str,
        requested_target: PumpOperatingTarget,
        requested_at: datetime,
        request_id: str | None = None,
    ) -> PumpTargetManualRequest:
        _require_aware(requested_at)
        if (
            self._session_id is None
            or body is not self._body
            or pump_circuit_id != self._pump_circuit_id
            or self._purpose is None
            or not self._evidence_usable_current
        ):
            raise ValueError("manual pump target request does not match an active session")
        baseline = self.configured_baseline_target
        if baseline is None or requested_target.unit is not baseline.unit:
            raise ValueError("manual pump target unit must match the active configured policy")

        token = uuid4().hex
        request = request_id or str(uuid4())
        manual_request = PumpTargetManualRequest(
            token,
            request,
            self._session_id,
            body,
            pump_circuit_id,
            requested_target,
            requested_at,
        )
        if requested_target == baseline:
            self._override = _TargetOverride()
            self._prior_override_by_token.clear()
            self._baseline_cancellation_request = manual_request
            self._last_override_reason = "manual_request_returned_control_to_baseline"
            return manual_request

        self._baseline_cancellation_request = None
        self._prior_override_by_token.clear()
        self._prior_override_by_token[token] = (
            self._override.copy()
            if self._override.state is PumpSpeedOverrideState.VERIFIED
            else _TargetOverride()
        )
        self._override = _TargetOverride(
            state=PumpSpeedOverrideState.PENDING,
            source=PumpSpeedOverrideSource.POOLOS_MANUAL,
            requested_target=requested_target,
            request_id=request,
            token_id=token,
            requested_at=requested_at,
            expires_at=requested_at + self.pending_ttl,
        )
        self._last_override_reason = "manual_request_pending_delivery"
        return manual_request

    def manual_delivery_accepted(
        self,
        request: PumpTargetManualRequest,
        *,
        accepted_at: datetime,
    ) -> None:
        _require_aware(accepted_at)
        self._expire_pending(accepted_at)
        if not self._request_is_current(request):
            return
        if self._baseline_cancellation_request == request:
            self._baseline_cancellation_request = None
            self._last_override_reason = "manual_baseline_cancellation_delivered"
            return
        self._override.accepted_at = accepted_at
        if (
            self._last_configured_target == request.requested_target
            and self._last_observed_at is not None
            and timedelta(0) <= accepted_at - self._last_observed_at
            <= self.observation_freshness
        ):
            self._verify_override(
                request.requested_target,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "manual_noop_verified_by_fresh_configured_target",
            )
            return
        if (
            self._override.correlated_at is not None
            and self._override.correlated_target == request.requested_target
            and self._override.correlated_at >= request.requested_at
        ):
            self._verify_override(
                request.requested_target,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "correlated_manual_configured_target_verified_after_acceptance",
            )
            return
        self._last_override_reason = "manual_delivery_accepted_awaiting_native_target"

    def manual_delivery_outcome_unknown(
        self,
        request: PumpTargetManualRequest,
        *,
        outcome_unknown_at: datetime,
    ) -> None:
        _require_aware(outcome_unknown_at)
        self._expire_pending(outcome_unknown_at)
        if not self._request_is_current(request):
            return
        if self._baseline_cancellation_request == request:
            self._baseline_cancellation_request = None
            self._last_override_reason = (
                "manual_baseline_delivery_outcome_unknown_control_remains_at_baseline"
            )
            return
        self._override.outcome_unknown_at = outcome_unknown_at
        if (
            self._override.correlated_at is not None
            and self._override.correlated_target == request.requested_target
            and self._override.correlated_at >= request.requested_at
        ):
            self._verify_override(
                request.requested_target,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "correlated_manual_configured_target_verified_after_outcome_unknown",
            )
            return
        self._last_override_reason = (
            "manual_delivery_outcome_unknown_awaiting_native_target"
        )

    def manual_delivery_failed(self, request: PumpTargetManualRequest) -> None:
        if not self._request_is_current(request):
            return
        if self._baseline_cancellation_request == request:
            self._baseline_cancellation_request = None
            self._last_override_reason = (
                "manual_baseline_delivery_failed_control_remains_at_baseline"
            )
            return
        prior = self._prior_override_by_token.pop(request.token_id, _TargetOverride())
        self._override = prior
        self._last_override_reason = "manual_delivery_failed_prior_override_preserved"

    def apply_transition(self, transition: PumpTargetNativeTransition) -> None:
        self._expire_pending(transition.observed_at)
        if (
            self._session_id is None
            or self._pump_circuit_id != transition.native_object_id
            or self._established_at is None
            or transition.observed_at < self._established_at
            or (
                transition.observed_at == self._established_at
                and not transition.positive_operator_intent
            )
            or (
                self._last_native_transition_at is not None
                and transition.observed_at <= self._last_native_transition_at
            )
        ):
            return

        baseline = self.configured_baseline_target
        if (
            baseline is None
            or transition.previous_target.unit is not baseline.unit
            or transition.new_target.unit is not baseline.unit
        ):
            # Mode/unit transitions are session boundaries handled by observe();
            # never reinterpret them as an in-session numeric override.
            return

        self._last_native_transition_at = transition.observed_at
        self._last_configured_target = transition.new_target
        pending = self._override
        if transition.correlated_request_id is not None:
            if (
                pending.state is PumpSpeedOverrideState.PENDING
                and pending.request_id == transition.correlated_request_id
                and pending.requested_target == transition.new_target
            ):
                if pending.accepted_at is None and pending.outcome_unknown_at is None:
                    pending.correlated_at = transition.observed_at
                    pending.correlated_target = transition.new_target
                    self._last_override_reason = (
                        "correlated_native_target_awaiting_delivery_acceptance"
                    )
                    return
                if transition.new_target == baseline:
                    self._clear_override("correlated_return_to_baseline")
                else:
                    self._verify_override(
                        transition.new_target,
                        PumpSpeedOverrideSource.POOLOS_MANUAL,
                        "correlated_manual_configured_target_verified",
                    )
            return

        if (
            self._override.state is PumpSpeedOverrideState.PENDING
            and self._override.source is PumpSpeedOverrideSource.POOLOS_MANUAL
        ) or self._baseline_cancellation_request is not None:
            self._last_override_reason = (
                "unattributed_configured_target_ignored_during_pending_manual_request"
            )
            return

        if transition.new_target == baseline:
            self._clear_override("external_configured_target_returned_to_baseline")
        else:
            self._verify_override(
                transition.new_target,
                PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED,
                "external_configured_target_override_verified",
            )

    @property
    def configured_baseline_target(self) -> PumpOperatingTarget | None:
        return _baseline_for(self.targets, self._purpose)

    @property
    def effective_target(self) -> PumpOperatingTarget | None:
        if (
            self._override.state is PumpSpeedOverrideState.PENDING
            and self._override.requested_target is not None
        ):
            return self._override.requested_target
        if (
            self._override.state is PumpSpeedOverrideState.VERIFIED
            and self._override.verified_target is not None
        ):
            return self._override.verified_target
        return self.configured_baseline_target

    def effective_target_for(
        self,
        *,
        body: PumpSpeedSessionBody,
        purpose: PumpSpeedSessionPurpose,
        pump_circuit_id: str,
    ) -> PumpOperatingTarget | None:
        if (
            self._session_id is None
            or body is not self._body
            or purpose is not self._purpose
            or pump_circuit_id != self._pump_circuit_id
        ):
            return None
        return self.effective_target

    @property
    def snapshot(self) -> PumpTargetSessionSnapshot:
        return PumpTargetSessionSnapshot(
            active=self._session_id is not None,
            evidence_usable=self._evidence_usable_current,
            session_id=self._session_id,
            generation=self._generation,
            body=self._body,
            purpose=self._purpose,
            pump_circuit_id=self._pump_circuit_id,
            configured_baseline_target=self.configured_baseline_target,
            effective_target=self.effective_target,
            override_state=self._override.state,
            override_source=self._override.source,
            pending_requested_target=self._override.requested_target,
            verified_override_target=self._override.verified_target,
            last_session_transition_reason=self._last_session_reason,
            last_override_transition_reason=self._last_override_reason,
        )

    def diagnostics(self) -> Mapping[str, object]:
        state = self.snapshot
        return MappingProxyType(
            {
                "session_active": state.active,
                "session_evidence_usable": state.evidence_usable,
                "session_id": state.session_id,
                "session_generation": state.generation,
                "body": None if state.body is None else state.body.value,
                "purpose": None if state.purpose is None else state.purpose.value,
                "pump_circuit_id": state.pump_circuit_id,
                "configured_baseline_target": _target_diag(state.configured_baseline_target),
                "effective_session_target": _target_diag(state.effective_target),
                "override_state": state.override_state.value,
                "override_source": state.override_source.value,
                "pending_requested_target": _target_diag(state.pending_requested_target),
                "verified_override_target": _target_diag(state.verified_override_target),
                "last_session_transition_reason": state.last_session_transition_reason,
                "last_override_transition_reason": state.last_override_transition_reason,
                "runtime_started_with_reset_override_state": True,
                "persistent_override_storage_enabled": False,
                "authority": "none",
                "command_delivery_enabled": False,
            }
        )

    def reset_currentness(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("pump target session reset reason must not be empty")
        self._end_session(reason)
        self._connection_generation = None
        self._last_observed_at = None

    def _start_session(
        self,
        evidence: PumpTargetSessionEvidence,
        reason: str,
    ) -> None:
        self._generation += 1
        self._session_id = f"{self._runtime_id}:{self._generation}"
        self._body = evidence.body
        self._purpose = evidence.purpose
        self._pump_circuit_id = evidence.pump_circuit_id
        self._connection_generation = evidence.connection_generation
        self._established_at = evidence.observed_at
        self._last_observed_at = evidence.observed_at
        self._last_configured_target = evidence.configured_target
        self._evidence_usable_current = True
        self._last_native_transition_at = None
        self._override = _TargetOverride()
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_session_reason = reason
        self._last_override_reason = "session_boundary_cleared_override"

    def _end_session(self, reason: str) -> None:
        if self._session_id is not None:
            self._generation += 1
        self._session_id = None
        self._body = None
        self._purpose = None
        self._pump_circuit_id = None
        self._established_at = None
        self._last_configured_target = None
        self._evidence_usable_current = False
        self._last_native_transition_at = None
        self._override = _TargetOverride()
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_session_reason = reason
        self._last_override_reason = "session_ended_override_cleared"

    def _request_is_current(self, request: PumpTargetManualRequest) -> bool:
        if self._baseline_cancellation_request == request:
            return self._session_id == request.session_id
        return (
            self._session_id == request.session_id
            and self._body is request.body
            and self._pump_circuit_id == request.pump_circuit_id
            and self._override.token_id == request.token_id
            and self._override.request_id == request.request_id
        )

    def _verify_override(
        self,
        target: PumpOperatingTarget,
        source: PumpSpeedOverrideSource,
        reason: str,
    ) -> None:
        self._override = _TargetOverride(
            state=PumpSpeedOverrideState.VERIFIED,
            source=source,
            verified_target=target,
        )
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_override_reason = reason

    def _clear_override(self, reason: str) -> None:
        self._override = _TargetOverride()
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_override_reason = reason

    def _expire_pending(self, now: datetime) -> None:
        cancellation = self._baseline_cancellation_request
        if cancellation is not None and now >= cancellation.requested_at + self.pending_ttl:
            self._baseline_cancellation_request = None
            self._last_override_reason = "pending_baseline_cancellation_expired"
        if (
            self._override.state is PumpSpeedOverrideState.PENDING
            and self._override.expires_at is not None
            and now >= self._override.expires_at
        ):
            token = self._override.token_id
            prior = (
                _TargetOverride()
                if token is None
                else self._prior_override_by_token.pop(token, _TargetOverride())
            )
            self._override = prior
            self._last_override_reason = "pending_manual_request_expired"


def _baseline_for(
    targets: PumpOperatingTargetPolicy,
    purpose: PumpSpeedSessionPurpose | None,
) -> PumpOperatingTarget | None:
    if purpose is None:
        return None
    return {
        PumpSpeedSessionPurpose.ORDINARY: targets.filtration,
        PumpSpeedSessionPurpose.SOLAR: targets.solar_heating,
        PumpSpeedSessionPurpose.GAS: targets.gas_heating,
        PumpSpeedSessionPurpose.TEMPERATURE_PROBE: targets.temperature_probe,
        PumpSpeedSessionPurpose.PRIMING: targets.priming,
        PumpSpeedSessionPurpose.GRID_OUTAGE: targets.grid_outage,
    }.get(purpose)


def _target_diag(target: PumpOperatingTarget | None) -> dict[str, object] | None:
    if target is None:
        return None
    return {"unit": target.unit.value, "value": target.value}


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("pump target session timestamps must be timezone-aware")


__all__ = [
    "PumpTargetManualRequest",
    "PumpTargetNativeTransition",
    "PumpTargetSessionEvidence",
    "PumpTargetSessionRuntime",
    "PumpTargetSessionSnapshot",
]
