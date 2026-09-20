"""Home Assistant lifecycle bridge for default-off automatic thermal execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging

from homeassistant.core import HomeAssistant

from poolos.physical_command_authority import (
    AutomaticThermalDispatchPurpose,
    PhysicalAuthorityReason,
    PhysicalRequestSource,
    PhysicalCommandRequest,
    PoolOSPhysicalCommandAuthority,
)
from poolos.circulation_successor import FiltrationSuccessorEvidence
from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from poolos.external_change import ExternalChangeBatch
from poolos.ownership_evidence import OwnershipAuthority, OwnershipDomain, PositiveOperatorEvidence
from poolos.pool_circulation_ownership import PoolCirculationOwner, PoolCirculationOwnershipRegistry
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_speed_session import PumpSpeedSessionPurpose, PumpSpeedSessionRuntime
from poolos.pool_temperature_probe_execution import PoolTemperatureProbeExecutionPhase
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    SpaAutomaticControlSuppression,
)
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDeliveryFactory,
    ThermalAutomaticExecutionDriver,
    ThermalAutomaticExecutionFrame,
    filtration_source_off_precondition,
)
from poolos.thermal_circulation_cleanup import (
    ThermalCirculationCleanupAction,
    ThermalCirculationCleanupCandidate,
)
from poolos.thermal_live_execution import (
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
)
from poolos.thermal_execution_currentness import ThermalExecutionPurposeKind
from poolos.thermal_runtime_assessment import ThermalRuntimeAssessment
from poolos.thermal_runtime_orchestration import (
    ThermalRuntimeOrchestrationAssessment,
    ThermalRuntimeOrchestrator,
)
from poolos.thermal_runtime_ownership import (
    ThermalQuickRestartCheckpoint,
    ThermalRuntimeOwnershipDisposition,
)

from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterControl
from .observation import ObservationSnapshot
from .pump_speed_session import PoolOSPumpSpeedSessionRuntime
from .thermal_live_delivery import ManualIntelliCenterThermalLiveDelivery
from .thermal_runtime import PoolOSThermalRuntime


LOGGER = logging.getLogger(__name__)
_OWNED_PUMP_SESSION_REOBSERVATION_INTERVAL_SECONDS = 15.0



@dataclass(frozen=True, slots=True)
class _ManualDeliveryFactory(ThermalAutomaticDeliveryFactory):
    manual: ManualIntelliCenterControl
    authority: PoolOSPhysicalCommandAuthority
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    pump_speed_session: PumpSpeedSessionRuntime | None = None

    def for_session(
        self,
        session: ThermalLiveExecutionSession,
        *,
        epoch_identity: str,
    ) -> ManualIntelliCenterThermalLiveDelivery:
        purpose = AutomaticThermalDispatchPurpose.NORMAL
        probe_operation_id = None
        pump_targets = {
            operation.equipment_id
            for operation in session.assessment.operations
            if isinstance(operation, SetPumpSpeed)
        }
        if len(pump_targets) > 1:
            raise ValueError("thermal plan contains conflicting pump identities")
        pump_circuit_id = next(iter(pump_targets), None)
        operating_purpose = None
        current_sequence = session.coordination.current_step_sequence
        if current_sequence is not None:
            current_operation = session.execution_plan.steps[
                current_sequence - 1
            ].operation
            if isinstance(current_operation, SetPumpSpeed):
                purpose_value = current_operation.metadata.get("operating_purpose")
                if isinstance(purpose_value, str) and purpose_value:
                    operating_purpose = purpose_value
                elif current_operation.metadata.get("priming_step") == "true":
                    operating_purpose = "priming"
        currentness = session.originating_currentness
        if currentness.purpose.kind is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE:
            sequence = session.coordination.current_step_sequence
            if sequence is None:
                raise ValueError("probe session has no current operation")
            step = session.execution_plan.steps[sequence - 1]
            operation = step.operation
            purpose = AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE
            if isinstance(operation, SetBodyActive):
                operation_name = "body_active"
                authority_target = "B1101"
                requested_value: bool | int | str = operation.active
            elif isinstance(operation, SetPumpSpeed):
                operation_name = "pump_circuit_speed"
                authority_target = operation.equipment_id
                requested_value = operation.rpm
            elif isinstance(operation, SetHeatMode):
                operation_name = "body_heat_source"
                authority_target = "B1101"
                requested_value = {
                    PhysicalHeatMode.OFF: "00000",
                    PhysicalHeatMode.GAS: "H0001",
                    PhysicalHeatMode.SOLAR: "H0002",
                }[operation.mode]
            else:
                raise ValueError("unsupported Pool temperature-probe operation")
            self.authority.register_automatic_thermal_probe(
                epoch_identity=epoch_identity,
                operation_id=operation.operation_id,
                operation=operation_name,
                target=authority_target,
                requested_value=requested_value,
            )
            probe_operation_id = operation.operation_id
        pump_session_id = None
        effective_pump_rpm = None
        if self.pump_speed_session is not None and operating_purpose is not None:
            pump_state = self.pump_speed_session.snapshot
            if (
                pump_state.active
                and pump_state.body is not None
                and pump_state.body.value == session.assessment.desired.body.value
                and pump_state.purpose is not None
                and pump_state.purpose.value == operating_purpose
                and pump_state.pump_circuit_id == pump_circuit_id
            ):
                pump_session_id = pump_state.session_id
                effective_pump_rpm = pump_state.effective_rpm
        context = self.authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch_identity,
            session_identity=session.execution_plan.plan_id,
            body=session.assessment.desired.body.value,
            pump_circuit_id=pump_circuit_id,
            operating_purpose=operating_purpose,
            purpose=purpose,
            probe_operation_id=probe_operation_id,
            pump_session_id=pump_session_id,
            effective_pump_rpm=effective_pump_rpm,
        )
        return ManualIntelliCenterThermalLiveDelivery(
            manual=self.manual,
            baselines=self.baselines,
            request_source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            automatic_thermal_context=context,
        )

    def for_termination(
        self,
        *,
        body: ThermalBody,
        entitlement_id: str,
        epoch_identity: str,
    ) -> ManualIntelliCenterThermalLiveDelivery:
        """Bind one residual source-Off request to the current authority epoch."""

        context = self.authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch_identity,
            session_identity=f"termination:{entitlement_id}",
            body=body.value,
            purpose=AutomaticThermalDispatchPurpose.TERMINATION,
        )
        return ManualIntelliCenterThermalLiveDelivery(
            manual=self.manual,
            baselines=self.baselines,
            request_source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            automatic_thermal_context=context,
        )

    def for_cleanup(
        self,
        candidate: ThermalCirculationCleanupCandidate,
        *,
        epoch_identity: str,
    ) -> ManualIntelliCenterThermalLiveDelivery:
        """Bind exactly one canonical cleanup candidate to this authority epoch."""

        operation = candidate.operation
        cleanup_body = ThermalBody.POOL
        if candidate.action is ThermalCirculationCleanupAction.BODY_DEACTIVATION:
            assert isinstance(operation, SetBodyActive)
            purpose = AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP
            physical_operation = "body_active"
            cleanup_body = ThermalBody(operation.equipment_id)
            target = "B1101" if cleanup_body is ThermalBody.POOL else "B1202"
            value: bool | int = operation.active
        else:
            assert isinstance(operation, SetPumpSpeed)
            purpose = AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION
            physical_operation = "pump_circuit_speed"
            target = operation.equipment_id
            value = operation.rpm
        self.authority.register_automatic_thermal_cleanup(
            epoch_identity=epoch_identity,
            candidate_identity=candidate.candidate_id,
            body=cleanup_body.value,
            purpose=purpose,
            operation=physical_operation,
            target=target,
            requested_value=value,
        )
        context = self.authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch_identity,
            session_identity=f"cleanup:{candidate.provenance_id}",
            body=cleanup_body.value,
            pump_circuit_id=(
                operation.equipment_id
                if isinstance(operation, SetPumpSpeed)
                else None
            ),
            purpose=purpose,
            cleanup_candidate_identity=candidate.candidate_id,
        )
        return ManualIntelliCenterThermalLiveDelivery(
            manual=self.manual,
            baselines=self.baselines,
            request_source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            automatic_thermal_context=context,
        )


@dataclass(slots=True)
class PoolOSThermalAutomaticRuntime:
    """Own one event-driven automatic driver instance per config entry."""

    hass: HomeAssistant
    coordinator: PoolOSCoordinator
    thermal_runtime: PoolOSThermalRuntime
    orchestrator: ThermalRuntimeOrchestrator
    authority: PoolOSPhysicalCommandAuthority
    manual: ManualIntelliCenterControl | None
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    pump_speed_session: PoolOSPumpSpeedSessionRuntime | None = None
    pool_automatic_control: PoolAutomaticControlSuppression = field(
        default_factory=PoolAutomaticControlSuppression
    )
    spa_automatic_control: SpaAutomaticControlSuppression = field(
        default_factory=SpaAutomaticControlSuppression
    )
    circulation_ownership: PoolCirculationOwnershipRegistry = field(
        default_factory=PoolCirculationOwnershipRegistry
    )
    driver: ThermalAutomaticExecutionDriver = field(init=False)
    _latest_frame: ThermalAutomaticExecutionFrame | None = field(
        default=None, init=False, repr=False
    )
    _task: asyncio.Task[object] | None = field(default=None, init=False, repr=False)
    _owned_pump_session_reobservation_task: asyncio.Task[object] | None = field(
        default=None, init=False, repr=False
    )
    _cleanup_topology_reobservation_task: asyncio.Task[object] | None = field(
        default=None, init=False, repr=False
    )
    _cleanup_topology_reobservation_provenance_id: str | None = field(
        default=None, init=False, repr=False
    )
    _unloaded: bool = field(default=False, init=False, repr=False)
    _desired_enabled: bool = field(default=False, init=False, repr=False)
    _restart_checkpoint: ThermalQuickRestartCheckpoint | None = field(
        default=None, init=False, repr=False
    )
    _restart_recovery_max_age: timedelta = field(
        default=timedelta(minutes=5), init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.driver = ThermalAutomaticExecutionDriver(
            self.orchestrator,
            baselines=self.baselines,
            circulation_ownership=self.circulation_ownership,
        )
        self._sync_authority_configuration()

        self.authority.ownership_permission_reader = self._domain_command_permitted
        self.authority.operator_request_listener = self._record_operator_request

    def _request_domain(self, request: PhysicalCommandRequest) -> OwnershipDomain | None:
        filtration = self.circulation_ownership.filtration_lease
        if filtration is not None and self.circulation_ownership.owner in {
            PoolCirculationOwner.FILTRATION, PoolCirculationOwner.FILTRATION_ACQUIRING,
            PoolCirculationOwner.FILTRATION_SUSPENDED,
            PoolCirculationOwner.FILTRATION_TO_THERMAL,
        }:
            if request.operation == "pump_circuit_speed" and request.target == filtration.pool_pump_circuit_id:
                return OwnershipDomain.PUMP
            if request.target == "B1101":
                return {"body_active": OwnershipDomain.BODY,
                        "body_heat_source": OwnershipDomain.THERMAL}.get(request.operation)
            return None
        lease = self.orchestrator.ownership.state.lease
        if lease is None:
            return None
        body_id = "B1101" if lease.body is ThermalBody.POOL else "B1202"
        if request.operation == "pump_circuit_speed":
            pump_session = (
                None
                if self.pump_speed_session is None
                else self.pump_speed_session.session.snapshot
            )
            if (
                pump_session is not None
                and pump_session.active
                and pump_session.body is not None
                and pump_session.body.value == lease.body.value
                and pump_session.pump_circuit_id == request.target
            ):
                return OwnershipDomain.PUMP
            currentness = lease.originating_currentness
            pump_ids = set() if currentness is None else {
                operation.equipment_id for operation in currentness.residual_plan.operations
                if operation.operation_type == "SetPumpSpeed"
            }
            return OwnershipDomain.PUMP if pump_ids == {request.target} else None
        if request.target != body_id:
            return None
        return {"body_active": OwnershipDomain.BODY,
                "body_heat_source": OwnershipDomain.THERMAL}.get(request.operation)

    def _domain_command_permitted(self, request: PhysicalCommandRequest) -> bool:
        context = request.automatic_thermal_context
        if request.source is PhysicalRequestSource.AUTOMATIC_FILTRATION:
            if self.pool_automatic_control.blocks_opportunity("filtration"):
                return False
        elif request.source is PhysicalRequestSource.AUTOMATIC_THERMAL:
            if context is not None and context.body == "pool":
                frame = self._latest_frame
                filtration_precondition = bool(
                    frame is not None and frame.thermal is not None
                    and filtration_source_off_precondition(frame.thermal.pool)
                    and request.operation == "body_heat_source"
                    and request.target == "B1101" and request.requested_value == "00000"
                )
                family = "filtration" if filtration_precondition else "thermal"
                if self.pool_automatic_control.blocks_opportunity(family):
                    return False
        elif (request.source is PhysicalRequestSource.RECONCILIATION
              and self.pool_automatic_control.state.suppressed):
            # A generic reconciliation request has no independent-purpose proof.
            return False
        domain = self._request_domain(request)
        lease = self.orchestrator.ownership.state.lease
        if lease is not None and domain is OwnershipDomain.BODY and request.requested_value is False:
            source = lease.domain_state(OwnershipDomain.THERMAL)
            if source.authority is OwnershipAuthority.OPERATOR:
                operator = source.positive_operator_evidence
                frame = self._latest_frame
                concept = "pool.raw_heater_id" if lease.body is ThermalBody.POOL else "spa.raw_heater_id"
                observation = next((item for item in frame.observations
                                    if item.observation_id == concept), None) if frame else None
                if (operator is None or observation is None
                    or observation.observed_at is None
                    or observation.observed_at <= operator.requested_at
                    or observation.value != "00000"):
                    return False
        if lease is not None and domain is OwnershipDomain.THERMAL and request.requested_value != "00000":
            pump = lease.domain_state(OwnershipDomain.PUMP)
            if pump.authority is OwnershipAuthority.OPERATOR:
                # Energizing a source needs newly reviewed flow evidence; an
                # operator speed request cannot inherit an older pump proof.
                # Source Off remains eligible through its independent gate.
                return False
        if domain is not None and self.circulation_ownership.filtration_lease is not None:
            return self.circulation_ownership.domain_permission_blocker(domain) is None
        context = request.automatic_thermal_context
        reduction = bool(context is not None and context.purpose in {
            AutomaticThermalDispatchPurpose.TERMINATION,
            AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        })
        return domain is None or self.orchestrator.ownership.domain_permission_blocker(
            domain, completion_reduction=reduction,
        ) is None

    def _record_operator_request(self, request: PhysicalCommandRequest, at: datetime) -> None:
        domain = self._request_domain(request)
        filtration = self.circulation_ownership.filtration_lease
        if domain is not None and filtration is not None:
            self.circulation_ownership.record_operator_intent(PositiveOperatorEvidence(
                request.request_id,
                filtration.body_session_generation or filtration.generation,
                filtration.body_session_id or filtration.session_id,
                domain, request.target, at,
            ), evaluated_at=at)
            return
        lease = self.orchestrator.ownership.state.lease
        if domain is None or lease is None:
            return
        assert lease.body_session_id is not None and lease.body_session_generation is not None
        equipment = (
            lease.body.value if domain is OwnershipDomain.BODY else "pump.rpm"
            if domain is OwnershipDomain.PUMP else
            f"{'pool' if lease.body is ThermalBody.POOL else 'spa'}.raw_heater_id"
        )
        self.orchestrator.ownership.record_operator_intent(PositiveOperatorEvidence(
            request.request_id, lease.body_session_generation, lease.body_session_id,
            domain, equipment, at,
        ), evaluated_at=at)

    def arm_quick_restart_recovery(
        self,
        checkpoint: ThermalQuickRestartCheckpoint,
    ) -> None:
        """Arm one command-free recovery attempt for a persisted lease."""

        self._restart_checkpoint = checkpoint

    @property
    def quick_restart_recovery_armed(self) -> bool:
        return self._restart_checkpoint is not None

    def quick_restart_restore_payload(self) -> dict[str, object] | None:
        """Return the latest safely persisted stable thermal checkpoint."""

        lease = self.orchestrator.ownership.state.lease
        if lease is None:
            return None
        checkpoint = self.orchestrator.ownership.export_restart_checkpoint(
            captured_at=lease.last_confirmed_at
        )
        return (
            None
            if checkpoint is None
            else checkpoint.to_restore_state()
        )

    @property
    def enabled(self) -> bool:
        return self._desired_enabled

    def set_enabled(self, enabled: bool) -> None:
        """Change the commissioned desired gate without replaying cached work."""

        enabled = bool(enabled)
        self._desired_enabled = enabled
        now = datetime.now(UTC)
        current = (
            None if self._latest_frame is None else self._latest_frame.epoch_identity
        )
        self.driver.set_enabled(
            enabled,
            changed_at=now,
            current_epoch_identity=current,
        )
        self._sync_authority_configuration()
        if not enabled:
            self._cancel_owned_pump_session_reobservation()
        self.coordinator.async_update_listeners()

    def authority_configuration_changed(self) -> None:
        """Invalidate queued work when Thermal Live or scope changes."""

        self._sync_authority_configuration()
        self.driver.restrictive_authority_changed(changed_at=datetime.now(UTC))
        self.coordinator.async_update_listeners()

    def observe(
        self,
        snapshot: ObservationSnapshot,
        thermal: ThermalRuntimeAssessment | None,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        external_changes: ExternalChangeBatch = ExternalChangeBatch(()),
    ) -> None:
        """Accept one serialized authoritative frame and schedule at most once."""

        if self._unloaded:
            return
        eligible = None
        if (thermal is not None and thermal.generated_at == snapshot.generated_at
                and not thermal.pool.evidence_blockers):
            purpose = thermal.pool.execution_currentness.purpose
            eligible = (purpose.kind is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
                        or purpose.selected_source is not PhysicalHeatMode.OFF)
        self.pool_automatic_control.observe_opportunity(
            "thermal", eligible=eligible, observed_at=snapshot.generated_at,
        )
        reason = self.authority.base_authority_reason
        ready = reason is PhysicalAuthorityReason.ALLOWED
        pump_session = (
            None
            if self.pump_speed_session is None
            else self.pump_speed_session.session.snapshot
        )
        frame = ThermalAutomaticExecutionFrame(
            epoch_identity=orchestration.snapshot_identity,
            observed_at=snapshot.generated_at,
            observations=tuple(snapshot.observations),
            thermal=thermal,
            orchestration=orchestration,
            live_policy=ThermalLiveExecutionPolicy(
                thermal_live_execution_enabled=(
                    self.thermal_runtime.effective_live_enabled
                ),
                commissioning_scope=self.thermal_runtime.commissioning_scope,
                baselines=self.baselines,
                pump_session_id=(
                    None if pump_session is None else pump_session.session_id
                ),
                pump_session_body=(
                    None
                    if pump_session is None or pump_session.body is None
                    else pump_session.body.value
                ),
                pump_session_purpose=(
                    None
                    if pump_session is None or pump_session.purpose is None
                    else pump_session.purpose.value
                ),
                pump_session_pump_circuit_id=(
                    None if pump_session is None else pump_session.pump_circuit_id
                ),
                pump_session_effective_rpm=(
                    None if pump_session is None else pump_session.effective_rpm
                ),
            ),
            physical_authority_ready=ready,
            physical_authority_blocker=(
                None if ready else f"physical_authority:{reason.value}"
            ),
            filtration_successor=(
                None
                if getattr(self.thermal_runtime, "filtration_runtime", None) is None
                or self.thermal_runtime.filtration_runtime.assessment is None
                else FiltrationSuccessorEvidence.from_accounting(
                    self.thermal_runtime.filtration_runtime.assessment
                )
            ),
            external_changes=external_changes,
            pool_opportunity_id=self.pool_automatic_control.opportunity_id(
                "filtration" if thermal is not None
                and filtration_source_off_precondition(thermal.pool) else "thermal"
            ),
            pool_automatic_control_suppressed=(
                self.pool_automatic_control.blocks_opportunity(
                    "filtration" if thermal is not None
                    and filtration_source_off_precondition(thermal.pool) else "thermal"
                )
            ),
            spa_automatic_control_suppressed=(
                self.spa_automatic_control.state.suppressed
            ),
        )
        if (
            self._latest_frame is not None
            and self._latest_frame.epoch_identity == frame.epoch_identity
        ):
            return
        self._latest_frame = frame
        self.circulation_ownership.begin_epoch(frame.epoch_identity)
        self.authority.begin_automatic_thermal_epoch(frame.epoch_identity)

        checkpoint = self._restart_checkpoint
        restart_authority_pending = reason in {
            PhysicalAuthorityReason.AUTHORITY_UNRESOLVED,
            PhysicalAuthorityReason.CONTROLLER_MODE_UNRESOLVED,
        }
        if (
            checkpoint is not None
            and self.driver.requested_enabled
            and thermal is not None
            and thermal.generated_at == snapshot.generated_at
        ):
            if restart_authority_pending:
                # Startup restoration is asynchronous.  Do not spend the
                # one-shot restart checkpoint while Maintenance/controller
                # authority is still unresolved; that is not yet an
                # authoritative recovery epoch.
                self.coordinator.async_update_listeners()
                return
            observations = {
                item.observation_id: item
                for item in snapshot.observations
            }
            decision = self.orchestrator.restore_quick_restart(
                checkpoint,
                generated_at=snapshot.generated_at,
                observations=observations,
                thermal=thermal,
                external_changes=external_changes,
                max_age=self._restart_recovery_max_age,
            )
            # One authoritative attempt only.  A denial falls back to normal
            # fail-closed startup behavior; it never retries equality later.
            self._restart_checkpoint = None

            if (
                decision.disposition
                is ThermalRuntimeOwnershipDisposition.ESTABLISHED
            ):
                lease = self.orchestrator.ownership.state.lease
                assert lease is not None
                self.circulation_ownership.mark_thermal_owned(
                    lease.lease_id
                )

                # Recovery itself is command-free.  Do not reserve, authorize,
                # or schedule automatic delivery on the restoration epoch.
                self.coordinator.async_update_listeners()
                return

        reserve = getattr(self.driver, "reserve_circulation_candidate", None)
        if reserve is not None:
            reserve(frame)
        if not self.driver.requested_enabled:
            self.driver.note_disabled_epoch(frame)
            self.coordinator.async_update_listeners()
            return
        self._schedule_if_idle()

    def orchestration_failed(self, snapshot: ObservationSnapshot, error: Exception) -> None:
        """Invalidate automatic readiness without suppressing native publication."""

        if self._unloaded:
            return
        self.authority.begin_automatic_thermal_epoch(
            f"failed:{snapshot.generated_at.isoformat()}:{type(error).__name__}"
        )
        self.driver.fail_closed(
            failed_at=snapshot.generated_at,
            reason=f"automatic_thermal_orchestration_failed:{type(error).__name__}",
        )
        self.coordinator.async_update_listeners()

    async def async_unload(self) -> None:
        """Make late work inert, then retain any already-accepted receipt."""

        if self._unloaded:
            return
        self._unloaded = True
        self.authority.ownership_permission_reader = None
        self.authority.operator_request_listener = None
        now = datetime.now(UTC)
        self.authority.unload_automatic_thermal_driver()
        self.driver.unload(unloaded_at=now)
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception(
                    "PoolOS automatic thermal task failed during command-free unload"
                )
        self._task = None
        probe_task = self._owned_pump_session_reobservation_task
        if probe_task is not None and not probe_task.done():
            probe_task.cancel()
            await asyncio.gather(probe_task, return_exceptions=True)
        self._owned_pump_session_reobservation_task = None
        cleanup_task = self._cleanup_topology_reobservation_task
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        self._cleanup_topology_reobservation_task = None

    def diagnostics(self) -> dict[str, object]:
        return {
            **dict(self.driver.diagnostics()),
            **dict(self.pool_automatic_control.diagnostics()),
            **dict(self.spa_automatic_control.diagnostics()),
        }

    def _sync_authority_configuration(self) -> None:
        scope = self.thermal_runtime.commissioning_scope
        self.authority.configure_automatic_thermal(
            driver_enabled=self.driver.requested_enabled,
            thermal_live_enabled=self.thermal_runtime.effective_live_enabled,
            commissioning_scope=scope.value,
        )

    def _cancel_owned_pump_session_reobservation(self) -> None:
        task = self._owned_pump_session_reobservation_task
        if task is not None and not task.done():
            task.cancel()
        self._owned_pump_session_reobservation_task = None

    def _owned_pump_session_reobservation_required(self) -> bool:
        if not self.driver.requested_enabled:
            return False

        probe = self.driver.probe_execution_evidence()
        if (
            probe is not None
            and probe.phase is PoolTemperatureProbeExecutionPhase.ACQUIRING
        ):
            return True

        return (
            self.driver.active_pump_session_purpose()
            is PumpSpeedSessionPurpose.PRIMING
        )

    def _sync_owned_pump_session_reobservation(self) -> None:
        if not self._owned_pump_session_reobservation_required():
            self._cancel_owned_pump_session_reobservation()
            return
        task = self._owned_pump_session_reobservation_task
        if task is not None and not task.done():
            return
        self._owned_pump_session_reobservation_task = self.hass.async_create_task(
            self._owned_pump_session_reobservation_loop(),
            "PoolOS owned pump-session native reobservation",
        )

    async def _owned_pump_session_reobservation_loop(self) -> None:
        """Keep unchanged owned pump-session evidence current without manufacturing truth."""

        try:
            while not self._unloaded and self._owned_pump_session_reobservation_required():
                await asyncio.sleep(_OWNED_PUMP_SESSION_REOBSERVATION_INTERVAL_SECONDS)
                if self._unloaded or not self._owned_pump_session_reobservation_required():
                    return
                refresh = getattr(
                    self.coordinator,
                    "async_refresh_native_owned_pump_session_evidence",
                    None,
                )
                if refresh is None:
                    return
                await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("PoolOS owned pump-session native reobservation failed")
        finally:
            if asyncio.current_task() is self._owned_pump_session_reobservation_task:
                self._owned_pump_session_reobservation_task = None

    def _sync_cleanup_topology_reobservation(self) -> None:
        """Request one post-boundary native topology refresh per cleanup provenance."""

        if self._unloaded or not self.driver.requested_enabled:
            return
        provenance = getattr(self.driver, "cleanup_provenance", None)
        if provenance is None:
            self._cleanup_topology_reobservation_provenance_id = None
            return
        provenance_id = provenance.provenance_id
        if self._cleanup_topology_reobservation_provenance_id == provenance_id:
            return
        task = self._cleanup_topology_reobservation_task
        if task is not None and not task.done():
            return
        self._cleanup_topology_reobservation_provenance_id = provenance_id
        self._cleanup_topology_reobservation_task = self.hass.async_create_task(
            self._refresh_cleanup_topology_once(provenance_id),
            "PoolOS cleanup topology native reobservation",
        )

    async def _refresh_cleanup_topology_once(self, provenance_id: str) -> None:
        """Refresh topology once after cleanup establishes a new chronology boundary."""

        try:
            if self._unloaded:
                return
            provenance = getattr(self.driver, "cleanup_provenance", None)
            if provenance is None or provenance.provenance_id != provenance_id:
                return
            refresh = getattr(
                self.coordinator,
                "async_refresh_native_cleanup_topology_evidence",
                None,
            )
            if refresh is None:
                return
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("PoolOS cleanup topology native reobservation failed")
        finally:
            if asyncio.current_task() is self._cleanup_topology_reobservation_task:
                self._cleanup_topology_reobservation_task = None

    def _schedule_if_idle(self) -> None:
        if self._unloaded or self._task is not None or self._latest_frame is None:
            return
        if self.manual is None:
            self.driver.fail_closed(
                failed_at=self._latest_frame.observed_at,
                reason="automatic_thermal_manual_delivery_unavailable",
            )
            self.coordinator.async_update_listeners()
            return
        frame = self._latest_frame
        factory = _ManualDeliveryFactory(
            self.manual,
            self.authority,
            self.baselines,
            None if self.pump_speed_session is None else self.pump_speed_session.session,
        )
        self._task = self.hass.async_create_task(
            self.driver.process_epoch(frame, delivery_factory=factory),
            "PoolOS automatic thermal execution epoch",
        )
        self._task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[object]) -> None:
        if task is not self._task:
            return
        self._task = None
        try:
            task.result()
        except asyncio.CancelledError:
            if not self._unloaded:
                frame = self._latest_frame
                self.driver.fail_closed(
                    failed_at=(
                        datetime.now(UTC) if frame is None else frame.observed_at
                    ),
                    reason="automatic_thermal_driver_task_cancelled",
                )
        except Exception as exc:
            LOGGER.exception("PoolOS automatic thermal execution failed closed")
            frame = self._latest_frame
            self.driver.fail_closed(
                failed_at=(datetime.now(UTC) if frame is None else frame.observed_at),
                reason=f"automatic_thermal_driver_exception:{type(exc).__name__}",
            )
        self.coordinator.async_update_listeners()
        self._sync_owned_pump_session_reobservation()
        self._sync_cleanup_topology_reobservation()
        if self._unloaded or not self.driver.requested_enabled:
            return
        latest = self._latest_frame
        if (
            latest is not None
            and latest.epoch_identity != self.driver.last_epoch_identity
        ):
            self._schedule_if_idle()


__all__ = ["PoolOSThermalAutomaticRuntime"]
