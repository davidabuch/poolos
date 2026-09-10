"""In-memory, body-bound pump-speed session and manual override state.

The runtime records operator intent for one already-established hydraulic
session.  It grants no body, source, cleanup, or physical command authority.
Configured PMPCIRC SPEED is the only native value used for override
attribution; parent-pump actual RPM remains separate verification evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from .operating_baselines import PumpOperatingBaselines


class PumpSpeedSessionBody(StrEnum):
    POOL = "pool"
    HOT_TUB = "hot_tub"


class PumpSpeedSessionPurpose(StrEnum):
    ORDINARY = "ordinary_circulation"
    SOLAR = "solar_heating"
    GAS = "gas_heating"
    TEMPERATURE_PROBE = "temperature_acquisition"
    PRIMING = "priming"
    GRID_OUTAGE = "grid_outage"


class PumpSpeedOverrideState(StrEnum):
    NONE = "none"
    PENDING = "pending"
    VERIFIED = "verified"


class PumpSpeedOverrideSource(StrEnum):
    NONE = "none"
    POOLOS_MANUAL = "poolos_manual"
    EXTERNAL_UNATTRIBUTED = "external_unattributed"


@dataclass(frozen=True, slots=True)
class PumpSpeedSessionEvidence:
    """Current authoritative facts required to establish one session."""

    observed_at: datetime
    body: PumpSpeedSessionBody | None
    purpose: PumpSpeedSessionPurpose | None
    pump_circuit_id: str | None
    configured_speed_rpm: int | None
    connection_generation: int
    evidence_usable: bool

    def __post_init__(self) -> None:
        _require_aware(self.observed_at)
        if self.connection_generation < 0:
            raise ValueError("connection_generation must be nonnegative")
        if self.configured_speed_rpm is not None and (
            type(self.configured_speed_rpm) is not int
            or self.configured_speed_rpm <= 0
        ):
            raise ValueError("configured_speed_rpm must be a positive integer")


@dataclass(frozen=True, slots=True)
class PumpSpeedSessionSnapshot:
    active: bool
    evidence_usable: bool
    session_id: str | None
    generation: int
    body: PumpSpeedSessionBody | None
    purpose: PumpSpeedSessionPurpose | None
    pump_circuit_id: str | None
    configured_baseline_rpm: int | None
    effective_rpm: int | None
    override_state: PumpSpeedOverrideState
    override_source: PumpSpeedOverrideSource
    pending_requested_rpm: int | None
    verified_override_rpm: int | None
    last_session_transition_reason: str
    last_override_transition_reason: str
    reset_on_runtime_start: bool = True


@dataclass(frozen=True, slots=True)
class PumpSpeedManualRequest:
    """One transactional explicit HA/manual intent."""

    token_id: str
    request_id: str
    session_id: str
    body: PumpSpeedSessionBody
    pump_circuit_id: str
    requested_rpm: int
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class PumpSpeedNativeTransition:
    """One accepted configured PMPCIRC transition from ADR-107."""

    concept: str
    native_object_id: str
    previous_rpm: int
    new_rpm: int
    observed_at: datetime
    correlated_request_id: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at)
        if type(self.previous_rpm) is not int or type(self.new_rpm) is not int:
            raise ValueError("configured-speed transition values must be integers")


@dataclass(slots=True)
class _Override:
    state: PumpSpeedOverrideState = PumpSpeedOverrideState.NONE
    source: PumpSpeedOverrideSource = PumpSpeedOverrideSource.NONE
    requested_rpm: int | None = None
    verified_rpm: int | None = None
    request_id: str | None = None
    token_id: str | None = None
    requested_at: datetime | None = None
    accepted_at: datetime | None = None
    outcome_unknown_at: datetime | None = None
    expires_at: datetime | None = None
    correlated_at: datetime | None = None
    correlated_rpm: int | None = None

    def copy(self) -> _Override:
        return _Override(
            state=self.state,
            source=self.source,
            requested_rpm=self.requested_rpm,
            verified_rpm=self.verified_rpm,
            request_id=self.request_id,
            token_id=self.token_id,
            requested_at=self.requested_at,
            accepted_at=self.accepted_at,
            outcome_unknown_at=self.outcome_unknown_at,
            expires_at=self.expires_at,
            correlated_at=self.correlated_at,
            correlated_rpm=self.correlated_rpm,
        )


@dataclass(slots=True)
class PumpSpeedSessionRuntime:
    """Own one bounded in-memory session controller for one config entry."""

    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
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
    _last_configured_rpm: int | None = field(default=None, init=False)
    _evidence_usable_current: bool = field(default=False, init=False)
    _last_session_reason: str = field(default="runtime_started", init=False)
    _last_override_reason: str = field(default="runtime_started_without_override", init=False)
    _override: _Override = field(default_factory=_Override, init=False)
    _prior_override_by_token: dict[str, _Override] = field(
        default_factory=dict, init=False, repr=False
    )
    _baseline_cancellation_request: PumpSpeedManualRequest | None = field(
        default=None, init=False, repr=False
    )
    _last_native_transition_at: datetime | None = field(
        default=None, init=False, repr=False
    )

    def observe(self, evidence: PumpSpeedSessionEvidence) -> PumpSpeedSessionSnapshot:
        """Apply session boundaries before any configured-speed attribution."""

        self._expire_pending(evidence.observed_at)
        if (
            self._last_observed_at is not None
            and evidence.observed_at <= self._last_observed_at
        ):
            return self.snapshot
        if not evidence.evidence_usable:
            self._evidence_usable_current = False
            # An unusable frame cannot change semantic state, but its accepted
            # chronology still prevents an older later frame from doing so.
            self._last_observed_at = evidence.observed_at
            self._last_session_reason = "session_evidence_unusable_preserved"
            return self.snapshot
        self._evidence_usable_current = True
        self._last_observed_at = evidence.observed_at
        if (
            evidence.body is None
            or evidence.purpose is None
            or evidence.pump_circuit_id is None
            or evidence.configured_speed_rpm is None
        ):
            self._end_session("authoritative_body_or_purpose_inactive")
            return self.snapshot
        key = (evidence.body, evidence.purpose, evidence.pump_circuit_id)
        current = (self._body, self._purpose, self._pump_circuit_id)
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
                else "semantic_body_or_purpose_changed"
            )
            self._start_session(evidence, reason)
            return self.snapshot
        self._last_configured_rpm = evidence.configured_speed_rpm
        return self.snapshot

    def begin_manual_request(
        self,
        *,
        body: PumpSpeedSessionBody,
        pump_circuit_id: str,
        requested_rpm: int,
        requested_at: datetime,
        request_id: str | None = None,
    ) -> PumpSpeedManualRequest:
        """Reserve one explicit intent without claiming delivery or verification."""

        _require_aware(requested_at)
        if type(requested_rpm) is not int or requested_rpm <= 0:
            raise ValueError("manual pump RPM must be a positive integer")
        if (
            self._session_id is None
            or body is not self._body
            or pump_circuit_id != self._pump_circuit_id
            or self._purpose is None
            or not self._evidence_usable_current
        ):
            raise ValueError("manual pump request does not match an active session")
        token = uuid4().hex
        request = request_id or str(uuid4())
        manual_request = PumpSpeedManualRequest(
            token,
            request,
            self._session_id,
            body,
            pump_circuit_id,
            requested_rpm,
            requested_at,
        )
        if requested_rpm == self.configured_baseline_rpm:
            self._override = _Override()
            self._prior_override_by_token.clear()
            self._baseline_cancellation_request = manual_request
            self._last_override_reason = "manual_request_returned_control_to_baseline"
            return manual_request
        self._baseline_cancellation_request = None
        self._prior_override_by_token.clear()
        self._prior_override_by_token[token] = (
            self._override.copy()
            if self._override.state is PumpSpeedOverrideState.VERIFIED
            else _Override()
        )
        self._override = _Override(
            state=PumpSpeedOverrideState.PENDING,
            source=PumpSpeedOverrideSource.POOLOS_MANUAL,
            requested_rpm=requested_rpm,
            request_id=request,
            token_id=token,
            requested_at=requested_at,
            expires_at=requested_at + self.pending_ttl,
        )
        self._last_override_reason = "manual_request_pending_delivery"
        return manual_request

    def manual_delivery_accepted(
        self,
        request: PumpSpeedManualRequest,
        *,
        accepted_at: datetime,
    ) -> None:
        """Record transport acceptance; verification remains a separate fact."""

        _require_aware(accepted_at)
        self._expire_pending(accepted_at)
        if not self._request_is_current(request):
            return
        if self._baseline_cancellation_request == request:
            self._baseline_cancellation_request = None
            self._last_override_reason = "manual_baseline_cancellation_delivered"
            return
        self._override.accepted_at = accepted_at
        # ADR-107 retains no transition expectation for a native no-op.  An
        # accepted explicit request plus fresh exact authoritative configured
        # SPEED is sufficient to attribute intent without inventing a future
        # transition or using actual motor RPM.
        if (
            self._last_configured_rpm == request.requested_rpm
            and self._last_observed_at is not None
            and timedelta(0) <= accepted_at - self._last_observed_at
            <= self.observation_freshness
        ):
            self._verify_override(
                request.requested_rpm,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "manual_noop_verified_by_fresh_configured_speed",
            )
            return
        if (
            self._override.correlated_at is not None
            and self._override.correlated_rpm == request.requested_rpm
            and self._override.correlated_at >= request.requested_at
        ):
            self._verify_override(
                request.requested_rpm,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "correlated_manual_configured_speed_verified_after_acceptance",
            )
            return
        self._last_override_reason = "manual_delivery_accepted_awaiting_native_speed"

    def manual_delivery_outcome_unknown(
        self,
        request: PumpSpeedManualRequest,
        *,
        outcome_unknown_at: datetime,
    ) -> None:
        """Retain a dispatched request until authoritative native truth resolves it."""

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
            and self._override.correlated_rpm == request.requested_rpm
            and self._override.correlated_at >= request.requested_at
        ):
            self._verify_override(
                request.requested_rpm,
                PumpSpeedOverrideSource.POOLOS_MANUAL,
                "correlated_manual_configured_speed_verified_after_outcome_unknown",
            )
            return

        self._last_override_reason = (
            "manual_delivery_outcome_unknown_awaiting_native_speed"
        )

    def manual_delivery_failed(self, request: PumpSpeedManualRequest) -> None:
        """Roll back only the failed current transaction."""

        if not self._request_is_current(request):
            return
        if self._baseline_cancellation_request == request:
            self._baseline_cancellation_request = None
            self._last_override_reason = (
                "manual_baseline_delivery_failed_control_remains_at_baseline"
            )
            return
        prior = self._prior_override_by_token.pop(request.token_id, _Override())
        self._override = prior
        self._last_override_reason = "manual_delivery_failed_prior_override_preserved"

    def apply_transition(self, transition: PumpSpeedNativeTransition) -> None:
        """Adopt one chronological configured-speed transition in this session."""

        self._expire_pending(transition.observed_at)
        if (
            self._session_id is None
            or self._pump_circuit_id != transition.native_object_id
            or self._established_at is None
            or transition.observed_at <= self._established_at
            or (
                self._last_native_transition_at is not None
                and transition.observed_at <= self._last_native_transition_at
            )
        ):
            return
        self._last_native_transition_at = transition.observed_at
        self._last_configured_rpm = transition.new_rpm
        pending = self._override
        if transition.correlated_request_id is not None:
            if (
                pending.state is PumpSpeedOverrideState.PENDING
                and pending.request_id == transition.correlated_request_id
                and pending.requested_rpm == transition.new_rpm
            ):
                if (
                    pending.accepted_at is None
                    and pending.outcome_unknown_at is None
                ):
                    pending.correlated_at = transition.observed_at
                    pending.correlated_rpm = transition.new_rpm
                    self._last_override_reason = (
                        "correlated_native_speed_awaiting_delivery_acceptance"
                    )
                    return
                baseline = self.configured_baseline_rpm
                if transition.new_rpm == baseline:
                    self._clear_override("correlated_return_to_baseline")
                else:
                    self._verify_override(
                        transition.new_rpm,
                        PumpSpeedOverrideSource.POOLOS_MANUAL,
                        "correlated_manual_configured_speed_verified",
                    )
            return
        baseline = self.configured_baseline_rpm
        if transition.new_rpm == baseline:
            self._clear_override("external_return_to_session_baseline")
        else:
            self._verify_override(
                transition.new_rpm,
                PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED,
                "external_configured_speed_override_adopted",
            )

    @property
    def configured_baseline_rpm(self) -> int | None:
        return _baseline_for(self.baselines, self._purpose)

    @property
    def effective_rpm(self) -> int | None:
        if (
            self._override.state is PumpSpeedOverrideState.PENDING
            and self._override.requested_rpm is not None
        ):
            return self._override.requested_rpm
        if (
            self._override.state is PumpSpeedOverrideState.VERIFIED
            and self._override.verified_rpm is not None
        ):
            return self._override.verified_rpm
        return self.configured_baseline_rpm

    def effective_rpm_for(
        self,
        *,
        body: PumpSpeedSessionBody,
        purpose: PumpSpeedSessionPurpose,
        pump_circuit_id: str,
    ) -> int | None:
        """Return an override only for the exact current body/purpose/PMPCIRC."""

        if (
            self._session_id is None
            or body is not self._body
            or purpose is not self._purpose
            or pump_circuit_id != self._pump_circuit_id
        ):
            return None
        return self.effective_rpm

    @property
    def snapshot(self) -> PumpSpeedSessionSnapshot:
        return PumpSpeedSessionSnapshot(
            active=self._session_id is not None,
            evidence_usable=self._evidence_usable_current,
            session_id=self._session_id,
            generation=self._generation,
            body=self._body,
            purpose=self._purpose,
            pump_circuit_id=self._pump_circuit_id,
            configured_baseline_rpm=self.configured_baseline_rpm,
            effective_rpm=self.effective_rpm,
            override_state=self._override.state,
            override_source=self._override.source,
            pending_requested_rpm=self._override.requested_rpm,
            verified_override_rpm=self._override.verified_rpm,
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
                "configured_baseline_rpm": state.configured_baseline_rpm,
                "effective_session_rpm": state.effective_rpm,
                "override_state": state.override_state.value,
                "override_source": state.override_source.value,
                "pending_requested_rpm": state.pending_requested_rpm,
                "verified_override_rpm": state.verified_override_rpm,
                "last_session_transition_reason": state.last_session_transition_reason,
                "last_override_transition_reason": state.last_override_transition_reason,
                "runtime_started_with_reset_override_state": True,
                "persistent_override_storage_enabled": False,
                "authority": "none",
                "command_delivery_enabled": False,
            }
        )

    def reset_currentness(self, reason: str) -> None:
        """Clear ephemeral intent at reload/reconnect/Maintenance boundaries."""

        if not reason.strip():
            raise ValueError("pump session reset reason must not be empty")
        self._end_session(reason)
        self._connection_generation = None
        self._last_observed_at = None

    def _start_session(
        self,
        evidence: PumpSpeedSessionEvidence,
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
        self._last_configured_rpm = evidence.configured_speed_rpm
        self._evidence_usable_current = True
        self._last_native_transition_at = None
        self._override = _Override()
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
        self._last_configured_rpm = None
        self._evidence_usable_current = False
        self._last_native_transition_at = None
        self._override = _Override()
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_session_reason = reason
        self._last_override_reason = "session_ended_override_cleared"

    def _request_is_current(self, request: PumpSpeedManualRequest) -> bool:
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
        rpm: int,
        source: PumpSpeedOverrideSource,
        reason: str,
    ) -> None:
        self._override = _Override(
            state=PumpSpeedOverrideState.VERIFIED,
            source=source,
            verified_rpm=rpm,
        )
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_override_reason = reason

    def _clear_override(self, reason: str) -> None:
        self._override = _Override()
        self._prior_override_by_token.clear()
        self._baseline_cancellation_request = None
        self._last_override_reason = reason

    def _expire_pending(self, now: datetime) -> None:
        cancellation = self._baseline_cancellation_request
        if (
            cancellation is not None
            and now >= cancellation.requested_at + self.pending_ttl
        ):
            self._baseline_cancellation_request = None
            self._last_override_reason = "pending_baseline_cancellation_expired"
        if (
            self._override.state is PumpSpeedOverrideState.PENDING
            and self._override.expires_at is not None
            and now >= self._override.expires_at
        ):
            token = self._override.token_id
            prior = (
                _Override()
                if token is None
                else self._prior_override_by_token.pop(token, _Override())
            )
            self._override = prior
            self._last_override_reason = "pending_manual_request_expired"


def _baseline_for(
    baselines: PumpOperatingBaselines,
    purpose: PumpSpeedSessionPurpose | None,
) -> int | None:
    if purpose is None:
        return None
    return {
        PumpSpeedSessionPurpose.ORDINARY: baselines.filtration_rpm,
        PumpSpeedSessionPurpose.SOLAR: baselines.solar_heating_rpm,
        PumpSpeedSessionPurpose.GAS: baselines.gas_heating_rpm,
        PumpSpeedSessionPurpose.TEMPERATURE_PROBE: baselines.temperature_probe_rpm,
        PumpSpeedSessionPurpose.PRIMING: baselines.priming_rpm,
        PumpSpeedSessionPurpose.GRID_OUTAGE: baselines.grid_outage_rpm,
    }.get(purpose)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("pump session timestamps must be timezone-aware")


__all__ = [
    "PumpSpeedManualRequest",
    "PumpSpeedNativeTransition",
    "PumpSpeedOverrideSource",
    "PumpSpeedOverrideState",
    "PumpSpeedSessionBody",
    "PumpSpeedSessionEvidence",
    "PumpSpeedSessionPurpose",
    "PumpSpeedSessionRuntime",
    "PumpSpeedSessionSnapshot",
]
