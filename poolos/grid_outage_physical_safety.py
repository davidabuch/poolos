"""Confirmed-grid-outage reduction policy and in-memory execution lifecycle.

The core model is intentionally transport-free.  It consumes the canonical
two-second outage assessment and current authoritative observations, selects at
most one exact reduction, and requires a later observation to verify delivery.
It never starts circulation, restores pre-outage state, or grants normal
thermal ownership.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Iterable, Mapping

from .clock import FixedClock
from .external_change import (
    ExternalChangeBatch,
    GRID_OUTAGE_SAFETY_TAKEOVER_CONCEPTS,
)
from .filtration_policy import FiltrationAccountingSnapshot, FiltrationDisposition
from .grid_outage_confirmation import GridOutageAssessment, GridOutageDisposition
from .intellicenter_readonly import (
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    is_pmpcirc_native_id,
)
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from .operating_baselines import PumpOperatingBaselines


_FRESHNESS = FreshnessPolicy(max_age=timedelta(seconds=30))
_QUALITIES = frozenset({ObservationQuality.GOOD, ObservationQuality.DEGRADED})
_MINIMUM_CONFIDENCE = 0.5
_KNOWN_SOURCES = frozenset({"00000", "H0001", "H0002"})
_OUTAGE_RPM = PumpOperatingBaselines().grid_outage_rpm
_RPM_TOLERANCE = 25
_VERIFICATION_TIMEOUT = timedelta(seconds=45)


class OutageCirculationDisposition(StrEnum):
    """Whether already-established Pool circulation must remain now."""

    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    BLOCKED = "blocked"


class GridOutageReductionKind(StrEnum):
    """The complete allow-list of confirmed-outage reductions."""

    SPA_SOURCE_OFF = "spa_source_off"
    POOL_SOURCE_OFF = "pool_source_off"
    POOL_LIGHT_OFF = "pool_light_off"
    JETS_OFF = "jets_off"
    SLIDE_OFF = "slide_off"
    WATERFALL_OFF = "waterfall_off"
    SPA_BODY_OFF = "spa_body_off"
    POOL_PUMP_REDUCTION = "pool_pump_reduction"


class GridOutageSafetyLifecycle(StrEnum):
    INACTIVE = "inactive"
    GATE_DISABLED = "confirmed_gate_disabled"
    BLOCKED = "blocked"
    CANDIDATE_READY = "candidate_ready"
    AWAITING_VERIFICATION = "awaiting_verification"
    PROGRESS = "progress"
    UNRESOLVED_OUTAGE = "unresolved_outage"
    ENDED = "ended"
    FAILED = "failed"
    UNLOADED = "unloaded"


@dataclass(frozen=True, slots=True)
class OutageCirculationRequirementAssessment:
    """Pure answer about retaining circulation which already exists."""

    disposition: OutageCirculationDisposition
    evaluated_at: datetime
    reason_code: str
    circulation_established: bool | None
    filtration_immediate: bool | None
    source_shutdown_pending: bool
    spa_shutdown_pending: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at)
        if not self.reason_code.strip():
            raise ValueError("circulation assessment reason is required")
        object.__setattr__(self, "blockers", tuple(self.blockers[:12]))


@dataclass(frozen=True, slots=True)
class GridOutageReductionCandidate:
    """One exact, current, reduction-only physical envelope."""

    candidate_id: str
    outage_epoch_id: str
    frame_identity: str
    kind: GridOutageReductionKind
    operation: str
    target: str
    requested_value: bool | int | str
    expected_concept: str
    expected_native_object_id: str
    priority: int
    evidence_fingerprint: str
    formed_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "outage_epoch_id",
            "frame_identity",
            "operation",
            "target",
            "expected_concept",
            "expected_native_object_id",
            "evidence_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.kind is GridOutageReductionKind.POOL_PUMP_REDUCTION:
            if not (
                self.operation == "pump_circuit_speed"
                and is_pmpcirc_native_id(self.target)
                and type(self.requested_value) is int
                and self.requested_value == _OUTAGE_RPM
                and self.expected_concept
                == POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
                and self.expected_native_object_id == self.target
                and self.priority == 9
            ):
                raise ValueError(
                    "outage pump candidate does not match its bound Pool PMPCIRC"
                )
            if self.formed_at is not None:
                _require_aware(self.formed_at)
            return
        expected = _CANDIDATE_SHAPES[self.kind]
        actual = (
            self.operation,
            self.target,
            self.requested_value,
            self.expected_concept,
            self.expected_native_object_id,
            self.priority,
        )
        if not (
            actual[:2] == expected[:2]
            and type(actual[2]) is type(expected[2])
            and actual[2:] == expected[2:]
        ):
            raise ValueError("outage candidate does not match its exact allow-list shape")
        if self.formed_at is not None:
            _require_aware(self.formed_at)


_CANDIDATE_SHAPES: Mapping[
    GridOutageReductionKind, tuple[str, str, bool | int | str, str, str, int]
] = MappingProxyType(
    {
        GridOutageReductionKind.SPA_SOURCE_OFF: (
            "body_heat_source",
            "B1202",
            "00000",
            "spa.raw_heater_id",
            "B1202",
            1,
        ),
        GridOutageReductionKind.POOL_SOURCE_OFF: (
            "body_heat_source",
            "B1101",
            "00000",
            "pool.raw_heater_id",
            "B1101",
            2,
        ),
        GridOutageReductionKind.POOL_LIGHT_OFF: (
            "circuit_active",
            "C0002",
            False,
            "pool_light.active",
            "C0002",
            3,
        ),
        GridOutageReductionKind.JETS_OFF: (
            "circuit_active",
            "C0003",
            False,
            "jets.active",
            "C0003",
            4,
        ),
        GridOutageReductionKind.SLIDE_OFF: (
            "circuit_active",
            "C0004",
            False,
            "slide.active",
            "C0004",
            5,
        ),
        GridOutageReductionKind.WATERFALL_OFF: (
            "circuit_active",
            "FTR01",
            False,
            "waterfall.active",
            "FTR01",
            6,
        ),
        GridOutageReductionKind.SPA_BODY_OFF: (
            "body_active",
            "B1202",
            False,
            "spa.active",
            "B1202",
            7,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class GridOutageSafetyFrame:
    """One immutable authoritative decision frame within an outage."""

    frame_identity: str
    observed_at: datetime
    observations: tuple[PoolObservation, ...]
    outage: GridOutageAssessment
    filtration: FiltrationAccountingSnapshot | None
    physical_authority_ready: bool
    transport_ready: bool
    pool_pump_circuit_id: str | None = None
    external_preemption_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.frame_identity.strip():
            raise ValueError("outage frame identity must not be empty")
        _require_aware(self.observed_at)
        object.__setattr__(self, "observations", tuple(self.observations))


@dataclass(frozen=True, slots=True)
class GridOutageDeliveryAttempt:
    candidate: GridOutageReductionCandidate
    accepted_at: datetime
    verification_deadline: datetime

    def __post_init__(self) -> None:
        _require_aware(self.accepted_at)
        _require_aware(self.verification_deadline)
        if self.verification_deadline <= self.accepted_at:
            raise ValueError("verification deadline must follow acceptance")


@dataclass(frozen=True, slots=True)
class GridOutageSafetyAssessment:
    lifecycle: GridOutageSafetyLifecycle
    evaluated_at: datetime
    outage_epoch_id: str | None
    frame_identity: str | None
    gate_requested: bool
    gate_effective: bool
    gate_generation: int
    reason_code: str
    candidate: GridOutageReductionCandidate | None
    circulation: OutageCirculationRequirementAssessment | None
    attempt: GridOutageDeliveryAttempt | None
    last_verified_reduction: GridOutageReductionKind | None
    command_delivery_performed: bool
    command_delivery_enabled: bool

    def diagnostics(self) -> Mapping[str, object]:
        candidate = self.candidate
        attempt = self.attempt
        circulation = self.circulation
        return MappingProxyType(
            {
                "state": self.lifecycle.value,
                "evaluated_at": self.evaluated_at.isoformat(),
                "outage_epoch_id": self.outage_epoch_id,
                "frame_identity": self.frame_identity,
                "outage_gate_requested": self.gate_requested,
                "outage_gate_effective": self.gate_effective,
                "gate_generation": self.gate_generation,
                "reason_code": self.reason_code[:256],
                "candidate_kind": None if candidate is None else candidate.kind.value,
                "candidate_id": None if candidate is None else candidate.candidate_id,
                "candidate_target": None if candidate is None else candidate.target,
                "candidate_operation": None if candidate is None else candidate.operation,
                "candidate_value": None if candidate is None else candidate.requested_value,
                "circulation_disposition": (
                    None if circulation is None else circulation.disposition.value
                ),
                "circulation_reason": (None if circulation is None else circulation.reason_code),
                "circulation_established": (
                    None if circulation is None else circulation.circulation_established
                ),
                "circulation_blockers": ([] if circulation is None else list(circulation.blockers)),
                "awaiting_verification": attempt is not None,
                "verification_deadline": (
                    None if attempt is None else attempt.verification_deadline.isoformat()
                ),
                "last_verified_reduction": (
                    None
                    if self.last_verified_reduction is None
                    else self.last_verified_reduction.value
                ),
                "command_delivery_performed": self.command_delivery_performed,
                "command_delivery_enabled": self.command_delivery_enabled,
                "restoration_enabled": False,
                "starts_circulation": False,
            }
        )


@dataclass(frozen=True, slots=True)
class _ObservationState:
    value: object
    usable: bool
    observed_at: datetime | None


def assess_outage_circulation_requirement(
    frame: GridOutageSafetyFrame,
) -> OutageCirculationRequirementAssessment:
    """Assess only whether proven existing Pool circulation must be retained."""

    by_id = {item.observation_id: item for item in frame.observations}
    states = {
        name: _state(by_id.get(name), frame.observed_at)
        for name in (
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.raw_heater_id",
            "spa.raw_heater_id",
            "pool_light.active",
            "jets.active",
            "slide.active",
            "waterfall.active",
            "freeze.active",
        )
    }
    blockers: list[str] = []
    for name in (
        "pool.active",
        "spa.active",
        "pump.rpm",
        "jets.active",
        "slide.active",
        "waterfall.active",
        "freeze.active",
    ):
        if not states[name].usable:
            blockers.append(f"outage_circulation_evidence_unusable:{name}")

    pool_active = _boolean(states["pool.active"])
    spa_active = _boolean(states["spa.active"])
    pump_rpm = _number(states["pump.rpm"])
    circulation = (
        None
        if pool_active is None or spa_active is None or pump_rpm is None
        else pool_active and not spa_active and pump_rpm > 0
    )
    pool_source = _source(states["pool.raw_heater_id"])
    spa_source = _source(states["spa.raw_heater_id"])
    if pool_active and states["pool.raw_heater_id"].usable and pool_source is None:
        blockers.append("outage_circulation_pool_source_unrecognized")
    if spa_active and states["spa.raw_heater_id"].usable and spa_source is None:
        blockers.append("outage_circulation_spa_source_unrecognized")
    if pool_active and spa_active:
        blockers.append("outage_circulation_topology_contradictory")
    if pool_active and not states["pool.raw_heater_id"].usable:
        blockers.append("outage_circulation_evidence_unusable:pool.raw_heater_id")
    if spa_active and not states["spa.raw_heater_id"].usable:
        blockers.append("outage_circulation_evidence_unusable:spa.raw_heater_id")

    filtration_immediate: bool | None = None
    if frame.filtration is None:
        blockers.append("outage_circulation_filtration_evidence_missing")
    elif frame.filtration.evaluated_at > frame.observed_at or (
        frame.observed_at - frame.filtration.evaluated_at > _FRESHNESS.max_age
    ):
        blockers.append("outage_circulation_filtration_evidence_stale")
    else:
        filtration_immediate = frame.filtration.disposition in {
            FiltrationDisposition.CREDITING,
            FiltrationDisposition.RUN_NOW,
        }

    source_pending = bool(
        (pool_active and pool_source in {"H0001", "H0002"})
        or (spa_active and spa_source in {"H0001", "H0002"})
    )
    spa_pending = spa_active is True
    required = filtration_immediate is True or source_pending or spa_pending
    if blockers:
        disposition = OutageCirculationDisposition.BLOCKED
        reason = blockers[0]
    elif required and circulation is not True:
        disposition = OutageCirculationDisposition.BLOCKED
        reason = "required_circulation_not_established"
        blockers.append(reason)
    elif required:
        disposition = OutageCirculationDisposition.REQUIRED
        reason = (
            "outage_circulation_source_shutdown_pending"
            if source_pending
            else "outage_circulation_spa_shutdown_pending"
            if spa_pending
            else "outage_circulation_filtration_immediate"
        )
    else:
        unsafe = [
            name
            for name in ("jets.active", "slide.active", "waterfall.active")
            if _boolean(states[name]) is not False
        ]
        if unsafe or _boolean(states["freeze.active"]) is not False:
            disposition = OutageCirculationDisposition.BLOCKED
            reason = (
                "outage_circulation_freeze_active"
                if _boolean(states["freeze.active"]) is True
                else f"outage_circulation_hydraulic_not_off:{unsafe[0]}"
            )
            blockers.append(reason)
        elif spa_active is not False or (pool_active is True and pool_source != "00000"):
            disposition = OutageCirculationDisposition.BLOCKED
            reason = "outage_circulation_shutdown_not_complete"
            blockers.append(reason)
        else:
            disposition = OutageCirculationDisposition.NOT_REQUIRED
            reason = "outage_circulation_not_required_proven"

    return OutageCirculationRequirementAssessment(
        disposition=disposition,
        evaluated_at=frame.observed_at,
        reason_code=reason,
        circulation_established=circulation,
        filtration_immediate=filtration_immediate,
        source_shutdown_pending=source_pending,
        spa_shutdown_pending=spa_pending,
        blockers=tuple(blockers),
    )


@dataclass(slots=True)
class GridOutagePhysicalSafetyEngine:
    """Select and verify one exact reduction per authoritative frame."""

    gate_requested: bool = False
    gate_generation: int = 0
    assessment: GridOutageSafetyAssessment | None = None
    _enabled_after: datetime | None = field(default=None, init=False, repr=False)
    _outage_epoch_id: str | None = field(default=None, init=False, repr=False)
    _attempt: GridOutageDeliveryAttempt | None = field(default=None, init=False, repr=False)
    _last_verified: GridOutageReductionKind | None = field(default=None, init=False, repr=False)
    _last_delivery_frame: str | None = field(default=None, init=False, repr=False)
    _blocked_outage_epoch: str | None = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)

    def set_enabled(self, enabled: bool, *, changed_at: datetime) -> None:
        _require_aware(changed_at)
        if self._unloaded:
            return
        if self.gate_requested == bool(enabled):
            return
        self.gate_requested = bool(enabled)
        self.gate_generation += 1
        self._enabled_after = changed_at if enabled else None
        if not enabled and self._attempt is not None:
            self._blocked_outage_epoch = self._outage_epoch_id
        self._attempt = None
        self._last_delivery_frame = None
        self.assessment = self._result(
            lifecycle=(
                GridOutageSafetyLifecycle.BLOCKED
                if enabled
                else GridOutageSafetyLifecycle.GATE_DISABLED
            ),
            at=changed_at,
            frame=None,
            reason=(
                "grid_outage_fresh_frame_required_after_enable"
                if enabled
                else "grid_outage_physical_gate_disabled"
            ),
        )

    def unload(self, *, unloaded_at: datetime) -> None:
        _require_aware(unloaded_at)
        self._unloaded = True
        self.gate_requested = False
        self.gate_generation += 1
        self._enabled_after = None
        self._outage_epoch_id = None
        self._attempt = None
        self._last_delivery_frame = None
        self._blocked_outage_epoch = None
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.UNLOADED,
            at=unloaded_at,
            frame=None,
            reason="grid_outage_safety_unloaded",
        )

    def fail_closed(self, *, failed_at: datetime, reason: str) -> None:
        """Invalidate readiness after a newer frame cannot be evaluated."""

        _require_aware(failed_at)
        if self._unloaded:
            return
        if self._attempt is not None:
            self._blocked_outage_epoch = self._outage_epoch_id
        self._attempt = None
        self._last_delivery_frame = None
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.FAILED,
            at=failed_at,
            frame=None,
            reason=f"grid_outage_safety_evaluation_failed:{reason[:160]}",
        )

    def evaluate(self, frame: GridOutageSafetyFrame) -> GridOutageSafetyAssessment:
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        outage = frame.outage
        if outage.disposition is GridOutageDisposition.ON_GRID:
            self._outage_epoch_id = None
            self._attempt = None
            self._last_delivery_frame = None
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.ENDED,
                at=frame.observed_at,
                frame=frame,
                reason="grid_returned_authoritatively_no_restore",
            )
            return self.assessment
        if outage.disposition is GridOutageDisposition.UNKNOWN:
            if (
                self._attempt is not None
                and frame.observed_at >= self._attempt.verification_deadline
            ):
                self._attempt = None
                self.assessment = self._result(
                    lifecycle=GridOutageSafetyLifecycle.FAILED,
                    at=frame.observed_at,
                    frame=frame,
                    reason="grid_outage_verification_timed_out_while_unresolved",
                )
                return self.assessment
            lifecycle = (
                GridOutageSafetyLifecycle.UNRESOLVED_OUTAGE
                if outage.unresolved_confirmed_outage_since is not None
                else GridOutageSafetyLifecycle.INACTIVE
            )
            self.assessment = self._result(
                lifecycle=lifecycle,
                at=frame.observed_at,
                frame=frame,
                reason="grid_outage_evidence_unresolved_no_new_authority",
            )
            return self.assessment
        if outage.disposition is not GridOutageDisposition.CONFIRMED_OUTAGE:
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.INACTIVE,
                at=frame.observed_at,
                frame=frame,
                reason="grid_outage_not_confirmed",
            )
            return self.assessment

        epoch = _epoch_id(outage)
        prior_attempt: GridOutageDeliveryAttempt | None = None
        if epoch != self._outage_epoch_id:
            prior_attempt = self._attempt
            self._outage_epoch_id = epoch
            self._attempt = None
            self._last_delivery_frame = None
            self._last_verified = None
            self._blocked_outage_epoch = None

        circulation = assess_outage_circulation_requirement(frame)
        if prior_attempt is not None:
            return self._store_blocked(
                frame,
                circulation,
                "grid_outage_prior_epoch_attempt_invalidated",
            )
        if self._blocked_outage_epoch == epoch:
            return self._store_blocked(
                frame,
                circulation,
                "grid_outage_attempt_invalidated_requires_new_outage_epoch",
            )
        if frame.external_preemption_reason:
            if self._attempt is not None:
                self._blocked_outage_epoch = epoch
                self._attempt = None
                self.assessment = self._result(
                    lifecycle=GridOutageSafetyLifecycle.FAILED,
                    at=frame.observed_at,
                    frame=frame,
                    reason=frame.external_preemption_reason,
                    circulation=circulation,
                )
                return self.assessment
            return self._store_blocked(
                frame,
                circulation,
                frame.external_preemption_reason,
            )
        if self._attempt is not None:
            verification = self._verify(frame, self._attempt)
            if verification == "verified":
                self._last_verified = self._attempt.candidate.kind
                self._attempt = None
                self.assessment = self._result(
                    lifecycle=GridOutageSafetyLifecycle.PROGRESS,
                    at=frame.observed_at,
                    frame=frame,
                    reason="grid_outage_reduction_verified",
                    circulation=circulation,
                )
                return self.assessment
            if verification in {"failed", "timed_out"}:
                self._attempt = None
                self.assessment = self._result(
                    lifecycle=GridOutageSafetyLifecycle.FAILED,
                    at=frame.observed_at,
                    frame=frame,
                    reason=f"grid_outage_verification_{verification}",
                    circulation=circulation,
                )
                return self.assessment
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.AWAITING_VERIFICATION,
                at=frame.observed_at,
                frame=frame,
                reason="grid_outage_awaiting_later_authoritative_verification",
                circulation=circulation,
            )
            return self.assessment

        if not self.gate_requested:
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.GATE_DISABLED,
                at=frame.observed_at,
                frame=frame,
                reason="grid_outage_physical_gate_disabled",
                circulation=circulation,
            )
            return self.assessment
        if self._enabled_after is None or frame.observed_at <= self._enabled_after:
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.BLOCKED,
                at=frame.observed_at,
                frame=frame,
                reason="grid_outage_fresh_frame_required_after_enable",
                circulation=circulation,
            )
            return self.assessment
        if not frame.physical_authority_ready:
            return self._store_blocked(
                frame, circulation, "grid_outage_physical_authority_unavailable"
            )
        if not frame.transport_ready:
            return self._store_blocked(frame, circulation, "grid_outage_transport_unavailable")
        if self._last_delivery_frame == frame.frame_identity:
            return self._store_blocked(frame, circulation, "grid_outage_frame_already_dispatched")

        candidate, reason = _select_candidate(frame, circulation, epoch)
        lifecycle = (
            GridOutageSafetyLifecycle.CANDIDATE_READY
            if candidate is not None
            else GridOutageSafetyLifecycle.BLOCKED
        )
        self.assessment = self._result(
            lifecycle=lifecycle,
            at=frame.observed_at,
            frame=frame,
            reason=reason,
            candidate=candidate,
            circulation=circulation,
        )
        return self.assessment

    def record_pre_dispatch_rejection(
        self,
        candidate: GridOutageReductionCandidate,
        *,
        rejected_at: datetime,
        reason: str,
    ) -> GridOutageSafetyAssessment:
        """Record proven zero-transport rejection without poisoning the outage."""

        _require_aware(rejected_at)
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        current = self.assessment
        if current is None or current.candidate != candidate:
            assert current is not None
            return current
        self._attempt = None
        self._last_delivery_frame = candidate.frame_identity
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.BLOCKED,
            at=rejected_at,
            frame=None,
            reason=f"grid_outage_delivery_rejected_before_transport:{reason[:160]}",
        )
        return self.assessment

    def record_accepted_delivery(
        self,
        candidate: GridOutageReductionCandidate,
        *,
        accepted_at: datetime,
    ) -> GridOutageSafetyAssessment:
        _require_aware(accepted_at)
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        current = self.assessment
        if (
            current is None
            or current.lifecycle is not GridOutageSafetyLifecycle.CANDIDATE_READY
            or current.candidate != candidate
            or candidate.outage_epoch_id != self._outage_epoch_id
        ):
            raise ValueError("outage candidate is no longer current")
        self._attempt = GridOutageDeliveryAttempt(
            candidate=candidate,
            accepted_at=accepted_at,
            verification_deadline=accepted_at + _VERIFICATION_TIMEOUT,
        )
        self._last_delivery_frame = candidate.frame_identity
        if not self.gate_requested:
            self._blocked_outage_epoch = candidate.outage_epoch_id
            self._attempt = None
            self.assessment = self._result(
                lifecycle=GridOutageSafetyLifecycle.FAILED,
                at=accepted_at,
                frame=None,
                reason="grid_outage_gate_disabled_after_dispatch",
                command_delivery_performed=True,
            )
            return self.assessment
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.AWAITING_VERIFICATION,
            at=accepted_at,
            frame=None,
            reason="grid_outage_delivery_accepted_verification_required",
            candidate=None,
            circulation=current.circulation,
            command_delivery_performed=True,
        )
        return self.assessment

    def record_delivery_failure(self, *, failed_at: datetime, reason: str) -> None:
        _require_aware(failed_at)
        if self._unloaded:
            return
        self._blocked_outage_epoch = self._outage_epoch_id
        self._attempt = None
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.FAILED,
            at=failed_at,
            frame=None,
            reason=f"grid_outage_delivery_failed:{reason[:160]}",
        )

    def _verify(self, frame: GridOutageSafetyFrame, attempt: GridOutageDeliveryAttempt) -> str:
        if frame.frame_identity == attempt.candidate.frame_identity:
            return "pending"
        by_id = {item.observation_id: item for item in frame.observations}
        expected_observation = by_id.get(attempt.candidate.expected_concept)
        expected = _state(expected_observation, frame.observed_at)
        if (
            not expected.usable
            or expected.observed_at is None
            or expected.observed_at <= attempt.accepted_at
        ):
            return "timed_out" if frame.observed_at >= attempt.verification_deadline else "pending"
        if (
            _native_object_id(expected_observation)
            != attempt.candidate.expected_native_object_id
        ):
            return "failed"
        if expected.value != attempt.candidate.requested_value:
            return "failed"
        if attempt.candidate.kind is GridOutageReductionKind.POOL_PUMP_REDUCTION:
            if _pump_verification_blocker(by_id, frame.observed_at) is not None:
                return "failed"
            actual = _state(by_id.get("pump.rpm"), frame.observed_at)
            rpm = _number(actual)
            if (
                not actual.usable
                or actual.observed_at is None
                or actual.observed_at <= attempt.accepted_at
            ):
                return (
                    "timed_out" if frame.observed_at >= attempt.verification_deadline else "pending"
                )
            if rpm is None or abs(rpm - _OUTAGE_RPM) > _RPM_TOLERANCE:
                return "failed"
        return "verified"

    def _store_blocked(
        self,
        frame: GridOutageSafetyFrame,
        circulation: OutageCirculationRequirementAssessment,
        reason: str,
    ) -> GridOutageSafetyAssessment:
        self.assessment = self._result(
            lifecycle=GridOutageSafetyLifecycle.BLOCKED,
            at=frame.observed_at,
            frame=frame,
            reason=reason,
            circulation=circulation,
        )
        return self.assessment

    def _result(
        self,
        *,
        lifecycle: GridOutageSafetyLifecycle,
        at: datetime,
        frame: GridOutageSafetyFrame | None,
        reason: str,
        candidate: GridOutageReductionCandidate | None = None,
        circulation: OutageCirculationRequirementAssessment | None = None,
        command_delivery_performed: bool = False,
    ) -> GridOutageSafetyAssessment:
        return GridOutageSafetyAssessment(
            lifecycle=lifecycle,
            evaluated_at=at,
            outage_epoch_id=self._outage_epoch_id,
            frame_identity=None if frame is None else frame.frame_identity,
            gate_requested=self.gate_requested,
            gate_effective=self.gate_requested and not self._unloaded,
            gate_generation=self.gate_generation,
            reason_code=reason,
            candidate=candidate,
            circulation=circulation,
            attempt=self._attempt,
            last_verified_reduction=self._last_verified,
            command_delivery_performed=(
                command_delivery_performed or self._attempt is not None
            ),
            command_delivery_enabled=(
                lifecycle is GridOutageSafetyLifecycle.CANDIDATE_READY
            ),
        )


def _select_candidate(
    frame: GridOutageSafetyFrame,
    circulation: OutageCirculationRequirementAssessment,
    epoch: str,
) -> tuple[GridOutageReductionCandidate | None, str]:
    by_id = {item.observation_id: item for item in frame.observations}

    def state(name: str) -> _ObservationState:
        return _state(by_id.get(name), frame.observed_at)

    pool = state("pool.active")
    spa = state("spa.active")
    pool_active = _boolean(pool)
    spa_active = _boolean(spa)
    pool_source_state = state("pool.raw_heater_id")
    spa_source_state = state("spa.raw_heater_id")
    pool_source = _source(pool_source_state)
    spa_source = _source(spa_source_state)

    if (
        spa.usable
        and spa_active is True
        and spa_source_state.usable
        and spa_source in {"H0001", "H0002"}
    ):
        return _candidate(
            GridOutageReductionKind.SPA_SOURCE_OFF, frame, epoch
        ), "grid_outage_spa_source_reduction_ready"
    if (
        pool.usable
        and pool_active is True
        and pool_source_state.usable
        and pool_source in {"H0001", "H0002"}
    ):
        return _candidate(
            GridOutageReductionKind.POOL_SOURCE_OFF, frame, epoch
        ), "grid_outage_pool_source_reduction_ready"

    light = state("pool_light.active")
    if light.usable and _boolean(light) is True:
        return _candidate(
            GridOutageReductionKind.POOL_LIGHT_OFF, frame, epoch
        ), "grid_outage_pool_light_reduction_ready"

    if not pool.usable or not spa.usable or pool_active is None or spa_active is None:
        return None, "grid_outage_body_topology_unusable"
    if pool_active and spa_active:
        return None, "grid_outage_body_topology_contradictory"
    if pool_active and (not pool_source_state.usable or pool_source not in _KNOWN_SOURCES):
        return None, "grid_outage_pool_source_unresolved"
    if spa_active and (not spa_source_state.usable or spa_source not in _KNOWN_SOURCES):
        return None, "grid_outage_spa_source_unresolved"

    freeze = state("freeze.active")
    if not freeze.usable or _boolean(freeze) is None:
        return None, "grid_outage_freeze_evidence_unusable"
    if _boolean(freeze) is True:
        return None, "grid_outage_freeze_blocks_hydraulic_reduction"

    for kind, concept in (
        (GridOutageReductionKind.JETS_OFF, "jets.active"),
        (GridOutageReductionKind.SLIDE_OFF, "slide.active"),
        (GridOutageReductionKind.WATERFALL_OFF, "waterfall.active"),
    ):
        circuit = state(concept)
        if not circuit.usable or _boolean(circuit) is None:
            return None, f"grid_outage_circuit_evidence_unusable:{concept}"
        if _boolean(circuit) is True:
            return _candidate(kind, frame, epoch), f"grid_outage_{kind.value}_ready"

    if spa_active:
        if spa_source != "00000":
            return None, "grid_outage_spa_source_shutdown_pending"
        return _candidate(
            GridOutageReductionKind.SPA_BODY_OFF, frame, epoch
        ), "grid_outage_spa_body_reduction_ready"

    if circulation.disposition is OutageCirculationDisposition.REQUIRED:
        if circulation.circulation_established is not True:
            return None, "required_circulation_not_established"
        if pool_active is not True or spa_active is not False:
            return None, "grid_outage_pool_routing_not_established"
        if pool_source != "00000":
            return None, "grid_outage_source_shutdown_not_complete"
        if frame.pool_pump_circuit_id is None:
            return None, "grid_outage_pool_pump_circuit_unresolved"
        configured = state(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT)
        actual = state("pump.rpm")
        configured_rpm = _number(configured)
        actual_rpm = _number(actual)
        if not configured.usable or configured_rpm is None:
            return None, "grid_outage_configured_pump_evidence_unusable"
        if (
            _native_object_id(
                by_id.get(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT)
            )
            != frame.pool_pump_circuit_id
        ):
            return None, "grid_outage_pool_pump_identity_stale"
        if not actual.usable or actual_rpm is None:
            return None, "grid_outage_actual_pump_evidence_unusable"
        if actual_rpm <= 0:
            return None, "required_circulation_not_established"
        if configured_rpm <= _OUTAGE_RPM:
            return None, "grid_outage_pump_already_at_or_below_ceiling"
        if actual_rpm < _OUTAGE_RPM - _RPM_TOLERANCE:
            return None, "grid_outage_configured_actual_pump_evidence_contradictory"
        return _candidate(
            GridOutageReductionKind.POOL_PUMP_REDUCTION, frame, epoch
        ), "grid_outage_pump_reduction_ready"

    if circulation.disposition is OutageCirculationDisposition.NOT_REQUIRED:
        return None, "grid_outage_external_circulation_left_untouched"
    return None, circulation.reason_code


def _candidate(
    kind: GridOutageReductionKind,
    frame: GridOutageSafetyFrame,
    epoch: str,
) -> GridOutageReductionCandidate:
    shape = (
        (
            "pump_circuit_speed",
            frame.pool_pump_circuit_id,
            _OUTAGE_RPM,
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
            frame.pool_pump_circuit_id,
            9,
        )
        if kind is GridOutageReductionKind.POOL_PUMP_REDUCTION
        and frame.pool_pump_circuit_id is not None
        else _CANDIDATE_SHAPES[kind]
    )
    fingerprint = _evidence_fingerprint(frame.observations)
    identity = sha256(
        f"{epoch}|{frame.frame_identity}|{kind.value}|{fingerprint}".encode()
    ).hexdigest()[:24]
    return GridOutageReductionCandidate(
        identity,
        epoch,
        frame.frame_identity,
        kind,
        *shape,
        fingerprint,
        frame.observed_at,
    )


def _pump_verification_blocker(
    observations: Mapping[str, PoolObservation],
    evaluated_at: datetime,
) -> str | None:
    required = {
        name: _state(observations.get(name), evaluated_at)
        for name in (
            "pool.active",
            "spa.active",
            "pool.raw_heater_id",
            "jets.active",
            "slide.active",
            "waterfall.active",
            "freeze.active",
        )
    }
    if any(not item.usable for item in required.values()):
        return "grid_outage_pump_verification_evidence_unusable"
    if _boolean(required["pool.active"]) is not True:
        return "grid_outage_pump_verification_pool_inactive"
    if _boolean(required["spa.active"]) is not False:
        return "grid_outage_pump_verification_spa_active"
    if _source(required["pool.raw_heater_id"]) != "00000":
        return "grid_outage_pump_verification_source_not_off"
    if _boolean(required["freeze.active"]) is not False:
        return "grid_outage_pump_verification_freeze_blocked"
    for concept in ("jets.active", "slide.active", "waterfall.active"):
        if _boolean(required[concept]) is not False:
            return f"grid_outage_pump_verification_hydraulic_active:{concept}"
    return None


def grid_outage_external_preemption_reason(
    batch: ExternalChangeBatch,
    *,
    authority_not_before: datetime,
    evaluated_at: datetime,
) -> str | None:
    """Return an uncorrelated takeover occurring after the authority basis."""

    _require_aware(authority_not_before)
    _require_aware(evaluated_at)
    relevant = sorted(
        (
            event.observed_at,
            event.concept,
            event.event_id,
        )
        for event in batch.events
        if event.concept in GRID_OUTAGE_SAFETY_TAKEOVER_CONCEPTS
        and authority_not_before < event.observed_at <= evaluated_at
    )
    if not relevant:
        return None
    return f"grid_outage_external_takeover:{relevant[0][1]}"


def _epoch_id(outage: GridOutageAssessment) -> str:
    if outage.outage_epoch_started_at is None or outage.confirmed_at is None:
        raise ValueError("confirmed outage requires canonical epoch timestamps")
    return sha256(
        f"{outage.outage_epoch_started_at.isoformat()}|{outage.confirmed_at.isoformat()}|{outage.source_id}".encode()
    ).hexdigest()[:24]


def _evidence_fingerprint(observations: Iterable[PoolObservation]) -> str:
    relevant = {
        "pool.active",
        "spa.active",
        "pump.rpm",
        POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        "pool.raw_heater_id",
        "spa.raw_heater_id",
        "pool_light.active",
        "jets.active",
        "slide.active",
        "waterfall.active",
        "freeze.active",
    }
    payload = [
        (
            item.observation_id,
            item.value,
            None if item.observed_at is None else item.observed_at.isoformat(),
            item.source_kind.value,
            item.source_id,
            item.quality.value,
            item.confidence,
        )
        for item in sorted(observations, key=lambda value: value.observation_id)
        if item.observation_id in relevant
    ]
    return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _state(observation: PoolObservation | None, evaluated_at: datetime) -> _ObservationState:
    if observation is None:
        return _ObservationState(None, False, None)
    fresh = observation.freshness(clock=FixedClock(evaluated_at), policy=_FRESHNESS)
    usable = (
        observation.source_kind is ObservationSourceKind.LIVE
        and observation.quality in _QUALITIES
        and observation.confidence >= _MINIMUM_CONFIDENCE
        and fresh is ObservationFreshness.FRESH
    )
    return _ObservationState(observation.value, usable, observation.observed_at)


def _boolean(state: _ObservationState) -> bool | None:
    return state.value if type(state.value) is bool else None


def _number(state: _ObservationState) -> float | None:
    if isinstance(state.value, bool) or not isinstance(state.value, (int, float)):
        return None
    return float(state.value)


def _source(state: _ObservationState) -> str | None:
    return state.value if isinstance(state.value, str) and state.value in _KNOWN_SOURCES else None


def _native_object_id(observation: PoolObservation | None) -> str | None:
    """Extract the exact native IntelliCenter object from canonical provenance."""

    if observation is None:
        return None
    source_id = observation.source_id
    prefix = "intellicenter_native:"
    if source_id is None or not source_id.startswith(prefix):
        return None
    _, separator, native_id = source_id.rpartition(":")
    if not separator or not native_id.strip():
        return None
    return native_id.strip()


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "GridOutageDeliveryAttempt",
    "GridOutagePhysicalSafetyEngine",
    "GridOutageReductionCandidate",
    "GridOutageReductionKind",
    "GridOutageSafetyAssessment",
    "GridOutageSafetyFrame",
    "GridOutageSafetyLifecycle",
    "OutageCirculationDisposition",
    "OutageCirculationRequirementAssessment",
    "assess_outage_circulation_requirement",
    "grid_outage_external_preemption_reason",
]
