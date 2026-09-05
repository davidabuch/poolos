"""Default-off event-driven automatic thermal execution supervision.

The driver consumes the existing runtime assessment, command-free orchestrator,
canonical currentness contract, scoped live engine, and runtime ownership
manager.  It owns no scheduler, transport, polling loop, persistence, retry, or
cleanup command.  One call represents one authoritative observation epoch and
may submit at most one new physical operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol

from .integration import SetBodyActive, ThermalBody
from .grid_outage_confirmation import GridOutageDisposition
from .observations import ObservationStore, PoolObservation
from .thermal_live_execution import (
    ThermalLiveDeliveryPort,
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
    ThermalLiveExecutionStatus,
    ThermalLiveStructuralPreflightResult,
)
from .thermal_runtime_assessment import (
    ThermalBodyRuntimeAssessment,
    ThermalRuntimeAssessment,
)
from .thermal_runtime_orchestration import (
    ThermalOrchestrationLifecycle,
    ThermalRuntimeOrchestrationAssessment,
    ThermalRuntimeOrchestrator,
)
from .thermal_runtime_ownership import ThermalRuntimeOwnershipStatus


class ThermalAutomaticDriverState(StrEnum):
    """Bounded lifecycle state for one config-entry automatic driver."""

    DISABLED = "disabled"
    BLOCKED = "blocked"
    READY = "ready"
    SESSION_ACTIVE = "session_active"
    AWAITING_REOBSERVATION = "awaiting_reobservation"
    AWAITING_VERIFICATION = "awaiting_verification"
    CONVERGED = "converged"
    PREEMPTED = "preempted"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    UNLOADED = "unloaded"


@dataclass(frozen=True, slots=True)
class ThermalAutomaticExecutionFrame:
    """One immutable authoritative runtime epoch supplied by the adapter."""

    epoch_identity: str
    observed_at: datetime
    observations: tuple[PoolObservation, ...]
    thermal: ThermalRuntimeAssessment | None
    orchestration: ThermalRuntimeOrchestrationAssessment
    live_policy: ThermalLiveExecutionPolicy
    physical_authority_ready: bool
    physical_authority_blocker: str | None = None

    def __post_init__(self) -> None:
        if not self.epoch_identity.strip():
            raise ValueError("automatic thermal epoch identity must not be empty")
        _require_aware(self.observed_at)
        if self.orchestration.snapshot_identity != self.epoch_identity:
            raise ValueError("orchestration identity must match automatic frame")
        if self.orchestration.evaluated_at != self.observed_at:
            raise ValueError("orchestration timestamp must match automatic frame")
        if self.physical_authority_ready == bool(self.physical_authority_blocker):
            raise ValueError("physical authority readiness must match blocker")
        object.__setattr__(self, "observations", tuple(self.observations))


class ThermalAutomaticDeliveryFactory(Protocol):
    """Create one final-gateway-bound delivery port for the current epoch."""

    def for_session(
        self,
        session: ThermalLiveExecutionSession,
        *,
        epoch_identity: str,
    ) -> ThermalLiveDeliveryPort: ...


@dataclass(frozen=True, slots=True)
class ThermalAutomaticDriverAssessment:
    """Bounded diagnostics for the latest automatic-driver transition."""

    state: ThermalAutomaticDriverState
    evaluated_at: datetime
    requested_enabled: bool
    effective_enabled: bool
    blocker: str | None
    candidate_body: ThermalBody | None
    candidate_evaluation_id: str | None
    candidate_plan_id: str | None
    candidate_execution_purpose_id: str | None
    static_preflight_eligible: bool | None
    static_preflight_blocker: str | None
    active_session_identity: str | None
    current_step_sequence: int | None
    current_step_operation_id: str | None
    awaiting_reobservation: bool
    awaiting_verification: bool
    runtime_ownership_status: ThermalRuntimeOwnershipStatus
    runtime_ownership_summary: Mapping[str, object]
    outage_state: str | None
    last_transition_at: datetime
    last_failure_reason: str | None
    accepted_delivery_count: int
    last_accepted_correlation_id: str | None
    command_delivery_performed: bool

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at)
        _require_aware(self.last_transition_at)
        if self.accepted_delivery_count < 0:
            raise ValueError("accepted delivery count must not be negative")
        object.__setattr__(
            self,
            "runtime_ownership_summary",
            MappingProxyType(dict(self.runtime_ownership_summary)),
        )


@dataclass(slots=True)
class ThermalAutomaticExecutionDriver:
    """Advance existing live execution only from authoritative epochs."""

    orchestrator: ThermalRuntimeOrchestrator
    engine: ThermalLiveExecutionEngine = field(default_factory=ThermalLiveExecutionEngine)
    requested_enabled: bool = False
    assessment: ThermalAutomaticDriverAssessment | None = None
    active_session: ThermalLiveExecutionSession | None = None
    _last_epoch_identity: str | None = field(default=None, init=False, repr=False)
    _last_epoch_at: datetime | None = field(default=None, init=False, repr=False)
    _enabled_after_epoch_identity: str | None = field(
        default=None, init=False, repr=False
    )
    _delivery_in_flight: bool = field(default=False, init=False, repr=False)
    _retire_after_inflight: bool = field(default=False, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)
    _accepted_delivery_count: int = field(default=0, init=False, repr=False)
    _last_accepted_correlation_id: str | None = field(
        default=None, init=False, repr=False
    )

    @property
    def last_epoch_identity(self) -> str | None:
        return self._last_epoch_identity

    def set_enabled(
        self,
        enabled: bool,
        *,
        changed_at: datetime,
        current_epoch_identity: str | None,
    ) -> ThermalAutomaticDriverAssessment:
        """Change the dedicated gate without replaying a cached candidate."""

        _require_aware(changed_at)
        enabled = bool(enabled)
        if enabled == self.requested_enabled and self.assessment is not None:
            return self.assessment
        self.requested_enabled = enabled
        self._enabled_after_epoch_identity = (
            current_epoch_identity if enabled else None
        )
        if not enabled:
            if self._delivery_in_flight:
                self._retire_after_inflight = True
            else:
                self._retire_session(
                    at=changed_at,
                    reason="automatic_thermal_driver_disabled",
                )
        return self._publish(
            state=(
                ThermalAutomaticDriverState.BLOCKED
                if enabled
                else ThermalAutomaticDriverState.DISABLED
            ),
            evaluated_at=changed_at,
            blocker=(
                "automatic_thermal_fresh_epoch_required_after_enable"
                if enabled
                else "automatic_thermal_driver_disabled"
            ),
            frame=None,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=False,
        )

    def note_disabled_epoch(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> ThermalAutomaticDriverAssessment:
        """Record current truth without creating async work while disabled."""

        self._accept_epoch(frame)
        return self._publish(
            state=ThermalAutomaticDriverState.DISABLED,
            evaluated_at=frame.observed_at,
            blocker="automatic_thermal_driver_disabled",
            frame=frame,
            body=_candidate_body(frame),
            preflight=None,
            failure=None,
            command_delivery_performed=False,
        )

    def restrictive_authority_changed(
        self,
        *,
        changed_at: datetime,
    ) -> ThermalAutomaticDriverAssessment:
        """Invalidate continuation without replay when an external gate changes."""

        _require_aware(changed_at)
        if self._delivery_in_flight:
            self._retire_after_inflight = True
        else:
            self._retire_session(
                at=changed_at,
                reason="automatic_thermal_restrictive_authority_changed",
            )
        return self._publish(
            state=(
                ThermalAutomaticDriverState.BLOCKED
                if self.requested_enabled
                else ThermalAutomaticDriverState.DISABLED
            ),
            evaluated_at=changed_at,
            blocker=(
                "automatic_thermal_fresh_epoch_required_after_authority_change"
                if self.requested_enabled
                else "automatic_thermal_driver_disabled"
            ),
            frame=None,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=False,
        )

    async def process_epoch(
        self,
        frame: ThermalAutomaticExecutionFrame,
        *,
        delivery_factory: ThermalAutomaticDeliveryFactory,
    ) -> ThermalAutomaticDriverAssessment:
        """Verify prior work and submit at most one operation for this epoch."""

        if self._unloaded:
            return self._publish(
                state=ThermalAutomaticDriverState.UNLOADED,
                evaluated_at=frame.observed_at,
                blocker="automatic_thermal_driver_unloaded",
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )
        if frame.epoch_identity == self._last_epoch_identity:
            assert self.assessment is not None
            return self.assessment
        if self._last_epoch_at is not None and frame.observed_at < self._last_epoch_at:
            assert self.assessment is not None
            return self.assessment
        self._accept_epoch(frame)
        if not self.requested_enabled:
            return self.note_disabled_epoch(frame)
        if frame.epoch_identity == self._enabled_after_epoch_identity:
            return self._blocked(
                frame,
                "automatic_thermal_fresh_epoch_required_after_enable",
            )
        if not frame.physical_authority_ready:
            return self._terminate_for_frame(
                frame,
                frame.physical_authority_blocker
                or "automatic_thermal_physical_authority_unavailable",
            )
        if (
            frame.orchestration.outage is None
            or frame.orchestration.outage.disposition is not GridOutageDisposition.ON_GRID
        ):
            return self._terminate_for_frame(
                frame,
                "automatic_thermal_grid_not_authoritatively_on",
            )

        body = self._session_body(frame)
        if self.active_session is not None:
            if frame.orchestration.lifecycle not in {
                ThermalOrchestrationLifecycle.CANDIDATE_READY,
                ThermalOrchestrationLifecycle.OWNED,
            }:
                return self._terminate_for_frame(
                    frame,
                    frame.orchestration.blocking_reason,
                )
            assert body is not None
            if self.active_session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION:
                before = self.active_session
                store = ObservationStore()
                store.extend(
                    item for item in frame.observations if item.observed_at is not None
                )
                verified = self.engine.verify_current_step(
                    before,
                    store,
                    current_context=body.live_execution_context,
                    policy=frame.live_policy,
                    evaluated_at=frame.observed_at,
                )
                self.active_session = verified
                if verified.status in {
                    ThermalLiveExecutionStatus.BLOCKED,
                    ThermalLiveExecutionStatus.FAILED,
                    ThermalLiveExecutionStatus.TIMED_OUT,
                    ThermalLiveExecutionStatus.SUPERSEDED,
                }:
                    reason = verified.failure_reason or "automatic_thermal_verification_failed"
                    return self._terminate_for_frame(frame, reason)
                promotion_failure = self._promote_session(
                    before.ownership,
                    verified,
                    promoted_at=frame.observed_at,
                    requested_mode=body.requested_mode.value,
                )
                if promotion_failure is not None:
                    return self._terminate_for_frame(frame, promotion_failure)
                if verified.status is ThermalLiveExecutionStatus.COMPLETED:
                    self.active_session = None
                    return self._publish(
                        state=ThermalAutomaticDriverState.CONVERGED,
                        evaluated_at=frame.observed_at,
                        blocker=None,
                        frame=frame,
                        body=body,
                        preflight=None,
                        failure=None,
                        command_delivery_performed=False,
                    )
                if verified.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION:
                    return self._publish(
                        state=ThermalAutomaticDriverState.AWAITING_VERIFICATION,
                        evaluated_at=frame.observed_at,
                        blocker=None,
                        frame=frame,
                        body=body,
                        preflight=None,
                        failure=None,
                        command_delivery_performed=False,
                    )

        if self.active_session is None:
            if frame.orchestration.lifecycle is ThermalOrchestrationLifecycle.OWNED:
                return self._blocked(
                    frame,
                    "automatic_thermal_owned_successor_requires_explicit_handoff",
                )
            if frame.orchestration.lifecycle is not ThermalOrchestrationLifecycle.CANDIDATE_READY:
                return self._blocked(frame, frame.orchestration.blocking_reason)
            body = _candidate_body(frame)
            if body is None:
                return self._blocked(frame, "automatic_thermal_candidate_unavailable")
            if body.body is ThermalBody.HOT_TUB:
                return self._blocked(
                    frame,
                    "automatic_thermal_hot_tub_pump_ownership_unproven",
                )
            preflight = self.engine.authorization_engine.structural_preflight(
                body.plan,
                policy=frame.live_policy,
            )
            if not preflight.eligible:
                return self._blocked(
                    frame,
                    "automatic_thermal_plan_preflight_failed:"
                    + ",".join(preflight.blocking_reasons),
                    body=body,
                    preflight=preflight,
                )
            if body.body_active is True:
                return self._blocked(
                    frame,
                    "automatic_thermal_preexisting_body_unowned",
                    body=body,
                    preflight=preflight,
                )
            if (
                not body.plan.operations
                or not isinstance(body.plan.operations[0], SetBodyActive)
                or body.plan.operations[0].active is not True
            ):
                return self._blocked(
                    frame,
                    "automatic_thermal_cold_start_activation_required",
                    body=body,
                    preflight=preflight,
                )
            safety = body.live_safety_evidence
            if safety is None:
                return self._blocked(
                    frame,
                    "automatic_thermal_live_safety_evidence_unavailable",
                    body=body,
                    preflight=preflight,
                )
            try:
                self.active_session = self.engine.begin(
                    body.plan,
                    policy=frame.live_policy,
                    evidence=safety,
                )
            except ValueError as exc:
                return self._blocked(
                    frame,
                    f"automatic_thermal_session_begin_failed:{_bounded(str(exc))}",
                    body=body,
                    preflight=preflight,
                )

        assert self.active_session is not None and body is not None
        safety = body.live_safety_evidence
        if safety is None:
            return self._terminate_for_frame(
                frame,
                "automatic_thermal_live_safety_evidence_unavailable",
            )
        if self.active_session is not None:
            safety = replace(
                safety,
                evaluation_id=self.active_session.evaluation_id,
            )
        try:
            delivery = delivery_factory.for_session(
                self.active_session,
                epoch_identity=frame.epoch_identity,
            )
        except (RuntimeError, ValueError) as exc:
            return self._terminate_for_frame(
                frame,
                f"automatic_thermal_delivery_binding_failed:{_bounded(str(exc))}",
            )
        self._delivery_in_flight = True
        try:
            delivered = await self.engine.deliver_current_step(
                self.active_session,
                policy=frame.live_policy,
                evidence=safety,
                delivery=delivery,
            )
        finally:
            self._delivery_in_flight = False
        self.active_session = delivered
        command_performed = delivered.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
        if command_performed:
            self._accepted_delivery_count += 1
            attempt = delivered.current_attempt
            assert attempt is not None
            self._last_accepted_correlation_id = attempt.correlation_id
            promotion_failure = self._promote_session(
                delivered.ownership,
                delivered,
                promoted_at=frame.observed_at,
                requested_mode=body.requested_mode.value,
            )
            if promotion_failure is not None:
                self._retire_session(
                    at=frame.observed_at,
                    reason=promotion_failure,
                )
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker=promotion_failure,
                    frame=frame,
                    body=body,
                    preflight=None,
                    failure=promotion_failure,
                    command_delivery_performed=True,
                )
        if self._retire_after_inflight or not self.requested_enabled or self._unloaded:
            self._retire_after_inflight = False
            self._retire_session(
                at=frame.observed_at,
                reason="automatic_thermal_driver_disabled_after_delivery",
            )
            return self._publish(
                state=(
                    ThermalAutomaticDriverState.DISABLED
                    if not self.requested_enabled or self._unloaded
                    else ThermalAutomaticDriverState.BLOCKED
                ),
                evaluated_at=frame.observed_at,
                blocker=(
                    "automatic_thermal_driver_unloaded"
                    if self._unloaded
                    else (
                        "automatic_thermal_driver_disabled"
                        if not self.requested_enabled
                        else "automatic_thermal_fresh_epoch_required_after_authority_change"
                    )
                ),
                frame=frame,
                body=body,
                preflight=None,
                failure=None,
                command_delivery_performed=command_performed,
            )
        if delivered.status is not ThermalLiveExecutionStatus.AWAITING_VERIFICATION:
            reason = delivered.failure_reason or "automatic_thermal_delivery_failed"
            return self._terminate_for_frame(frame, reason)
        return self._publish(
            state=ThermalAutomaticDriverState.AWAITING_REOBSERVATION,
            evaluated_at=frame.observed_at,
            blocker=None,
            frame=frame,
            body=body,
            preflight=None,
            failure=None,
            command_delivery_performed=True,
        )

    def fail_closed(
        self,
        *,
        failed_at: datetime,
        reason: str,
    ) -> ThermalAutomaticDriverAssessment:
        """Invalidate stale candidate/session truth after adapter failure."""

        _require_aware(failed_at)
        self._retire_session(at=failed_at, reason=reason)
        return self._publish(
            state=ThermalAutomaticDriverState.FAILED,
            evaluated_at=failed_at,
            blocker=reason,
            frame=None,
            body=None,
            preflight=None,
            failure=reason,
            command_delivery_performed=False,
        )

    def unload(self, *, unloaded_at: datetime) -> ThermalAutomaticDriverAssessment:
        """Discard sessions/ownership without issuing physical cleanup."""

        _require_aware(unloaded_at)
        self._unloaded = True
        self.requested_enabled = False
        self._retire_session(
            at=unloaded_at,
            reason="automatic_thermal_driver_unloaded",
        )
        return self._publish(
            state=ThermalAutomaticDriverState.UNLOADED,
            evaluated_at=unloaded_at,
            blocker="automatic_thermal_driver_unloaded",
            frame=None,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=False,
        )

    def diagnostics(self) -> Mapping[str, object]:
        """Return bounded commissioning evidence; never authorize delivery."""

        assessment = self.assessment
        if assessment is None:
            return MappingProxyType(
                {
                    "state": ThermalAutomaticDriverState.DISABLED.value,
                    "requested_enabled": self.requested_enabled,
                    "effective_enabled": False,
                    "blocker": "automatic_thermal_driver_not_evaluated",
                    "accepted_delivery_count": self._accepted_delivery_count,
                    "command_delivery_performed": False,
                }
            )
        return MappingProxyType(
            {
                "state": assessment.state.value,
                "requested_enabled": assessment.requested_enabled,
                "effective_enabled": assessment.effective_enabled,
                "blocker": assessment.blocker,
                "candidate_body": (
                    None
                    if assessment.candidate_body is None
                    else assessment.candidate_body.value
                ),
                "candidate_evaluation_id": assessment.candidate_evaluation_id,
                "candidate_plan_id": assessment.candidate_plan_id,
                "candidate_execution_purpose_id": (
                    assessment.candidate_execution_purpose_id
                ),
                "static_preflight_eligible": assessment.static_preflight_eligible,
                "static_preflight_blocker": assessment.static_preflight_blocker,
                "active_session_identity": assessment.active_session_identity,
                "current_step_sequence": assessment.current_step_sequence,
                "current_step_operation_id": assessment.current_step_operation_id,
                "awaiting_reobservation": assessment.awaiting_reobservation,
                "awaiting_verification": assessment.awaiting_verification,
                "runtime_ownership_status": assessment.runtime_ownership_status.value,
                "runtime_ownership_summary": dict(
                    assessment.runtime_ownership_summary
                ),
                "outage_state": assessment.outage_state,
                "last_transition_at": assessment.last_transition_at.isoformat(),
                "last_failure_reason": assessment.last_failure_reason,
                "accepted_delivery_count": assessment.accepted_delivery_count,
                "last_accepted_correlation_id": (
                    assessment.last_accepted_correlation_id
                ),
                "command_delivery_performed": assessment.command_delivery_performed,
                "automatic_retry_enabled": False,
                "session_persistence_enabled": False,
                "generic_cleanup_enabled": False,
            }
        )

    def _accept_epoch(self, frame: ThermalAutomaticExecutionFrame) -> None:
        self._last_epoch_identity = frame.epoch_identity
        self._last_epoch_at = frame.observed_at

    def _session_body(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> ThermalBodyRuntimeAssessment | None:
        if self.active_session is None or frame.thermal is None:
            return _candidate_body(frame)
        return (
            frame.thermal.pool
            if self.active_session.assessment.desired.body is ThermalBody.POOL
            else frame.thermal.hot_tub
        )

    def _promote_session(
        self,
        ownership,
        session: ThermalLiveExecutionSession,
        *,
        promoted_at: datetime,
        requested_mode: str,
    ) -> str | None:
        decision = self.orchestrator.ownership.promote_session_provenance(
            ownership,
            promoted_at=promoted_at,
            requested_mode=requested_mode,
            originating_context=session.originating_context,
            execution_progress=session.execution_progress,
        )
        if decision.current_state.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return decision.reason_code
        return None

    def _retire_session(self, *, at: datetime, reason: str) -> None:
        lease = self.orchestrator.ownership.state.lease
        if lease is not None and lease.status is ThermalRuntimeOwnershipStatus.OWNED:
            self.orchestrator.ownership.relinquish(
                lease_id=lease.lease_id,
                relinquished_at=at,
                reason_code=reason,
            )
        self.active_session = None

    def _terminate_for_frame(
        self,
        frame: ThermalAutomaticExecutionFrame,
        reason: str,
    ) -> ThermalAutomaticDriverAssessment:
        state = (
            ThermalAutomaticDriverState.SUPERSEDED
            if "supersed" in reason
            else (
                ThermalAutomaticDriverState.PREEMPTED
                if "preempt" in reason or "hydraulic" in reason or "grid" in reason
                else ThermalAutomaticDriverState.BLOCKED
            )
        )
        self._retire_session(at=frame.observed_at, reason=reason)
        return self._publish(
            state=state,
            evaluated_at=frame.observed_at,
            blocker=reason,
            frame=frame,
            body=_candidate_body(frame),
            preflight=None,
            failure=reason if state is ThermalAutomaticDriverState.FAILED else None,
            command_delivery_performed=False,
        )

    def _blocked(
        self,
        frame: ThermalAutomaticExecutionFrame,
        reason: str,
        *,
        body: ThermalBodyRuntimeAssessment | None = None,
        preflight: ThermalLiveStructuralPreflightResult | None = None,
    ) -> ThermalAutomaticDriverAssessment:
        return self._publish(
            state=ThermalAutomaticDriverState.BLOCKED,
            evaluated_at=frame.observed_at,
            blocker=reason,
            frame=frame,
            body=body or _candidate_body(frame),
            preflight=preflight,
            failure=None,
            command_delivery_performed=False,
        )

    def _publish(
        self,
        *,
        state: ThermalAutomaticDriverState,
        evaluated_at: datetime,
        blocker: str | None,
        frame: ThermalAutomaticExecutionFrame | None,
        body: ThermalBodyRuntimeAssessment | None,
        preflight: ThermalLiveStructuralPreflightResult | None,
        failure: str | None,
        command_delivery_performed: bool,
    ) -> ThermalAutomaticDriverAssessment:
        session = self.active_session
        step = None
        if session is not None and session.status is ThermalLiveExecutionStatus.READY:
            selected = self.engine.coordinator.current_step(
                session.execution_plan,
                session.coordination,
            )
            step = selected.current_step
        elif session is not None and session.current_attempt is not None:
            step = session.current_attempt.step
        lease = self.orchestrator.ownership.state.lease
        ownership_summary = {
            "body": None if lease is None else lease.body.value,
            "owns_body_activation": bool(lease and lease.owns_body_activation),
            "owns_pump_setpoint": bool(lease and lease.owns_pump_setpoint),
            "owns_heat_source": bool(lease and lease.owns_heat_source),
            "reason_code": self.orchestrator.ownership.state.reason_code,
        }
        previous = self.assessment
        last_transition = (
            evaluated_at
            if previous is None
            or (previous.state, previous.blocker) != (state, blocker)
            else previous.last_transition_at
        )
        outage = None
        if frame is not None and frame.orchestration.outage is not None:
            outage = frame.orchestration.outage.disposition.value
        self.assessment = ThermalAutomaticDriverAssessment(
            state=state,
            evaluated_at=evaluated_at,
            requested_enabled=self.requested_enabled,
            effective_enabled=(
                self.requested_enabled
                and frame is not None
                and frame.physical_authority_ready
                and frame.live_policy.thermal_live_execution_enabled
            ),
            blocker=blocker,
            candidate_body=None if body is None else body.body,
            candidate_evaluation_id=None if body is None else body.evaluation_id,
            candidate_plan_id=None if body is None else body.plan.plan_id,
            candidate_execution_purpose_id=(
                None
                if body is None
                else body.execution_currentness.purpose.purpose_id
            ),
            static_preflight_eligible=None if preflight is None else preflight.eligible,
            static_preflight_blocker=(
                None
                if preflight is None or preflight.eligible
                else ",".join(preflight.blocking_reasons)
            ),
            active_session_identity=(
                None if session is None else session.execution_plan.plan_id
            ),
            current_step_sequence=None if step is None else step.sequence,
            current_step_operation_id=(
                None if step is None else step.operation.operation_id
            ),
            awaiting_reobservation=(
                state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
            ),
            awaiting_verification=(
                session is not None
                and session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
            ),
            runtime_ownership_status=self.orchestrator.ownership.state.status,
            runtime_ownership_summary=ownership_summary,
            outage_state=outage,
            last_transition_at=last_transition,
            last_failure_reason=failure,
            accepted_delivery_count=self._accepted_delivery_count,
            last_accepted_correlation_id=self._last_accepted_correlation_id,
            command_delivery_performed=command_delivery_performed,
        )
        return self.assessment


def _candidate_body(
    frame: ThermalAutomaticExecutionFrame,
) -> ThermalBodyRuntimeAssessment | None:
    if frame.thermal is None or frame.orchestration.candidate_body is None:
        return None
    return (
        frame.thermal.pool
        if frame.orchestration.candidate_body is ThermalBody.POOL
        else frame.thermal.hot_tub
    )


def _bounded(value: str, limit: int = 256) -> str:
    return " ".join(value.split())[:limit]


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("automatic thermal timestamp must be timezone-aware")


__all__ = [
    "ThermalAutomaticDeliveryFactory",
    "ThermalAutomaticDriverAssessment",
    "ThermalAutomaticDriverState",
    "ThermalAutomaticExecutionDriver",
    "ThermalAutomaticExecutionFrame",
]
