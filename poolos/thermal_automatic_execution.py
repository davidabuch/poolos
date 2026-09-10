"""Default-off event-driven automatic thermal execution supervision.

The driver consumes the existing runtime assessment, command-free orchestrator,
canonical currentness contract, scoped live engine, and runtime ownership
manager.  It owns no scheduler, transport, polling loop, persistence, retry, or
generic cleanup command.  One call represents one authoritative observation
epoch and may submit at most one new physical operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol

from .circulation_successor import (
    CirculationSuccessorArbitrator,
    CirculationSuccessorAssessment,
    FiltrationSuccessorEvidence,
)
from .external_change import ExternalChangeBatch
from .grid_outage_confirmation import GridOutageDisposition
from .integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from .clock import FixedClock
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
)
from .pool_temperature_probe_execution import (
    PoolTemperatureProbeExecutionEvidence,
    PoolTemperatureProbeExecutionPhase,
)
from .pool_circulation_ownership import (
    FiltrationToThermalHandoff,
    PoolCirculationOwnershipRegistry,
)
from .operating_baselines import PumpOperatingBaselines
from .pump_speed_session import PumpSpeedOverrideState, PumpSpeedSessionPurpose
from .spa_thermal_policy import SpaSessionKind
from .thermal_execution_currentness import ThermalExecutionPurposeKind
from .thermal_execution_planning import ThermalPlanDisposition
from .thermal_live_execution import (
    ThermalLiveDeliveryPort,
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
    ThermalLiveExecutionStatus,
    ThermalLiveStructuralPreflightResult,
)
from .thermal_circulation_cleanup import (
    ThermalCirculationCleanupAction,
    ThermalCirculationCleanupAttempt,
    ThermalCirculationCleanupCandidate,
    ThermalCirculationCleanupProvenance,
)
from .thermal_runtime_assessment import (
    ThermalBodyRuntimeAssessment,
    ThermalRuntimeAssessment,
)
from .thermal_runtime_orchestration import (
    ThermalOrchestrationLifecycle,
    ThermalRuntimeOrchestrationAssessment,
    ThermalRuntimeOrchestrator,
    build_thermal_runtime_ownership_evidence,
)
from .thermal_runtime_ownership import (
    SharedHydraulicSafetyClass,
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeHandoffRequest,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipDisposition,
    ThermalRuntimeOwnershipStatus,
)
from .thermal_termination import (
    ThermalTerminationAssessment,
    ThermalTerminationDisposition,
    ThermalTerminationPolicy,
)

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
    TERMINATING = "terminating"
    AWAITING_TERMINATION_VERIFICATION = "awaiting_termination_verification"
    CLEANUP_WAITING = "cleanup_waiting"
    AWAITING_CLEANUP_VERIFICATION = "awaiting_cleanup_verification"
    OBSERVING_SOLAR_ENGAGEMENT = "observing_solar_engagement"
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
    filtration_successor: FiltrationSuccessorEvidence | None = None
    external_changes: ExternalChangeBatch = ExternalChangeBatch(())
    pool_automatic_control_suppressed: bool = False
    spa_automatic_control_suppressed: bool = False

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

    def for_termination(
        self,
        *,
        body: ThermalBody,
        entitlement_id: str,
        epoch_identity: str,
    ) -> ThermalLiveDeliveryPort: ...

    def for_cleanup(
        self,
        candidate: ThermalCirculationCleanupCandidate,
        *,
        epoch_identity: str,
    ) -> ThermalLiveDeliveryPort: ...


@dataclass(frozen=True, slots=True)
class ThermalTerminationAttempt:
    """One accepted source-Off request awaiting later native confirmation."""

    entitlement_id: str
    entitlement_generation: int
    operation: SetHeatMode
    correlation_id: str
    delivered_at: datetime
    deadline: datetime


@dataclass(frozen=True, slots=True)
class SolarEngagementPolicy:
    """Bound one PoolOS-started Solar opportunity without verifying H0002."""

    observation_timeout: timedelta = timedelta(minutes=5)
    confirmation_hold: timedelta = timedelta(seconds=30)
    retry_suppression: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.observation_timeout <= timedelta(0):
            raise ValueError("Solar engagement observation timeout must be positive")
        if self.confirmation_hold < timedelta(0):
            raise ValueError("Solar engagement confirmation hold must not be negative")
        if self.retry_suppression < timedelta(0):
            raise ValueError("Solar retry suppression must not be negative")


@dataclass(frozen=True, slots=True)
class SolarEngagementAttempt:
    """One in-memory observation epoch after exact H0002 plan completion."""

    execution_purpose_id: str
    ownership_lease_id: str
    ownership_generation: int
    started_at: datetime
    deadline: datetime
    engaged_since: datetime | None = None

    def __post_init__(self) -> None:
        if not self.execution_purpose_id.strip() or not self.ownership_lease_id.strip():
            raise ValueError("Solar engagement provenance must not be empty")
        if self.ownership_generation < 1:
            raise ValueError("Solar engagement generation must be positive")
        if self.started_at.tzinfo is None or self.deadline.tzinfo is None:
            raise ValueError("Solar engagement timestamps must be timezone-aware")
        if self.deadline <= self.started_at:
            raise ValueError("Solar engagement deadline must follow its start")
        if self.engaged_since is not None:
            if self.engaged_since.tzinfo is None:
                raise ValueError("Solar engagement confirmation must be timezone-aware")
            if not self.started_at <= self.engaged_since <= self.deadline:
                raise ValueError("Solar engagement confirmation must belong to its epoch")


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
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    engine: ThermalLiveExecutionEngine = field(default_factory=ThermalLiveExecutionEngine)
    circulation_ownership: PoolCirculationOwnershipRegistry = field(
        default_factory=PoolCirculationOwnershipRegistry
    )
    requested_enabled: bool = False
    assessment: ThermalAutomaticDriverAssessment | None = None
    active_session: ThermalLiveExecutionSession | None = None
    termination_attempt: ThermalTerminationAttempt | None = None
    cleanup_provenance: ThermalCirculationCleanupProvenance | None = None
    cleanup_attempt: ThermalCirculationCleanupAttempt | None = None
    termination_policy: ThermalTerminationPolicy = field(
        default_factory=ThermalTerminationPolicy
    )
    circulation_arbitrator: CirculationSuccessorArbitrator = field(
        default_factory=CirculationSuccessorArbitrator
    )
    solar_engagement_policy: SolarEngagementPolicy = field(
        default_factory=SolarEngagementPolicy
    )
    solar_engagement_attempt: SolarEngagementAttempt | None = None
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
    _probe_acquisition: PoolTemperatureProbeExecutionEvidence | None = field(
        default=None, init=False, repr=False
    )
    _solar_suppressed_purpose_id: str | None = field(
        default=None, init=False, repr=False
    )
    _solar_suppressed_until: datetime | None = field(
        default=None, init=False, repr=False
    )
    _solar_nonengagement_cleanup_purpose_id: str | None = field(
        default=None, init=False, repr=False
    )
    _filtration_handoff: FiltrationToThermalHandoff | None = field(
        default=None, init=False, repr=False
    )
    _reenable_required: bool = field(default=False, init=False, repr=False)

    def reserve_circulation_candidate(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> None:
        """Synchronously reserve this epoch before another driver is scheduled."""

        if (
            self.requested_enabled
            and frame.physical_authority_ready
            and frame.live_policy.thermal_live_execution_enabled
            and not (
                frame.pool_automatic_control_suppressed
                and frame.orchestration.candidate_body is ThermalBody.POOL
            )
            and not (
                frame.spa_automatic_control_suppressed
                and frame.orchestration.candidate_body is ThermalBody.HOT_TUB
            )
            and frame.orchestration.candidate_body is ThermalBody.POOL
            and frame.orchestration.lifecycle
            in {
                ThermalOrchestrationLifecycle.CANDIDATE_READY,
                ThermalOrchestrationLifecycle.OWNED,
            }
        ):
            self.circulation_ownership.reserve_thermal(frame.epoch_identity)

    @property
    def last_epoch_identity(self) -> str | None:
        return self._last_epoch_identity

    def probe_execution_evidence(self) -> PoolTemperatureProbeExecutionEvidence | None:
        """Return positive in-memory probe provenance for the evaluator."""

        lease = self.orchestrator.ownership.state.lease
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease.originating_currentness is None
            or lease.originating_currentness.purpose.kind
            is not ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
        ):
            return None
        if self._probe_acquisition is not None:
            if (
                self._probe_acquisition.ownership_lease_id == lease.lease_id
                and self._probe_acquisition.ownership_generation == lease.generation
            ):
                return self._probe_acquisition
            return None
        if not (lease.owns_body_activation or lease.owns_pump_setpoint):
            return None
        return PoolTemperatureProbeExecutionEvidence(
            phase=PoolTemperatureProbeExecutionPhase.PREPARING,
            execution_purpose_id=lease.originating_currentness.purpose.purpose_id,
            execution_plan_id=lease.execution_plan_id,
            ownership_lease_id=lease.lease_id,
            ownership_generation=lease.generation,
            body_activation_owned=lease.owns_body_activation,
            pump_setpoint_owned=lease.owns_pump_setpoint,
        )

    def spa_session_kind(self) -> SpaSessionKind | None:
        """Return only positively proven PoolOS opportunistic Spa ownership."""

        lease = self.orchestrator.ownership.state.lease
        if (
            lease is not None
            and lease.status is ThermalRuntimeOwnershipStatus.OWNED
            and lease.body is ThermalBody.HOT_TUB
            and lease.body_activation is not None
        ):
            return SpaSessionKind.POOLOS_OPPORTUNISTIC
        return None

    def active_pump_session_purpose(self) -> PumpSpeedSessionPurpose | None:
        """Expose only explicit probe/priming execution-purpose boundaries."""

        session = self.active_session
        if session is None:
            return None
        sequence = session.coordination.current_step_sequence
        if sequence is not None:
            step = session.execution_plan.steps[sequence - 1]
            if step.metadata.get("priming_step") == "true":
                return PumpSpeedSessionPurpose.PRIMING
        if (
            session.originating_currentness.purpose.kind
            is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
        ):
            return PumpSpeedSessionPurpose.TEMPERATURE_PROBE
        return None

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
        if not enabled:
            self._reenable_required = False
        self._enabled_after_epoch_identity = (
            current_epoch_identity if enabled else None
        )
        if not enabled:
            self._clear_cleanup()
            self._probe_acquisition = None
            self.solar_engagement_attempt = None
            self._solar_nonengagement_cleanup_purpose_id = None
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
        self._clear_cleanup()
        self._probe_acquisition = None
        self.solar_engagement_attempt = None
        self._solar_nonengagement_cleanup_purpose_id = None
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
        if self._reenable_required:
            return self._blocked(frame, "automatic_thermal_reenable_required")
        if frame.epoch_identity == self._enabled_after_epoch_identity:
            return self._blocked(
                frame,
                "automatic_thermal_fresh_epoch_required_after_enable",
            )
        restrained_body = _restrained_body(self, frame)
        if (
            frame.pool_automatic_control_suppressed
            and restrained_body is ThermalBody.POOL
        ):
            return self._terminate_for_frame(
                frame,
                "automatic_thermal_manual_pool_off_preempted",
            )
        if (
            frame.spa_automatic_control_suppressed
            and restrained_body is ThermalBody.HOT_TUB
        ):
            return self._terminate_for_frame(
                frame,
                "automatic_thermal_manual_spa_off_preempted",
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

        engagement_result = self._process_solar_engagement(frame)
        if engagement_result is not None:
            return engagement_result

        termination_result = await self._process_termination(
            frame,
            delivery_factory=delivery_factory,
        )
        if termination_result is not None:
            return termination_result

        cleanup_result = await self._process_cleanup(
            frame,
            delivery_factory=delivery_factory,
        )
        if cleanup_result is not None:
            return cleanup_result

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
                    self._begin_verified_probe_acquisition(
                        verified,
                        started_at=frame.observed_at,
                    )
                    self._begin_solar_engagement_observation(
                        verified,
                        started_at=frame.observed_at,
                    )
                    self.active_session = None
                    return self._publish(
                        state=(
                            ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
                            if self.solar_engagement_attempt is not None
                            else ThermalAutomaticDriverState.CONVERGED
                        ),
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
                body = _candidate_body(frame)
                if body is None:
                    return self._blocked(
                        frame,
                        "automatic_thermal_owned_successor_unavailable",
                    )
                lease = self.orchestrator.ownership.state.lease
                currentness = body.execution_currentness
                if (
                    self._probe_acquisition is not None
                    and lease is not None
                    and lease.originating_currentness is not None
                    and currentness is not None
                    and currentness.purpose.kind
                    is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
                    and currentness.purpose.purpose_id
                    == self._probe_acquisition.execution_purpose_id
                    and lease.lease_id
                    == self._probe_acquisition.ownership_lease_id
                    and lease.generation
                    == self._probe_acquisition.ownership_generation
                ):
                    # Body activation completed the command-bearing portion of
                    # this purpose. Acquisition is now observation-only; an
                    # ALREADY_CONVERGED plan is not a successor to preflight.
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
                lease = self.orchestrator.ownership.state.lease
                session_requirement_current = bool(
                    lease is not None
                    and lease.pump_setpoint is None
                    and lease.pump_session_id is not None
                    and lease.pump_session_id == body.pump_session_id
                    and lease.pump_session_effective_rpm
                    == body.pump_session_effective_rpm
                )
                if (
                    body.pump_session_override_state
                    in {
                        PumpSpeedOverrideState.PENDING,
                        PumpSpeedOverrideState.VERIFIED,
                    }
                    or session_requirement_current
                ):
                    pending = (
                        body.pump_session_override_state
                        is PumpSpeedOverrideState.PENDING
                    )
                    return self._publish(
                        state=(
                            ThermalAutomaticDriverState.SESSION_ACTIVE
                            if pending
                            or body.plan.disposition is ThermalPlanDisposition.READY
                            else ThermalAutomaticDriverState.CONVERGED
                        ),
                        evaluated_at=frame.observed_at,
                        blocker=(
                            "automatic_thermal_pump_override_pending"
                            if pending
                            else (
                                "automatic_thermal_pump_override_awaiting_actual_rpm"
                                if body.plan.disposition
                                is ThermalPlanDisposition.READY
                                else None
                            )
                        ),
                        frame=frame,
                        body=body,
                        preflight=None,
                        failure=None,
                        command_delivery_performed=False,
                    )
                preflight = self.engine.authorization_engine.structural_preflight(
                    body.plan,
                    policy=frame.live_policy,
                )
                handoff_failure = self._begin_probe_successor_handoff(
                    frame,
                    body=body,
                    preflight=preflight,
                )
                if handoff_failure is not None:
                    return self._blocked(
                        frame,
                        handoff_failure,
                        body=body,
                        preflight=preflight,
                    )
            elif (
                frame.orchestration.lifecycle
                is not ThermalOrchestrationLifecycle.CANDIDATE_READY
            ):
                return self._blocked(frame, frame.orchestration.blocking_reason)
            else:
                body = _candidate_body(frame)
                if body is None:
                    return self._blocked(
                        frame,
                        "automatic_thermal_candidate_unavailable",
                    )
                if self._solar_retry_suppressed(body, at=frame.observed_at):
                    return self._blocked(
                        frame,
                        "automatic_thermal_solar_opportunity_retry_suppressed",
                        body=body,
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
                if (
                    body.body is ThermalBody.HOT_TUB
                    and body.body_active is True
                    and any(
                        step.metadata.get("priming_step") == "true"
                        for step in body.plan.step_specifications
                    )
                ):
                    return self._blocked(
                        frame,
                        "automatic_thermal_external_hot_tub_circulation_not_established",
                        body=body,
                        preflight=preflight,
                    )
                if body.body_active is True and body.body is ThermalBody.POOL:
                    self._filtration_handoff = (
                        self.circulation_ownership.begin_filtration_to_thermal(
                            thermal_purpose_id=(
                                body.execution_currentness.purpose.purpose_id
                            ),
                            established_at=frame.observed_at,
                        )
                    )
                    if (
                        self._filtration_handoff is None
                        and body.plan.desired.evidence.get("active_operating_purpose")
                        is None
                    ):
                        return self._blocked(
                            frame,
                            "automatic_thermal_preexisting_body_unowned",
                            body=body,
                            preflight=preflight,
                        )
                if (
                    self._filtration_handoff is None
                    and (
                        not body.plan.operations
                        or not isinstance(body.plan.operations[0], SetBodyActive)
                        or body.plan.operations[0].active is not True
                    )
                    and body.body_active is not True
                    and not _probe_source_precondition_then_activation(body)
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
                    if self._filtration_handoff is not None:
                        provenance = self._filtration_handoff.body_activation
                        seeded = replace(
                            self.active_session.ownership,
                            body_activation_operation_id=provenance.operation_id,
                            body_activation_receipt_id=provenance.receipt_id,
                            body_activation_correlation_id=provenance.correlation_id,
                        )
                        self.active_session = replace(
                            self.active_session,
                            ownership=seeded,
                        )
                except ValueError as exc:
                    if self._filtration_handoff is not None:
                        self.circulation_ownership.cancel_filtration_to_thermal(
                            token_id=self._filtration_handoff.token_id
                        )
                        self._filtration_handoff = None
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
                if self._filtration_handoff is not None:
                    self.circulation_ownership.invalidate_filtration_to_thermal(
                        token_id=self._filtration_handoff.token_id,
                    )
                    self._filtration_handoff = None
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
            lease = self.orchestrator.ownership.state.lease
            if lease is not None and body.body is ThermalBody.POOL:
                if self._filtration_handoff is not None:
                    self.circulation_ownership.complete_filtration_to_thermal(
                        token_id=self._filtration_handoff.token_id,
                        thermal_lease_id=lease.lease_id,
                    )
                    self._filtration_handoff = None
                else:
                    self.circulation_ownership.mark_thermal_owned(lease.lease_id)
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

    async def _process_termination(
        self,
        frame: ThermalAutomaticExecutionFrame,
        *,
        delivery_factory: ThermalAutomaticDeliveryFactory,
    ) -> ThermalAutomaticDriverAssessment | None:
        """Advance one residual source-Off lifecycle, never normal execution."""

        assessment = self._termination_assessment(frame)
        attempt = self.termination_attempt
        if attempt is not None:
            current = self.orchestrator.ownership.residual_termination
            if (
                current is None
                or current.entitlement_id != attempt.entitlement_id
                or current.generation != attempt.entitlement_generation
            ):
                self.termination_attempt = None
                return self._blocked(
                    frame,
                    "thermal_termination_stale_entitlement_token",
                )
            if (
                assessment is not None
                and assessment.source_action.value == "already_off"
            ):
                circulation = self._circulation_assessment(frame)
                self._capture_cleanup_provenance(
                    current,
                    frame=frame,
                    circulation=circulation,
                )
                self.orchestrator.ownership.consume_residual_termination(
                    entitlement_id=attempt.entitlement_id,
                )
                self.termination_attempt = None
                return self._publish(
                    state=ThermalAutomaticDriverState.CONVERGED,
                    evaluated_at=frame.observed_at,
                    blocker=None,
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=None,
                    command_delivery_performed=False,
                    circulation_assessment=circulation,
                )
            if (
                assessment is None
                or assessment.disposition
                in {
                    ThermalTerminationDisposition.INVALIDATED,
                    ThermalTerminationDisposition.NO_ENTITLEMENT,
                }
            ):
                if (
                    assessment is not None
                    and assessment.disposition
                    is ThermalTerminationDisposition.INVALIDATED
                ):
                    self.orchestrator.ownership.invalidate_residual_termination()
                self.termination_attempt = None
                return self._blocked(
                    frame,
                    "thermal_termination_verification_preempted",
                )
            if frame.observed_at >= attempt.deadline:
                self.termination_attempt = None
                self.orchestrator.ownership.invalidate_residual_termination()
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker="thermal_termination_source_off_verification_timed_out",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure="thermal_termination_source_off_verification_timed_out",
                    command_delivery_performed=False,
                )
            return self._publish(
                state=ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION,
                evaluated_at=frame.observed_at,
                blocker=None,
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )

        if assessment is None:
            return None
        if self.active_session is not None:
            self._retire_session(
                at=frame.observed_at,
                reason="automatic_thermal_residual_termination_required",
            )
            return self._publish(
                state=ThermalAutomaticDriverState.TERMINATING,
                evaluated_at=frame.observed_at,
                blocker="thermal_termination_fresh_epoch_required",
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )
        if assessment.disposition is ThermalTerminationDisposition.INVALIDATED:
            self.orchestrator.ownership.invalidate_residual_termination()
            return self._blocked(frame, assessment.reason_code)
        if assessment.disposition is ThermalTerminationDisposition.BLOCKED:
            return self._blocked(frame, assessment.reason_code)
        if assessment.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY:
            circulation = self._circulation_assessment(frame)
            entitlement = self.orchestrator.ownership.residual_termination
            self._capture_cleanup_provenance(
                entitlement,
                frame=frame,
                circulation=circulation,
            )
            if assessment.entitlement_id is not None:
                self.orchestrator.ownership.consume_residual_termination(
                    entitlement_id=assessment.entitlement_id,
                )
            return self._publish(
                state=ThermalAutomaticDriverState.CONVERGED,
                evaluated_at=frame.observed_at,
                blocker=assessment.reason_code,
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
                circulation_assessment=circulation,
            )
        if assessment.disposition is not ThermalTerminationDisposition.SOURCE_OFF_READY:
            return None
        assert assessment.operation is not None
        assert assessment.body in {ThermalBody.POOL, ThermalBody.HOT_TUB}
        assert assessment.entitlement_id is not None
        assert assessment.entitlement_generation is not None
        if not frame.live_policy.thermal_live_execution_enabled:
            return self._blocked(frame, "thermal_termination_thermal_live_disabled")
        if frame.live_policy.commissioning_scope.value != assessment.body.value:
            return self._blocked(frame, "thermal_termination_commissioning_scope_mismatch")
        try:
            delivery = delivery_factory.for_termination(
                body=assessment.body,
                entitlement_id=assessment.entitlement_id,
                epoch_identity=frame.epoch_identity,
            )
        except (RuntimeError, ValueError) as exc:
            return self._blocked(
                frame,
                f"thermal_termination_delivery_binding_failed:{_bounded(str(exc))}",
            )
        if not delivery.available:
            return self._blocked(frame, "thermal_termination_delivery_unavailable")
        correlation_id = (
            f"thermal-termination:{assessment.entitlement_id}:"
            f"{assessment.operation.operation_id}"
        )
        self._delivery_in_flight = True
        try:
            try:
                receipt = await delivery.deliver(
                    assessment.operation,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                self.orchestrator.ownership.invalidate_residual_termination()
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker=f"thermal_termination_delivery_exception:{type(exc).__name__}",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=f"thermal_termination_delivery_exception:{type(exc).__name__}",
                    command_delivery_performed=False,
                )
        finally:
            self._delivery_in_flight = False
        if not receipt.accepted:
            self.orchestrator.ownership.invalidate_residual_termination()
            return self._publish(
                state=ThermalAutomaticDriverState.FAILED,
                evaluated_at=frame.observed_at,
                blocker=f"thermal_termination_delivery_{receipt.status.value}",
                frame=frame,
                body=None,
                preflight=None,
                failure=f"thermal_termination_delivery_{receipt.status.value}",
                command_delivery_performed=False,
            )
        if self._retire_after_inflight or not self.requested_enabled or self._unloaded:
            self._retire_after_inflight = False
            self.termination_attempt = None
            return self._publish(
                state=(
                    ThermalAutomaticDriverState.UNLOADED
                    if self._unloaded
                    else ThermalAutomaticDriverState.DISABLED
                ),
                evaluated_at=frame.observed_at,
                blocker=(
                    "automatic_thermal_driver_unloaded"
                    if self._unloaded
                    else "automatic_thermal_driver_disabled"
                ),
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=True,
            )
        self.termination_attempt = ThermalTerminationAttempt(
            entitlement_id=assessment.entitlement_id,
            entitlement_generation=assessment.entitlement_generation,
            operation=assessment.operation,
            correlation_id=correlation_id,
            delivered_at=frame.observed_at,
            deadline=frame.observed_at + frame.live_policy.verification_timeout,
        )
        self._accepted_delivery_count += 1
        self._last_accepted_correlation_id = correlation_id
        return self._publish(
            state=ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION,
            evaluated_at=frame.observed_at,
            blocker=None,
            frame=frame,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=True,
        )

    async def _process_cleanup(
        self,
        frame: ThermalAutomaticExecutionFrame,
        *,
        delivery_factory: ThermalAutomaticDeliveryFactory,
    ) -> ThermalAutomaticDriverAssessment | None:
        """Advance one bounded Pool circulation-cleanup lifecycle."""

        provenance = self.cleanup_provenance
        if provenance is None:
            return None
        if provenance.body is ThermalBody.HOT_TUB:
            return await self._process_hot_tub_cleanup(
                frame,
                provenance=provenance,
                delivery_factory=delivery_factory,
            )
        assessment = self._circulation_assessment(frame)
        if assessment is None:
            self._clear_cleanup()
            return self._blocked(frame, "thermal_cleanup_arbitration_unavailable")

        attempt = self.cleanup_attempt
        if attempt is not None:
            if (
                attempt.candidate.provenance_id != provenance.provenance_id
                or attempt.candidate.provenance_generation != provenance.generation
            ):
                self._clear_cleanup()
                return self._blocked(frame, "thermal_cleanup_stale_provenance")
            verification = self._cleanup_verification(frame, attempt, assessment)
            if verification == "verified":
                action = attempt.candidate.action
                self.cleanup_attempt = None
                if action is ThermalCirculationCleanupAction.BODY_DEACTIVATION:
                    self.cleanup_provenance = None
                    self.circulation_ownership.release_thermal()
                    return self._publish(
                        state=ThermalAutomaticDriverState.CONVERGED,
                        evaluated_at=frame.observed_at,
                        blocker="thermal_cleanup_pool_body_off_verified",
                        frame=frame,
                        body=None,
                        preflight=None,
                        failure=None,
                        command_delivery_performed=False,
                        circulation_assessment=assessment,
                    )
                operation = attempt.candidate.operation
                assert isinstance(operation, SetPumpSpeed)
                if provenance.body_activation is not None:
                    self.circulation_ownership.accept_thermal_to_filtration(
                        session_id=f"thermal-successor:{provenance.provenance_id}",
                        pool_pump_circuit_id=operation.equipment_id,
                        accepted_at=frame.observed_at,
                        body_activation=provenance.body_activation,
                        pump_setpoint=ThermalRuntimeConceptProvenance(
                            concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
                            operation_id=operation.operation_id,
                            receipt_id=attempt.receipt_id,
                            correlation_id=attempt.correlation_id,
                            intended_value=operation.rpm,
                        ),
                    )
                else:
                    self.circulation_ownership.release_thermal()
                self.cleanup_provenance = None
                return self._publish(
                    state=ThermalAutomaticDriverState.CONVERGED,
                    evaluated_at=frame.observed_at,
                    blocker="thermal_cleanup_filtration_handoff_verified",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=None,
                    command_delivery_performed=False,
                    circulation_assessment=assessment,
                )
            if verification.startswith("failed:"):
                reason = verification.removeprefix("failed:")
                self._clear_cleanup()
                self.circulation_ownership.release_thermal(
                    thermal_lease_id=provenance.lease_id,
                )
                return self._publish(
                    state=ThermalAutomaticDriverState.PREEMPTED,
                    evaluated_at=frame.observed_at,
                    blocker=reason,
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=reason,
                    command_delivery_performed=False,
                    circulation_assessment=assessment,
                )
            if frame.observed_at >= attempt.deadline:
                self._clear_cleanup()
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker="thermal_cleanup_verification_timed_out",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure="thermal_cleanup_verification_timed_out",
                    command_delivery_performed=False,
                    circulation_assessment=assessment,
                )
            return self._publish(
                state=ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION,
                evaluated_at=frame.observed_at,
                blocker=None,
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
                circulation_assessment=assessment,
            )

        if assessment.external_takeover or assessment.topology_conflict:
            reason = assessment.reason_code
            self._clear_cleanup()
            self.circulation_ownership.release_thermal(
                thermal_lease_id=provenance.lease_id,
            )
            return self._publish(
                state=ThermalAutomaticDriverState.PREEMPTED,
                evaluated_at=frame.observed_at,
                blocker=reason,
                frame=frame,
                body=None,
                preflight=None,
                failure=reason,
                command_delivery_performed=False,
                circulation_assessment=assessment,
            )

        if not assessment.filtration_immediate_need and provenance.pump_setpoint is not None:
            self.cleanup_provenance = provenance.without_pump()
            provenance = self.cleanup_provenance
            if provenance is None:
                return self._publish(
                    state=ThermalAutomaticDriverState.CONVERGED,
                    evaluated_at=frame.observed_at,
                    blocker="thermal_cleanup_pump_provenance_relinquished",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=None,
                    command_delivery_performed=False,
                    circulation_assessment=assessment,
                )

        candidate = ThermalCirculationCleanupCandidate.from_arbitration(
            provenance=provenance,
            assessment=assessment,
            epoch_identity=frame.epoch_identity,
            pump_circuit_id=(
                None
                if frame.thermal is None
                else frame.thermal.pool_pump_circuit_id
            ),
        )
        if candidate is None:
            return self._publish(
                state=ThermalAutomaticDriverState.CLEANUP_WAITING,
                evaluated_at=frame.observed_at,
                blocker=assessment.reason_code,
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
                circulation_assessment=assessment,
            )
        if not frame.live_policy.thermal_live_execution_enabled:
            return self._blocked(frame, "thermal_cleanup_thermal_live_disabled")
        if frame.live_policy.commissioning_scope.value != ThermalBody.POOL.value:
            return self._blocked(frame, "thermal_cleanup_commissioning_scope_mismatch")
        try:
            delivery = delivery_factory.for_cleanup(
                candidate,
                epoch_identity=frame.epoch_identity,
            )
        except (RuntimeError, ValueError) as exc:
            return self._blocked(
                frame,
                f"thermal_cleanup_delivery_binding_failed:{_bounded(str(exc))}",
            )
        if not delivery.available:
            return self._blocked(frame, "thermal_cleanup_delivery_unavailable")
        correlation_id = (
            f"thermal-cleanup:{candidate.provenance_id}:{candidate.candidate_id}:"
            f"{candidate.operation.operation_id}"
        )
        self._delivery_in_flight = True
        try:
            try:
                receipt = await delivery.deliver(
                    candidate.operation,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                self._clear_cleanup()
                reason = f"thermal_cleanup_delivery_exception:{type(exc).__name__}"
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker=reason,
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=reason,
                    command_delivery_performed=False,
                    circulation_assessment=assessment,
                )
        finally:
            self._delivery_in_flight = False
        if not receipt.accepted:
            authority_reason = receipt.details.get("authority_reason")
            if authority_reason == "automatic_thermal_context_stale":
                return self._blocked(frame, "thermal_cleanup_dispatch_context_stale")
            self._clear_cleanup()
            reason = f"thermal_cleanup_delivery_{receipt.status.value}"
            return self._publish(
                state=ThermalAutomaticDriverState.FAILED,
                evaluated_at=frame.observed_at,
                blocker=reason,
                frame=frame,
                body=None,
                preflight=None,
                failure=reason,
                command_delivery_performed=False,
                circulation_assessment=assessment,
            )
        if self._retire_after_inflight or not self.requested_enabled or self._unloaded:
            self._retire_after_inflight = False
            self._clear_cleanup()
            return self._publish(
                state=(
                    ThermalAutomaticDriverState.UNLOADED
                    if self._unloaded
                    else ThermalAutomaticDriverState.DISABLED
                ),
                evaluated_at=frame.observed_at,
                blocker=(
                    "automatic_thermal_driver_unloaded"
                    if self._unloaded
                    else "automatic_thermal_driver_disabled"
                ),
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=True,
                circulation_assessment=assessment,
            )
        self.cleanup_attempt = ThermalCirculationCleanupAttempt(
            candidate=candidate,
            correlation_id=correlation_id,
            receipt_id=receipt.command_id,
            delivered_at=frame.observed_at,
            deadline=frame.observed_at + frame.live_policy.verification_timeout,
        )
        self._accepted_delivery_count += 1
        self._last_accepted_correlation_id = correlation_id
        return self._publish(
            state=ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION,
            evaluated_at=frame.observed_at,
            blocker=None,
            frame=frame,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=True,
            circulation_assessment=assessment,
        )

    def _termination_assessment(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> ThermalTerminationAssessment | None:
        entitlement = self.orchestrator.ownership.residual_termination
        if entitlement is None or frame.thermal is None:
            return None
        body = (
            frame.thermal.pool
            if entitlement.body is ThermalBody.POOL
            else frame.thermal.hot_tub
        )
        assessment = self.termination_policy.evaluate(
            entitlement,
            build_thermal_runtime_ownership_evidence(
                generated_at=frame.observed_at,
                observations={item.observation_id: item for item in frame.observations},
                body=body,
                external_changes=frame.external_changes,
            ),
            desired_source=(
                PhysicalHeatMode.OFF
                if self._solar_nonengagement_cleanup_purpose_id is not None
                else body.plan.desired.selected_source
            ),
            verification_after=(
                None
                if self.termination_attempt is None
                else self.termination_attempt.delivered_at
            ),
        )
        return assessment

    def _circulation_assessment(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> CirculationSuccessorAssessment | None:
        """Evaluate command-free successor truth without mutating entitlement."""

        entitlement = self.orchestrator.ownership.residual_termination
        if entitlement is None and self.cleanup_provenance is not None:
            entitlement = self.cleanup_provenance.arbitration_entitlement()
        if entitlement is None or frame.thermal is None:
            return None
        body = (
            frame.thermal.pool
            if entitlement.body is ThermalBody.POOL
            else frame.thermal.hot_tub
        )
        return self.circulation_arbitrator.evaluate(
            entitlement=entitlement,
            evidence=build_thermal_runtime_ownership_evidence(
                generated_at=frame.observed_at,
                observations={item.observation_id: item for item in frame.observations},
                body=body,
                external_changes=frame.external_changes,
            ),
            filtration=frame.filtration_successor,
            outage=frame.orchestration.outage,
        )

    def _capture_cleanup_provenance(
        self,
        entitlement: ThermalResidualTerminationEntitlement | None,
        *,
        frame: ThermalAutomaticExecutionFrame,
        circulation: CirculationSuccessorAssessment | None,
    ) -> None:
        """Capture accepted body/pump proof only after authoritative source Off."""

        if entitlement is None:
            return
        if entitlement.body is ThermalBody.POOL and (
            circulation is None or not circulation.source_cleanup_complete
        ):
            return
        if (
            entitlement.body is ThermalBody.HOT_TUB
            and entitlement.body_activation is None
        ):
            return
        captured = ThermalCirculationCleanupProvenance.from_residual(
            entitlement,
            established_at=frame.observed_at,
        )
        if captured is not None:
            self.cleanup_provenance = captured
            self._solar_nonengagement_cleanup_purpose_id = None

    async def _process_hot_tub_cleanup(
        self,
        frame: ThermalAutomaticExecutionFrame,
        *,
        provenance: ThermalCirculationCleanupProvenance,
        delivery_factory: ThermalAutomaticDeliveryFactory,
    ) -> ThermalAutomaticDriverAssessment:
        """Release only a positively owned opportunistic Spa activation."""

        if frame.thermal is None:
            self._clear_cleanup()
            return self._blocked(frame, "hot_tub_cleanup_thermal_evidence_unavailable")
        body = frame.thermal.hot_tub
        evidence = build_thermal_runtime_ownership_evidence(
            generated_at=frame.observed_at,
            observations={item.observation_id: item for item in frame.observations},
            body=body,
            external_changes=frame.external_changes,
        )
        external_reason = self.termination_policy.evaluate(
            provenance.arbitration_entitlement(),
            evidence,
            desired_source=PhysicalHeatMode.OFF,
        )
        attempt = self.cleanup_attempt
        if attempt is not None:
            if (
                evidence.pool_active is False
                and evidence.pool_activity_fresh
                and evidence.pool_activity_usable
                and evidence.spa_active is False
                and evidence.spa_activity_fresh
                and evidence.spa_activity_usable
                and evidence.spa_activity_observed_at is not None
                and evidence.spa_activity_observed_at > attempt.delivered_at
            ):
                self._clear_cleanup()
                self.circulation_ownership.release_thermal(
                    thermal_lease_id=provenance.lease_id
                )
                return self._publish(
                    state=ThermalAutomaticDriverState.CONVERGED,
                    evaluated_at=frame.observed_at,
                    blocker="hot_tub_cleanup_body_off_verified",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=None,
                    command_delivery_performed=False,
                )
            if external_reason.disposition is ThermalTerminationDisposition.INVALIDATED:
                self._clear_cleanup()
                self.circulation_ownership.release_thermal(
                    thermal_lease_id=provenance.lease_id
                )
                return self._blocked(frame, external_reason.reason_code)
            if frame.observed_at >= attempt.deadline:
                self._clear_cleanup()
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker="hot_tub_cleanup_verification_timed_out",
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure="hot_tub_cleanup_verification_timed_out",
                    command_delivery_performed=False,
                )
            return self._publish(
                state=ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION,
                evaluated_at=frame.observed_at,
                blocker=None,
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )

        if evidence.spa_active is False and evidence.spa_activity_fresh and evidence.spa_activity_usable:
            self._clear_cleanup()
            self.circulation_ownership.release_thermal(
                thermal_lease_id=provenance.lease_id
            )
            return self._publish(
                state=ThermalAutomaticDriverState.CONVERGED,
                evaluated_at=frame.observed_at,
                blocker="hot_tub_cleanup_already_off",
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )
        if (
            external_reason.disposition is not ThermalTerminationDisposition.RELINQUISH_ONLY
            or external_reason.source_action.value != "already_off"
        ):
            if external_reason.disposition is ThermalTerminationDisposition.INVALIDATED:
                self._clear_cleanup()
                self.circulation_ownership.release_thermal(
                    thermal_lease_id=provenance.lease_id
                )
            return self._blocked(frame, external_reason.reason_code)
        candidate = ThermalCirculationCleanupCandidate.for_owned_hot_tub_release(
            provenance=provenance,
            epoch_identity=frame.epoch_identity,
            evaluated_at=frame.observed_at,
        )
        if candidate is None:
            self._clear_cleanup()
            return self._blocked(frame, "hot_tub_cleanup_activation_provenance_unavailable")
        if not frame.live_policy.thermal_live_execution_enabled:
            return self._blocked(frame, "hot_tub_cleanup_thermal_live_disabled")
        if frame.live_policy.commissioning_scope is not ThermalLiveCommissioningScope.HOT_TUB:
            return self._blocked(frame, "hot_tub_cleanup_commissioning_scope_mismatch")
        try:
            delivery = delivery_factory.for_cleanup(
                candidate,
                epoch_identity=frame.epoch_identity,
            )
        except (RuntimeError, ValueError) as exc:
            return self._blocked(
                frame,
                f"hot_tub_cleanup_delivery_binding_failed:{_bounded(str(exc))}",
            )
        if not delivery.available:
            return self._blocked(frame, "hot_tub_cleanup_delivery_unavailable")
        correlation_id = (
            f"hot-tub-cleanup:{candidate.provenance_id}:"
            f"{candidate.candidate_id}:{candidate.operation.operation_id}"
        )
        self._delivery_in_flight = True
        try:
            try:
                receipt = await delivery.deliver(
                    candidate.operation,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                self._clear_cleanup()
                reason = f"hot_tub_cleanup_delivery_exception:{type(exc).__name__}"
                return self._publish(
                    state=ThermalAutomaticDriverState.FAILED,
                    evaluated_at=frame.observed_at,
                    blocker=reason,
                    frame=frame,
                    body=None,
                    preflight=None,
                    failure=reason,
                    command_delivery_performed=False,
                )
        finally:
            self._delivery_in_flight = False
        if not receipt.accepted:
            self._clear_cleanup()
            reason = f"hot_tub_cleanup_delivery_{receipt.status.value}"
            return self._publish(
                state=ThermalAutomaticDriverState.FAILED,
                evaluated_at=frame.observed_at,
                blocker=reason,
                frame=frame,
                body=None,
                preflight=None,
                failure=reason,
                command_delivery_performed=False,
            )
        if self._retire_after_inflight or not self.requested_enabled or self._unloaded:
            self._retire_after_inflight = False
            self._clear_cleanup()
            return self._publish(
                state=(
                    ThermalAutomaticDriverState.UNLOADED
                    if self._unloaded
                    else ThermalAutomaticDriverState.DISABLED
                ),
                evaluated_at=frame.observed_at,
                blocker=(
                    "automatic_thermal_driver_unloaded"
                    if self._unloaded
                    else "automatic_thermal_driver_disabled"
                ),
                frame=frame,
                body=None,
                preflight=None,
                failure=None,
                command_delivery_performed=True,
            )
        self.cleanup_attempt = ThermalCirculationCleanupAttempt(
            candidate=candidate,
            correlation_id=correlation_id,
            receipt_id=receipt.command_id,
            delivered_at=frame.observed_at,
            deadline=frame.observed_at + frame.live_policy.verification_timeout,
        )
        self._accepted_delivery_count += 1
        self._last_accepted_correlation_id = correlation_id
        return self._publish(
            state=ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION,
            evaluated_at=frame.observed_at,
            blocker=None,
            frame=frame,
            body=None,
            preflight=None,
            failure=None,
            command_delivery_performed=True,
        )

    def _cleanup_verification(
        self,
        frame: ThermalAutomaticExecutionFrame,
        attempt: ThermalCirculationCleanupAttempt,
        assessment: CirculationSuccessorAssessment,
    ) -> str:
        """Verify an accepted cleanup command from later authoritative truth."""

        provenance = self.cleanup_provenance
        if provenance is None or frame.thermal is None:
            return "failed:thermal_cleanup_provenance_unavailable"
        body = frame.thermal.pool
        evidence = build_thermal_runtime_ownership_evidence(
            generated_at=frame.observed_at,
            observations={item.observation_id: item for item in frame.observations},
            body=body,
            external_changes=frame.external_changes,
        )
        outage = frame.orchestration.outage
        if (
            outage is None
            or outage.evaluated_at != frame.observed_at
            or outage.disposition is not GridOutageDisposition.ON_GRID
        ):
            return "failed:thermal_cleanup_grid_not_authoritatively_on"
        if (
            evidence.effective_heat_source is not PhysicalHeatMode.OFF
            or not evidence.heat_source_observation_fresh
            or not evidence.heat_source_observation_usable
        ):
            return "failed:thermal_cleanup_source_off_not_current"
        if (
            evidence.spa_active is not False
            or not evidence.spa_activity_fresh
            or not evidence.spa_activity_usable
        ):
            return "failed:thermal_cleanup_spa_topology_preempted"
        if not evidence.shared_hydraulic_inventory_complete:
            return "failed:thermal_cleanup_shared_hydraulic_evidence_incomplete"
        for item in evidence.shared_hydraulic_circuits:
            if item.active is None or not item.fresh or not item.usable:
                return "failed:thermal_cleanup_shared_hydraulic_evidence_unusable"
            if (
                item.active
                and item.safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING
            ):
                return "failed:thermal_cleanup_shared_hydraulic_takeover"
        if assessment.external_takeover:
            return "failed:thermal_cleanup_external_takeover"
        action = attempt.candidate.action
        if action is ThermalCirculationCleanupAction.BODY_DEACTIVATION:
            if (
                evidence.pool_active is None
                or not evidence.pool_activity_fresh
                or not evidence.pool_activity_usable
            ):
                return "failed:thermal_cleanup_pool_topology_preempted"
            if (
                evidence.pool_activity_observed_at is not None
                and evidence.pool_activity_observed_at > attempt.delivered_at
                and evidence.pool_active is False
            ):
                return "verified"
            if not assessment.body_deactivation_eligible:
                return "failed:thermal_cleanup_circulation_successor_changed"
            return "pending"

        filtration = frame.filtration_successor
        operation = attempt.candidate.operation
        assert isinstance(operation, SetPumpSpeed)
        if (
            filtration is None
            or filtration.evaluated_at != frame.observed_at
            or not filtration.immediate_circulation_required
            or filtration.successor_target_rpm != operation.rpm
        ):
            return "failed:thermal_cleanup_filtration_successor_changed"
        if (
            evidence.pool_active is not True
            or not evidence.pool_activity_fresh
            or not evidence.pool_activity_usable
        ):
            return "failed:thermal_cleanup_pool_topology_preempted"
        configured_verified = (
            evidence.configured_pump_speed_observed_at is not None
            and evidence.configured_pump_speed_observed_at > attempt.delivered_at
            and evidence.configured_pump_speed_observation_fresh
            and evidence.configured_pump_speed_observation_usable
            and evidence.configured_pump_speed_rpm == operation.rpm
        )
        actual_verified = (
            evidence.pump_observed_at is not None
            and evidence.pump_observed_at > attempt.delivered_at
            and evidence.pump_observation_fresh
            and evidence.pump_observation_usable
            and evidence.pump_rpm is not None
            and abs(evidence.pump_rpm - operation.rpm)
            <= self.circulation_arbitrator.pump_rpm_tolerance
        )
        return "verified" if configured_verified and actual_verified else "pending"

    def _clear_cleanup(self) -> None:
        self.cleanup_attempt = None
        self.cleanup_provenance = None

    def fail_closed(
        self,
        *,
        failed_at: datetime,
        reason: str,
    ) -> ThermalAutomaticDriverAssessment:
        """Invalidate stale candidate/session truth after adapter failure."""

        _require_aware(failed_at)
        self._clear_cleanup()
        self._probe_acquisition = None
        self.solar_engagement_attempt = None
        self._solar_nonengagement_cleanup_purpose_id = None
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
        self._clear_cleanup()
        self._probe_acquisition = None
        self.solar_engagement_attempt = None
        self._solar_nonengagement_cleanup_purpose_id = None
        self._cancel_filtration_handoff()
        self._retire_session(
            at=unloaded_at,
            reason="automatic_thermal_driver_unloaded",
        )
        self.termination_attempt = None
        self.orchestrator.ownership.invalidate_residual_termination()
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
                    "solar_engagement_observation_timeout_seconds": int(
                        self.solar_engagement_policy.observation_timeout.total_seconds()
                    ),
                    "solar_engagement_confirmation_hold_seconds": int(
                        self.solar_engagement_policy.confirmation_hold.total_seconds()
                    ),
                    "solar_retry_suppression_seconds": int(
                        self.solar_engagement_policy.retry_suppression.total_seconds()
                    ),
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
                "solar_engagement_observation_active": (
                    self.solar_engagement_attempt is not None
                ),
                "solar_retry_suppressed_until": (
                    None
                    if self._solar_suppressed_until is None
                    else self._solar_suppressed_until.isoformat()
                ),
                "solar_engagement_observation_timeout_seconds": int(
                    self.solar_engagement_policy.observation_timeout.total_seconds()
                ),
                "solar_engagement_confirmation_hold_seconds": int(
                    self.solar_engagement_policy.confirmation_hold.total_seconds()
                ),
                "solar_retry_suppression_seconds": int(
                    self.solar_engagement_policy.retry_suppression.total_seconds()
                ),
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
        if (
            session.originating_currentness.purpose.kind
            is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
            and ownership.body_activation_operation_id is None
        ):
            # Source-Off is a prerequisite, not proof that PoolOS owns
            # circulation. Keep its accepted provenance on the live session
            # until the body-activation operation is itself accepted.
            return None
        lease = self.orchestrator.ownership.state.lease
        if (
            lease is not None
            and lease.status is ThermalRuntimeOwnershipStatus.PREEMPTED
            and lease.execution_plan_id != ownership.execution_plan_id
        ):
            # PREEMPTED is terminal for the prior execution generation, not
            # for all future autonomous thermal work. A genuinely new live
            # execution may establish a fresh lease only from its own accepted
            # delivery provenance. ThermalRuntimeOwnershipManager.establish()
            # independently rejects provenance reuse and never copies prior
            # concept ownership into the successor generation.
            decision = self.orchestrator.ownership.establish(
                ownership,
                established_at=promoted_at,
                requested_mode=requested_mode,
                current_context=session.originating_context,
                execution_progress=session.execution_progress,
            )
        else:
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

    def _begin_probe_successor_handoff(
        self,
        frame: ThermalAutomaticExecutionFrame,
        *,
        body: ThermalBodyRuntimeAssessment,
        preflight: ThermalLiveStructuralPreflightResult,
    ) -> str | None:
        """Bind a fresh Pool thermal session while retaining only body provenance."""

        lease = self.orchestrator.ownership.state.lease
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease.originating_currentness is None
            or lease.originating_currentness.purpose.kind
            is not ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
            or body.body is not ThermalBody.POOL
        ):
            return "automatic_thermal_owned_successor_requires_explicit_handoff"
        if not preflight.eligible:
            return "automatic_thermal_plan_preflight_failed:" + ",".join(
                preflight.blocking_reasons
            )
        safety = body.live_safety_evidence
        if safety is None:
            return "automatic_thermal_live_safety_evidence_unavailable"
        try:
            successor = self.engine.begin(
                body.plan,
                policy=frame.live_policy,
                evidence=safety,
            )
        except ValueError as exc:
            return f"automatic_thermal_session_begin_failed:{_bounded(str(exc))}"
        request = ThermalRuntimeHandoffRequest(
            explicit=True,
            predecessor_lease_id=lease.lease_id,
            predecessor_generation=lease.generation,
            successor_context=successor.originating_context,
            successor_execution_plan_id=successor.execution_plan.plan_id,
            successor_body=body.body,
            successor_requested_mode=body.requested_mode.value,
            successor_requires_body_active=True,
            successor_required_pump_rpm=body.plan.desired.required_pump_rpm,
            successor_heat_source=body.plan.desired.selected_source,
            successor_progress=successor.execution_progress,
            replace_pump_setpoint=(
                lease.pump_setpoint is not None
                and lease.pump_setpoint.intended_value
                != body.plan.desired.required_pump_rpm
            ),
            replace_heat_source=(
                lease.heat_source is not None
                and lease.heat_source.intended_value
                is not body.plan.desired.selected_source
            ),
        )
        decision = self.orchestrator.ownership.handoff(
            request,
            build_thermal_runtime_ownership_evidence(
                generated_at=frame.observed_at,
                observations={item.observation_id: item for item in frame.observations},
                body=body,
                external_changes=frame.external_changes,
            ),
        )
        if decision.disposition is not ThermalRuntimeOwnershipDisposition.HANDED_OFF:
            return decision.reason_code
        self.active_session = successor
        self._probe_acquisition = None
        return None

    def _retire_session(self, *, at: datetime, reason: str) -> None:
        lease = self.orchestrator.ownership.state.lease
        if lease is not None and lease.status is ThermalRuntimeOwnershipStatus.OWNED:
            self.orchestrator.ownership.relinquish(
                lease_id=lease.lease_id,
                relinquished_at=at,
                reason_code=reason,
                retain_termination_entitlement=True,
            )
        self.active_session = None

    def _begin_verified_probe_acquisition(
        self,
        session: ThermalLiveExecutionSession,
        *,
        started_at: datetime,
    ) -> None:
        """Start acquisition only after verified PoolOS body activation."""

        purpose = session.originating_currentness.purpose
        if purpose.kind is not ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE:
            return
        lease = self.orchestrator.ownership.state.lease
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or not lease.owns_body_activation
            or not lease.owns_pump_setpoint
            or lease.pump_setpoint is None
            or lease.pump_setpoint.intended_value
            != self.baselines.temperature_probe_rpm
        ):
            return
        self._probe_acquisition = PoolTemperatureProbeExecutionEvidence(
            phase=PoolTemperatureProbeExecutionPhase.ACQUIRING,
            execution_purpose_id=purpose.purpose_id,
            execution_plan_id=lease.execution_plan_id,
            ownership_lease_id=lease.lease_id,
            ownership_generation=lease.generation,
            body_activation_owned=True,
            pump_setpoint_owned=True,
            acquisition_started_at=started_at,
        )

    def _begin_solar_engagement_observation(
        self,
        session: ThermalLiveExecutionSession,
        *,
        started_at: datetime,
    ) -> None:
        """Observe IntelliCenter engagement after exact H0002 verification."""

        purpose = session.originating_currentness.purpose
        if (
            purpose.kind is not ThermalExecutionPurposeKind.THERMAL_CONTROL
            or purpose.body is not ThermalBody.POOL
            or purpose.selected_source is not PhysicalHeatMode.SOLAR
        ):
            return
        lease = self.orchestrator.ownership.state.lease
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease.originating_currentness is None
            or lease.originating_currentness.purpose.purpose_id != purpose.purpose_id
            or not lease.owns_body_activation
            or not lease.owns_heat_source
        ):
            return
        self.solar_engagement_attempt = SolarEngagementAttempt(
            execution_purpose_id=purpose.purpose_id,
            ownership_lease_id=lease.lease_id,
            ownership_generation=lease.generation,
            started_at=started_at,
            deadline=started_at + self.solar_engagement_policy.observation_timeout,
        )

    def _process_solar_engagement(
        self,
        frame: ThermalAutomaticExecutionFrame,
    ) -> ThermalAutomaticDriverAssessment | None:
        """Advance bounded effectiveness observation; never verify H0002 here."""

        attempt = self.solar_engagement_attempt
        if attempt is None:
            return None
        lease = self.orchestrator.ownership.state.lease
        body = None if frame.thermal is None else frame.thermal.pool
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease.lease_id != attempt.ownership_lease_id
            or lease.generation != attempt.ownership_generation
            or lease.originating_currentness is None
            or lease.originating_currentness.purpose.purpose_id
            != attempt.execution_purpose_id
            or body is None
            or body.execution_currentness.purpose.purpose_id
            != attempt.execution_purpose_id
        ):
            self.solar_engagement_attempt = None
            return self._terminate_for_frame(
                frame,
                "automatic_thermal_solar_engagement_currentness_lost",
            )
        observation = next(
            (
                item
                for item in frame.observations
                if item.observation_id == "solar.active"
            ),
            None,
        )
        solar_active = _live_boolean_observation(
            observation,
            evaluated_at=frame.observed_at,
        )
        if solar_active is None and frame.observed_at < attempt.deadline:
            if attempt.engaged_since is not None:
                self.solar_engagement_attempt = replace(attempt, engaged_since=None)
            return self._publish(
                state=ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT,
                evaluated_at=frame.observed_at,
                blocker=(
                    "automatic_thermal_solar_engagement_evidence_unusable_pending"
                ),
                frame=frame,
                body=body,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )
        if solar_active is True:
            engaged_since = attempt.engaged_since or frame.observed_at
            if (
                frame.observed_at - engaged_since
                >= self.solar_engagement_policy.confirmation_hold
            ):
                self.solar_engagement_attempt = None
                return self._publish(
                    state=ThermalAutomaticDriverState.CONVERGED,
                    evaluated_at=frame.observed_at,
                    blocker="automatic_thermal_solar_engaged",
                    frame=frame,
                    body=body,
                    preflight=None,
                    failure=None,
                    command_delivery_performed=False,
                )
            self.solar_engagement_attempt = replace(
                attempt,
                engaged_since=engaged_since,
            )
        elif attempt.engaged_since is not None:
            self.solar_engagement_attempt = replace(attempt, engaged_since=None)
        if frame.observed_at >= attempt.deadline:
            self.solar_engagement_attempt = None
            self._solar_suppressed_purpose_id = attempt.execution_purpose_id
            self._solar_nonengagement_cleanup_purpose_id = (
                attempt.execution_purpose_id
            )
            self._solar_suppressed_until = (
                frame.observed_at + self.solar_engagement_policy.retry_suppression
            )
            self._retire_session(
                at=frame.observed_at,
                reason="automatic_thermal_solar_not_engaged",
            )
            return self._publish(
                state=ThermalAutomaticDriverState.TERMINATING,
                evaluated_at=frame.observed_at,
                blocker="automatic_thermal_solar_not_engaged",
                frame=frame,
                body=body,
                preflight=None,
                failure=None,
                command_delivery_performed=False,
            )
        return self._publish(
            state=ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT,
            evaluated_at=frame.observed_at,
            blocker="automatic_thermal_solar_engagement_observation_pending",
            frame=frame,
            body=body,
            preflight=None,
            failure=None,
            command_delivery_performed=False,
        )

    def _solar_retry_suppressed(
        self,
        body: ThermalBodyRuntimeAssessment,
        *,
        at: datetime,
    ) -> bool:
        """Suppress only the unchanged failed Solar opportunity purpose."""

        until = self._solar_suppressed_until
        purpose = body.execution_currentness.purpose
        if until is None or self._solar_suppressed_purpose_id is None:
            return False
        if at >= until or purpose.purpose_id != self._solar_suppressed_purpose_id:
            self._solar_suppressed_until = None
            self._solar_suppressed_purpose_id = None
            return False
        return purpose.selected_source is PhysicalHeatMode.SOLAR

    def _terminate_for_frame(
        self,
        frame: ThermalAutomaticExecutionFrame,
        reason: str,
    ) -> ThermalAutomaticDriverAssessment:
        if _terminal_execution_failure_requires_reenable(reason):
            self._reenable_required = True
        state = (
            ThermalAutomaticDriverState.SUPERSEDED
            if "supersed" in reason
            else (
                ThermalAutomaticDriverState.PREEMPTED
                if "preempt" in reason or "hydraulic" in reason or "grid" in reason
                else ThermalAutomaticDriverState.BLOCKED
            )
        )
        self._clear_cleanup()
        self._probe_acquisition = None
        self.solar_engagement_attempt = None
        self._solar_nonengagement_cleanup_purpose_id = None
        self._cancel_filtration_handoff()
        self._retire_session(at=frame.observed_at, reason=reason)
        if state is ThermalAutomaticDriverState.PREEMPTED:
            self.circulation_ownership.release_thermal()
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

    def _cancel_filtration_handoff(self) -> None:
        handoff = self._filtration_handoff
        if handoff is None:
            return
        self.circulation_ownership.cancel_filtration_to_thermal(
            token_id=handoff.token_id,
        )
        self._filtration_handoff = None

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
        circulation_assessment: CirculationSuccessorAssessment | None = None,
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
        residual = self.orchestrator.ownership.residual_termination
        terminal_transition = self.orchestrator.ownership.last_terminal_transition
        accepted_current = (
            None
            if lease is None or lease.execution_progress is None
            else lease.execution_progress.accepted_current
        )
        termination = None if frame is None else self._termination_assessment(frame)
        circulation = circulation_assessment
        if circulation is None and frame is not None:
            circulation = self._circulation_assessment(frame)
        ownership_summary: dict[str, object] = {
            "body": None if lease is None else lease.body.value,
            "owns_body_activation": bool(lease and lease.owns_body_activation),
            "owns_pump_setpoint": bool(lease and lease.owns_pump_setpoint),
            "owns_heat_source": bool(lease and lease.owns_heat_source),
            "verified_owned_concepts": (
                []
                if lease is None
                else [concept.value for concept in lease.verified_concepts]
            ),
            "accepted_consequence_pending_role": (
                None if accepted_current is None else accepted_current.role
            ),
            "accepted_consequence_pending_equipment_id": (
                None if accepted_current is None else accepted_current.equipment_id
            ),
            "accepted_consequence_pending_value": (
                None if accepted_current is None else accepted_current.requested_value
            ),
            "ownership_ended_at": (
                None
                if lease is None or lease.ended_at is None
                else lease.ended_at.isoformat()
            ),
            "terminal_transition_prior_status": (
                None
                if terminal_transition is None
                else terminal_transition.previous_status.value
            ),
            "terminal_transition_current_status": (
                None
                if terminal_transition is None
                else terminal_transition.current_status.value
            ),
            "terminal_transition_at": (
                None
                if terminal_transition is None
                else terminal_transition.occurred_at.isoformat()
            ),
            "terminal_transition_reason_code": (
                None if terminal_transition is None else terminal_transition.reason_code
            ),
            "terminal_transition_affected_concept": (
                None
                if terminal_transition is None
                or terminal_transition.affected_concept is None
                else terminal_transition.affected_concept.value
            ),
            "terminal_transition_expected_value": (
                None if terminal_transition is None else terminal_transition.expected_value
            ),
            "terminal_transition_observed_value": (
                None if terminal_transition is None else terminal_transition.observed_value
            ),
            "terminal_transition_observed_at": (
                None
                if terminal_transition is None
                or terminal_transition.observed_at is None
                else terminal_transition.observed_at.isoformat()
            ),
            "terminal_transition_operation_id": (
                None if terminal_transition is None else terminal_transition.operation_id
            ),
            "terminal_transition_correlation_id": (
                None
                if terminal_transition is None
                else terminal_transition.correlation_id
            ),
            "terminal_transition_accepted_at": (
                None
                if terminal_transition is None
                or terminal_transition.accepted_at is None
                else terminal_transition.accepted_at.isoformat()
            ),
            "terminal_transition_execution_purpose_id": (
                None
                if terminal_transition is None
                else terminal_transition.execution_purpose_id
            ),
            "terminal_transition_currentness_disposition": (
                None
                if terminal_transition is None
                else terminal_transition.currentness_disposition
            ),
            "terminal_transition_external_event_id": (
                None
                if terminal_transition is None
                else terminal_transition.external_event_id
            ),
            "terminal_transition_external_event_concept": (
                None
                if terminal_transition is None
                else terminal_transition.external_event_concept
            ),
            "terminal_transition_external_event_observed_at": (
                None
                if terminal_transition is None
                or terminal_transition.external_event_observed_at is None
                else terminal_transition.external_event_observed_at.isoformat()
            ),
            "reason_code": self.orchestrator.ownership.state.reason_code,
            "automatic_thermal_reenable_required": self._reenable_required,
            "residual_termination_entitlement_id": (
                None if residual is None else residual.entitlement_id
            ),
            "residual_termination_generation": (
                None if residual is None else residual.generation
            ),
            "residual_owned_concepts": (
                []
                if residual is None
                else [item.value for item in residual.owned_concepts]
            ),
            "termination_disposition": (
                None if termination is None else termination.disposition.value
            ),
            "termination_reason_code": (
                None if termination is None else termination.reason_code
            ),
            "termination_source_action": (
                None if termination is None else termination.source_action.value
            ),
            "termination_pump_action": (
                None if termination is None else termination.pump_action.value
            ),
            "termination_body_action": (
                None if termination is None else termination.body_action.value
            ),
            "termination_awaiting_verification": self.termination_attempt is not None,
            "circulation_cleanup_provenance_id": (
                None
                if self.cleanup_provenance is None
                else self.cleanup_provenance.provenance_id
            ),
            "circulation_cleanup_body_provenance_present": bool(
                self.cleanup_provenance
                and self.cleanup_provenance.body_activation is not None
            ),
            "circulation_cleanup_pump_provenance_present": bool(
                self.cleanup_provenance
                and self.cleanup_provenance.pump_setpoint is not None
            ),
            "circulation_cleanup_awaiting_verification": self.cleanup_attempt is not None,
            "circulation_cleanup_action": (
                None
                if self.cleanup_attempt is None
                else self.cleanup_attempt.candidate.action.value
            ),
            "circulation_cleanup_target_rpm": (
                self.cleanup_attempt.candidate.operation.rpm
                if self.cleanup_attempt is not None
                and isinstance(self.cleanup_attempt.candidate.operation, SetPumpSpeed)
                else None
            ),
            "body_deactivation_authorized": bool(
                self.cleanup_attempt
                and self.cleanup_attempt.candidate.action
                is ThermalCirculationCleanupAction.BODY_DEACTIVATION
            ),
            "filtration_pump_normalization_authorized": bool(
                self.cleanup_attempt
                and self.cleanup_attempt.candidate.action
                is ThermalCirculationCleanupAction.FILTRATION_PUMP_NORMALIZATION
            ),
            "stop_pump_authorized": False,
        }
        probe = self.probe_execution_evidence()
        ownership_summary.update(
            {
                "pool_temperature_probe_phase": (
                    None if probe is None else probe.phase.value
                ),
                "pool_temperature_probe_ownership_present": probe is not None,
                "pool_temperature_probe_body_provenance_present": bool(
                    probe and probe.body_activation_owned
                ),
                "pool_temperature_probe_pump_provenance_present": bool(
                    probe and probe.pump_setpoint_owned
                ),
                "pool_temperature_probe_acquisition_started_at": (
                    None
                    if probe is None or probe.acquisition_started_at is None
                    else probe.acquisition_started_at.isoformat()
                ),
                "solar_engagement_observation_active": (
                    self.solar_engagement_attempt is not None
                ),
                "solar_engagement_observation_deadline": (
                    None
                    if self.solar_engagement_attempt is None
                    else self.solar_engagement_attempt.deadline.isoformat()
                ),
                "solar_retry_suppressed_until": (
                    None
                    if self._solar_suppressed_until is None
                    else self._solar_suppressed_until.isoformat()
                ),
            }
        )
        if circulation is not None:
            ownership_summary.update(circulation.diagnostics())
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
                (
                    session is not None
                    and session.status
                    is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
                )
                or self.cleanup_attempt is not None
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


def _restrained_body(
    driver: ThermalAutomaticExecutionDriver,
    frame: ThermalAutomaticExecutionFrame,
) -> ThermalBody | None:
    """Return only the body tied to current in-memory automatic provenance."""

    if driver.active_session is not None:
        return driver.active_session.assessment.desired.body
    if driver.cleanup_provenance is not None:
        return driver.cleanup_provenance.body
    lease = driver.orchestrator.ownership.state.lease
    if lease is not None:
        return lease.body
    return frame.orchestration.candidate_body


def _probe_source_precondition_then_activation(
    body: ThermalBodyRuntimeAssessment,
) -> bool:
    """Recognize only the canonical source-Off, Pool-On, 1500-RPM plan."""

    operations = body.plan.operations
    specifications = body.plan.step_specifications
    return bool(
        body.body is ThermalBody.POOL
        and body.plan.desired.reason_code == "pool_temperature_probe_required"
        and len(operations) == 3
        and len(specifications) == 3
        and isinstance(operations[0], SetHeatMode)
        and operations[0].equipment_id == ThermalBody.POOL.value
        and operations[0].mode is PhysicalHeatMode.OFF
        and specifications[0].operation_id == operations[0].operation_id
        and specifications[0].metadata.get(
            "pool_temperature_probe_source_precondition"
        )
        == "true"
        and isinstance(operations[1], SetBodyActive)
        and operations[1].equipment_id == ThermalBody.POOL.value
        and operations[1].active is True
        and isinstance(operations[2], SetPumpSpeed)
        and operations[2].equipment_id == body.pump_circuit_id
        and operations[2].rpm == body.plan.desired.required_pump_rpm
        and operations[2].metadata.get("reason_code")
        == "pool_temperature_probe_required"
        and operations[2].metadata.get("operating_purpose")
        == "temperature_acquisition"
        and specifications[2].operation_id == operations[2].operation_id
        and specifications[2].metadata.get("pool_temperature_probe_step") == "true"
    )


def _bounded(value: str, limit: int = 256) -> str:
    return " ".join(value.split())[:limit]


def _terminal_execution_failure_requires_reenable(reason: str) -> bool:
    """Prevent automatic replay after a command or verification failure."""

    return (
        reason.startswith("delivery_")
        or reason.startswith("automatic_thermal_delivery")
        or "verification_deadline_reached" in reason
        or "verification_failed" in reason
    )


def _live_boolean_observation(
    observation: PoolObservation | None,
    *,
    evaluated_at: datetime,
) -> bool | None:
    """Return exact live boolean truth under the execution-verification contract."""

    if (
        observation is None
        or observation.source_kind is not ObservationSourceKind.LIVE
        or observation.quality
        not in {ObservationQuality.GOOD, ObservationQuality.DEGRADED}
        or observation.confidence < 0.5
        or not isinstance(observation.value, bool)
    ):
        return None
    freshness = observation.freshness(
        clock=FixedClock(evaluated_at),
        policy=FreshnessPolicy(max_age=timedelta(seconds=30)),
    )
    if freshness is not ObservationFreshness.FRESH:
        return None
    return observation.value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("automatic thermal timestamp must be timezone-aware")


__all__ = [
    "SolarEngagementAttempt",
    "SolarEngagementPolicy",
    "ThermalAutomaticDeliveryFactory",
    "ThermalAutomaticDriverAssessment",
    "ThermalAutomaticDriverState",
    "ThermalAutomaticExecutionDriver",
    "ThermalAutomaticExecutionFrame",
]
