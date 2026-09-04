"""Command-free supervisory lifecycle for production thermal evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from typing import Iterable

from .clock import FixedClock
from .external_change import ExternalChangeBatch
from .grid_outage_confirmation import (
    GridOutageAssessment,
    GridOutageConfirmationTracker,
    GridOutageDisposition,
)
from .integration import PhysicalHeatMode, ThermalBody
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from .thermal_live_execution import ThermalLiveExecutionContext
from .thermal_runtime_assessment import (
    ThermalBodyRuntimeAssessment,
    ThermalRuntimeAssessment,
)
from .thermal_runtime_ownership import (
    SHARED_HYDRAULIC_SAFETY_BY_CONCEPT,
    SharedHydraulicCircuitEvidence,
    ThermalRuntimeOwnershipDecision,
    ThermalRuntimeOwnershipEvidence,
    ThermalRuntimeOwnershipManager,
    ThermalRuntimeOwnershipStatus,
    shared_hydraulic_safety_class,
)

_LIVE_FRESHNESS = FreshnessPolicy(max_age=timedelta(seconds=30))
_LIVE_MINIMUM_CONFIDENCE = 0.5
_LIVE_ACCEPTED_QUALITIES = frozenset(
    {ObservationQuality.GOOD, ObservationQuality.DEGRADED}
)
_EMPTY_EXTERNAL_CHANGES = ExternalChangeBatch(())
_ORCHESTRATION_OBSERVATION_IDS = frozenset(
    {
        "grid.outage_active",
        "pool.active",
        "spa.active",
        "pump.rpm",
        "pump_circuit.p0102.configured_speed_rpm",
        "pool.raw_heater_id",
        "spa.raw_heater_id",
        *SHARED_HYDRAULIC_SAFETY_BY_CONCEPT,
    }
)
_REASON_LIMIT = 256


class ThermalOrchestrationLifecycle(StrEnum):
    """Current command-free supervisory lifecycle disposition."""

    INITIALIZING = "initializing"
    BLOCKED = "blocked"
    CANDIDATE_READY = "candidate_ready"
    OWNED = "owned"
    PREEMPTED = "preempted"
    SUPERSEDED = "superseded"
    UNLOADED = "unloaded"


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOrchestrationAssessment:
    """Bounded immutable diagnostics for one authoritative orchestration pass."""

    lifecycle: ThermalOrchestrationLifecycle
    evaluated_at: datetime
    snapshot_identity: str
    pool_evaluation_id: str | None
    pool_plan_id: str | None
    hot_tub_evaluation_id: str | None
    hot_tub_plan_id: str | None
    pool_requested_mode: str | None
    hot_tub_requested_mode: str | None
    outage: GridOutageAssessment | None
    ownership_status: ThermalRuntimeOwnershipStatus
    ownership_decision: ThermalRuntimeOwnershipDecision | None
    candidate_id: str | None
    candidate_body: ThermalBody | None
    superseded_candidate_id: str | None
    awaiting_verification: bool
    blocking_reason: str
    last_transition_at: datetime
    automatic_execution_driver_enabled: bool = field(default=False, init=False)
    command_delivery_performed: bool = field(default=False, init=False)


@dataclass(slots=True)
class ThermalRuntimeOrchestrator:
    """Coordinate current lifecycle truth without owning a delivery port."""

    ownership: ThermalRuntimeOwnershipManager = field(
        default_factory=ThermalRuntimeOwnershipManager
    )
    outage_confirmation: GridOutageConfirmationTracker = field(
        default_factory=GridOutageConfirmationTracker
    )
    assessment: ThermalRuntimeOrchestrationAssessment | None = None
    _last_snapshot_at: datetime | None = field(default=None, init=False, repr=False)
    _last_frame_fingerprint: str | None = field(default=None, init=False, repr=False)
    _conflicting_snapshot_at: datetime | None = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)

    def refresh(
        self,
        *,
        generated_at: datetime,
        observations: Iterable[PoolObservation],
        thermal: ThermalRuntimeAssessment | None,
        external_changes: ExternalChangeBatch = _EMPTY_EXTERNAL_CHANGES,
    ) -> ThermalRuntimeOrchestrationAssessment:
        """Process one already-created authoritative frame exactly once."""

        _require_aware(generated_at)
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        observation_items = tuple(observations)
        frame_fingerprint = _frame_fingerprint(
            generated_at,
            observation_items,
            thermal,
            external_changes,
        )
        if self._last_snapshot_at is not None:
            if generated_at < self._last_snapshot_at:
                assert self.assessment is not None
                return self.assessment
            if generated_at == self._last_snapshot_at:
                assert self.assessment is not None
                if self._conflicting_snapshot_at == generated_at:
                    return self.assessment
                if frame_fingerprint == self._last_frame_fingerprint:
                    return self.assessment
                conflict_identity = _conflict_snapshot_identity(
                    self._last_frame_fingerprint,
                    frame_fingerprint,
                )
                blocked = self.fail_closed(
                    failed_at=generated_at,
                    reason_code="thermal_orchestration_snapshot_conflict",
                    snapshot_identity=conflict_identity,
                )
                self._conflicting_snapshot_at = generated_at
                return blocked

        by_id = {item.observation_id: item for item in observation_items}
        outage = self.outage_confirmation.evaluate(
            by_id.get("grid.outage_active"),
            evaluated_at=generated_at,
        )
        previous_candidate = (
            None if self.assessment is None else self.assessment.candidate_id
        )
        ownership_decision = self._evaluate_ownership(
            generated_at=generated_at,
            observations=by_id,
            thermal=thermal,
            external_changes=external_changes,
            outage=outage,
        )
        lifecycle, reason, candidate_body = self._lifecycle(
            generated_at=generated_at,
            observations=by_id,
            thermal=thermal,
            outage=outage,
            ownership_decision=ownership_decision,
        )
        body_assessment = _body_assessment(thermal, candidate_body)
        candidate_id = (
            None
            if body_assessment is None
            or lifecycle is not ThermalOrchestrationLifecycle.CANDIDATE_READY
            else _candidate_id(body_assessment)
        )
        superseded = (
            previous_candidate
            if previous_candidate is not None and previous_candidate != candidate_id
            else None
        )
        prior = self.assessment
        last_transition_at = (
            generated_at
            if prior is None
            or (
                prior.lifecycle,
                prior.blocking_reason,
                prior.candidate_id,
                prior.ownership_status,
                None if prior.outage is None else prior.outage.disposition,
            )
            != (
                lifecycle,
                reason,
                candidate_id,
                self.ownership.state.status,
                outage.disposition,
            )
            else prior.last_transition_at
        )
        self.assessment = ThermalRuntimeOrchestrationAssessment(
            lifecycle=lifecycle,
            evaluated_at=generated_at,
            snapshot_identity=_snapshot_identity(generated_at, frame_fingerprint),
            pool_evaluation_id=None if thermal is None else thermal.pool.evaluation_id,
            pool_plan_id=None if thermal is None else thermal.pool.plan.plan_id,
            hot_tub_evaluation_id=(
                None if thermal is None else thermal.hot_tub.evaluation_id
            ),
            hot_tub_plan_id=(
                None if thermal is None else thermal.hot_tub.plan.plan_id
            ),
            pool_requested_mode=(
                None if thermal is None else thermal.pool.requested_mode.value
            ),
            hot_tub_requested_mode=(
                None if thermal is None else thermal.hot_tub.requested_mode.value
            ),
            outage=outage,
            ownership_status=self.ownership.state.status,
            ownership_decision=ownership_decision,
            candidate_id=candidate_id,
            candidate_body=candidate_body,
            superseded_candidate_id=superseded,
            awaiting_verification=False,
            blocking_reason=reason,
            last_transition_at=last_transition_at,
        )
        self._last_snapshot_at = generated_at
        self._last_frame_fingerprint = frame_fingerprint
        self._conflicting_snapshot_at = None
        return self.assessment

    def fail_closed(
        self,
        *,
        failed_at: datetime,
        reason_code: str,
        snapshot_identity: str | None = None,
    ) -> ThermalRuntimeOrchestrationAssessment:
        """Invalidate current readiness after a bounded integration failure."""

        _require_aware(failed_at)
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        if self._last_snapshot_at is not None and failed_at < self._last_snapshot_at:
            assert self.assessment is not None
            return self.assessment
        reason = _bounded_reason(reason_code)
        prior = self.assessment
        ownership_decision = None
        lease = self.ownership.state.lease
        if lease is not None and lease.status is ThermalRuntimeOwnershipStatus.OWNED:
            ownership_decision = self.ownership.relinquish(
                lease_id=lease.lease_id,
                relinquished_at=failed_at,
                reason_code="orchestration_processing_failed",
            )
        self.assessment = ThermalRuntimeOrchestrationAssessment(
            lifecycle=ThermalOrchestrationLifecycle.BLOCKED,
            evaluated_at=failed_at,
            snapshot_identity=(
                snapshot_identity
                if snapshot_identity is not None
                else _failure_snapshot_identity(failed_at, reason)
            ),
            pool_evaluation_id=None if prior is None else prior.pool_evaluation_id,
            pool_plan_id=None if prior is None else prior.pool_plan_id,
            hot_tub_evaluation_id=(
                None if prior is None else prior.hot_tub_evaluation_id
            ),
            hot_tub_plan_id=None if prior is None else prior.hot_tub_plan_id,
            pool_requested_mode=None if prior is None else prior.pool_requested_mode,
            hot_tub_requested_mode=(
                None if prior is None else prior.hot_tub_requested_mode
            ),
            outage=None if prior is None else prior.outage,
            ownership_status=self.ownership.state.status,
            ownership_decision=ownership_decision,
            candidate_id=None,
            candidate_body=None,
            superseded_candidate_id=None if prior is None else prior.candidate_id,
            awaiting_verification=False,
            blocking_reason=reason,
            last_transition_at=failed_at,
        )
        self._last_snapshot_at = failed_at
        self._last_frame_fingerprint = None
        self._conflicting_snapshot_at = failed_at
        return self.assessment

    def unload(self, *, unloaded_at: datetime) -> ThermalRuntimeOrchestrationAssessment:
        """Discard in-memory lifecycle state without cleanup or restoration."""

        _require_aware(unloaded_at)
        if self._unloaded:
            assert self.assessment is not None
            return self.assessment
        self.ownership = ThermalRuntimeOwnershipManager()
        self.outage_confirmation = GridOutageConfirmationTracker()
        self._unloaded = True
        self._last_snapshot_at = unloaded_at
        self._last_frame_fingerprint = None
        self._conflicting_snapshot_at = None
        self.assessment = ThermalRuntimeOrchestrationAssessment(
            lifecycle=ThermalOrchestrationLifecycle.UNLOADED,
            evaluated_at=unloaded_at,
            snapshot_identity=_snapshot_identity(unloaded_at),
            pool_evaluation_id=None,
            pool_plan_id=None,
            hot_tub_evaluation_id=None,
            hot_tub_plan_id=None,
            pool_requested_mode=None,
            hot_tub_requested_mode=None,
            outage=None,
            ownership_status=ThermalRuntimeOwnershipStatus.UNOWNED,
            ownership_decision=None,
            candidate_id=None,
            candidate_body=None,
            superseded_candidate_id=None,
            awaiting_verification=False,
            blocking_reason="thermal_orchestration_unloaded",
            last_transition_at=unloaded_at,
        )
        return self.assessment

    def _evaluate_ownership(
        self,
        *,
        generated_at: datetime,
        observations: dict[str, PoolObservation],
        thermal: ThermalRuntimeAssessment | None,
        external_changes: ExternalChangeBatch,
        outage: GridOutageAssessment,
    ) -> ThermalRuntimeOwnershipDecision | None:
        lease = self.ownership.state.lease
        if lease is None or lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return None
        if outage.disposition is not GridOutageDisposition.ON_GRID:
            return self.ownership.relinquish(
                lease_id=lease.lease_id,
                relinquished_at=generated_at,
                reason_code="runtime_ownership_relinquished:grid_not_authoritatively_on",
            )
        if thermal is None:
            return self.ownership.relinquish(
                lease_id=lease.lease_id,
                relinquished_at=generated_at,
                reason_code="runtime_ownership_relinquished:thermal_assessment_unavailable",
            )
        body = thermal.pool if lease.body is ThermalBody.POOL else thermal.hot_tub
        return self.ownership.evaluate(
            _ownership_evidence(
                generated_at=generated_at,
                observations=observations,
                body=body,
                external_changes=external_changes,
            )
        )

    def _lifecycle(
        self,
        *,
        generated_at: datetime,
        observations: dict[str, PoolObservation],
        thermal: ThermalRuntimeAssessment | None,
        outage: GridOutageAssessment,
        ownership_decision: ThermalRuntimeOwnershipDecision | None,
    ) -> tuple[ThermalOrchestrationLifecycle, str, ThermalBody | None]:
        if ownership_decision is not None:
            status = ownership_decision.current_state.status
            if status is ThermalRuntimeOwnershipStatus.PREEMPTED:
                return (
                    ThermalOrchestrationLifecycle.PREEMPTED,
                    ownership_decision.reason_code,
                    None,
                )
            if status in {
                ThermalRuntimeOwnershipStatus.SUPERSEDED,
                ThermalRuntimeOwnershipStatus.RELINQUISHED,
            }:
                return (
                    ThermalOrchestrationLifecycle.SUPERSEDED,
                    ownership_decision.reason_code,
                    None,
                )
            if status is ThermalRuntimeOwnershipStatus.OWNED:
                lease = self.ownership.state.lease
                assert lease is not None
                return (
                    ThermalOrchestrationLifecycle.OWNED,
                    ownership_decision.reason_code,
                    lease.body,
                )
        if thermal is None:
            return (
                ThermalOrchestrationLifecycle.INITIALIZING,
                "thermal_orchestration_assessment_unavailable",
                None,
            )
        if thermal.generated_at != generated_at:
            return (
                ThermalOrchestrationLifecycle.BLOCKED,
                "thermal_orchestration_assessment_snapshot_mismatch",
                None,
            )
        if outage.disposition is not GridOutageDisposition.ON_GRID:
            return (
                ThermalOrchestrationLifecycle.BLOCKED,
                f"thermal_orchestration_grid:{outage.disposition.value}",
                None,
            )
        hydraulic_reason = _shared_hydraulic_blocker(
            observations,
            evaluated_at=thermal.generated_at,
        )
        if hydraulic_reason is not None:
            return ThermalOrchestrationLifecycle.BLOCKED, hydraulic_reason, None
        candidates = tuple(
            item.body
            for item in (thermal.pool, thermal.hot_tub)
            if item.actual_authorization.authorized
        )
        if len(candidates) != 1:
            reason = (
                "thermal_orchestration_no_authorized_candidate"
                if not candidates
                else "thermal_orchestration_multiple_authorized_candidates"
            )
            return ThermalOrchestrationLifecycle.BLOCKED, reason, None
        topology_reason = _body_topology_blocker(
            observations,
            evaluated_at=thermal.generated_at,
            target=candidates[0],
        )
        if topology_reason is not None:
            return ThermalOrchestrationLifecycle.BLOCKED, topology_reason, None
        return (
            ThermalOrchestrationLifecycle.CANDIDATE_READY,
            "thermal_orchestration_candidate_ready_command_free",
            candidates[0],
        )


def _ownership_evidence(
    *,
    generated_at: datetime,
    observations: dict[str, PoolObservation],
    body: ThermalBodyRuntimeAssessment,
    external_changes: ExternalChangeBatch,
) -> ThermalRuntimeOwnershipEvidence:
    pool = _observation_state(observations.get("pool.active"), generated_at)
    spa = _observation_state(observations.get("spa.active"), generated_at)
    pump = _observation_state(observations.get("pump.rpm"), generated_at)
    configured = _observation_state(
        observations.get("pump_circuit.p0102.configured_speed_rpm"),
        generated_at,
    )
    source_concept = (
        "pool.raw_heater_id"
        if body.body is ThermalBody.POOL
        else "spa.raw_heater_id"
    )
    source = _observation_state(observations.get(source_concept), generated_at)
    circuits, complete = _shared_hydraulic_evidence(observations, generated_at)
    return ThermalRuntimeOwnershipEvidence(
        evaluated_at=generated_at,
        current_context=ThermalLiveExecutionContext(
            evaluation_id=body.evaluation_id,
            plan_id=body.plan.plan_id,
        ),
        requested_mode=body.requested_mode.value,
        pool_active=_boolean(pool.value),
        spa_active=_boolean(spa.value),
        pool_activity_fresh=pool.fresh,
        spa_activity_fresh=spa.fresh,
        pool_activity_usable=pool.usable,
        spa_activity_usable=spa.usable,
        pump_rpm=_integer(pump.value),
        pump_observation_fresh=pump.fresh,
        pump_observation_usable=pump.usable,
        configured_pump_speed_rpm=_integer(configured.value),
        configured_pump_speed_observation_fresh=configured.fresh,
        configured_pump_speed_observation_usable=configured.usable,
        effective_heat_source=_heat_source(source.value),
        heat_source_observation_fresh=source.fresh,
        heat_source_observation_usable=source.usable,
        external_changes=external_changes,
        shared_hydraulic_circuits=circuits,
        shared_hydraulic_inventory_complete=complete,
    )


@dataclass(frozen=True, slots=True)
class _ObservationState:
    value: object
    fresh: bool
    usable: bool


def _observation_state(
    observation: PoolObservation | None,
    evaluated_at: datetime,
) -> _ObservationState:
    if observation is None:
        return _ObservationState(None, False, False)
    freshness = observation.freshness(
        clock=FixedClock(evaluated_at),
        policy=_LIVE_FRESHNESS,
    )
    return _ObservationState(
        observation.value,
        freshness is ObservationFreshness.FRESH,
        observation.source_kind is ObservationSourceKind.LIVE
        and observation.quality in _LIVE_ACCEPTED_QUALITIES
        and observation.confidence >= _LIVE_MINIMUM_CONFIDENCE
        and freshness is ObservationFreshness.FRESH,
    )


def _shared_hydraulic_evidence(
    observations: dict[str, PoolObservation],
    evaluated_at: datetime,
) -> tuple[tuple[SharedHydraulicCircuitEvidence, ...], bool]:
    evidence: list[SharedHydraulicCircuitEvidence] = []
    complete = True
    for concept in SHARED_HYDRAULIC_SAFETY_BY_CONCEPT:
        if concept == "pool_light.active":
            continue
        state = _observation_state(observations.get(concept), evaluated_at)
        active = _boolean(state.value)
        if active is None or not state.usable:
            complete = False
        evidence.append(
            SharedHydraulicCircuitEvidence(
                concept=concept,
                active=active,
                fresh=state.fresh,
                usable=state.usable,
                safety_class=shared_hydraulic_safety_class(concept),
            )
        )
    return tuple(evidence), complete


def _shared_hydraulic_blocker(
    observations: dict[str, PoolObservation],
    *,
    evaluated_at: datetime,
) -> str | None:
    circuits, complete = _shared_hydraulic_evidence(observations, evaluated_at)
    if not complete:
        return "thermal_orchestration_shared_hydraulic_inventory_incomplete"
    for item in circuits:
        if item.active:
            return f"thermal_orchestration_shared_hydraulic_conflict:{item.concept}"
    return None


def _body_topology_blocker(
    observations: dict[str, PoolObservation],
    *,
    evaluated_at: datetime,
    target: ThermalBody,
) -> str | None:
    pool = _observation_state(observations.get("pool.active"), evaluated_at)
    spa = _observation_state(observations.get("spa.active"), evaluated_at)
    pool_active = _boolean(pool.value)
    spa_active = _boolean(spa.value)
    if not pool.usable or pool_active is None:
        return "thermal_orchestration_pool_activity_unusable"
    if not spa.usable or spa_active is None:
        return "thermal_orchestration_spa_activity_unusable"
    if pool_active and spa_active:
        return "thermal_orchestration_body_topology_contradictory"
    if target is ThermalBody.POOL and spa_active:
        return "thermal_orchestration_spa_takeover"
    if target is ThermalBody.HOT_TUB and pool_active:
        return "thermal_orchestration_pool_takeover"
    return None


def _body_assessment(
    thermal: ThermalRuntimeAssessment | None,
    body: ThermalBody | None,
) -> ThermalBodyRuntimeAssessment | None:
    if thermal is None or body is None:
        return None
    return thermal.pool if body is ThermalBody.POOL else thermal.hot_tub


def _candidate_id(body: ThermalBodyRuntimeAssessment) -> str:
    payload = json.dumps(
        {
            "body": body.body.value,
            "evaluation_id": body.evaluation_id,
            "plan_id": body.plan.plan_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "thermal-candidate-" + sha256(payload.encode()).hexdigest()[:24]


def _snapshot_identity(generated_at: datetime, fingerprint: str | None = None) -> str:
    value = fingerprint or sha256(generated_at.isoformat().encode()).hexdigest()
    return "thermal-snapshot-" + value[:24]


def _frame_fingerprint(
    generated_at: datetime,
    observations: tuple[PoolObservation, ...],
    thermal: ThermalRuntimeAssessment | None,
    external_changes: ExternalChangeBatch,
) -> str:
    relevant = sorted(
        (
            item.observation_id,
            _canonical_value(item.value),
            None if item.observed_at is None else item.observed_at.isoformat(),
            item.source_kind.value,
            _text_digest(item.source_id),
            item.quality.value,
            item.confidence,
        )
        for item in observations
        if item.observation_id in _ORCHESTRATION_OBSERVATION_IDS
    )
    bodies = []
    if thermal is not None:
        for body in (thermal.pool, thermal.hot_tub):
            bodies.append(
                (
                    body.body.value,
                    _text_digest(body.evaluation_id),
                    _text_digest(body.plan.plan_id),
                    body.requested_mode.value,
                    body.actual_authorization.authorized,
                )
            )
    external = sorted(
        (
            _text_digest(event.event_id),
            event.concept,
            event.observed_at.isoformat(),
            _canonical_value(event.previous_value),
            _canonical_value(event.new_value),
            event.reconciliation_required,
            _text_digest(event.reason_code),
        )
        for event in external_changes.events
    )
    correlated = sorted(
        (
            _text_digest(item.expectation_id),
            _text_digest(item.request_id),
            _text_digest(item.operation),
            _text_digest(item.target),
        )
        for item in external_changes.correlated_consequences
    )
    payload = json.dumps(
        {
            "generated_at": generated_at.isoformat(),
            "observations": relevant,
            "thermal": bodies,
            "external": external,
            "correlated": correlated,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()


def _canonical_value(value: object) -> tuple[str, object]:
    if value is None or type(value) in {bool, int, float}:
        return type(value).__name__, value
    if isinstance(value, str):
        return "str", sha256(value.encode()).hexdigest()
    return "unsupported", f"{type(value).__module__}.{type(value).__qualname__}"


def _text_digest(value: str | None) -> str | None:
    return None if value is None else sha256(value.encode()).hexdigest()


def _conflict_snapshot_identity(
    previous: str | None,
    current: str,
) -> str:
    payload = "|".join(sorted((previous or "missing", current)))
    return "thermal-snapshot-conflict-" + sha256(payload.encode()).hexdigest()[:24]


def _failure_snapshot_identity(failed_at: datetime, reason: str) -> str:
    payload = f"{failed_at.isoformat()}|{reason}"
    return "thermal-snapshot-failed-" + sha256(payload.encode()).hexdigest()[:24]


def _bounded_reason(reason: str) -> str:
    compact = " ".join(reason.split())
    return (compact or "thermal_orchestration_processing_failed")[:_REASON_LIMIT]


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _heat_source(value: object) -> PhysicalHeatMode | None:
    return {
        "00000": PhysicalHeatMode.OFF,
        "H0001": PhysicalHeatMode.GAS,
        "H0002": PhysicalHeatMode.SOLAR,
    }.get(value if isinstance(value, str) else "")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("orchestration timestamp must be timezone-aware")


__all__ = [
    "ThermalOrchestrationLifecycle",
    "ThermalRuntimeOrchestrationAssessment",
    "ThermalRuntimeOrchestrator",
]
