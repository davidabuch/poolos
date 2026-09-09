"""Home Assistant lifecycle bridge for default-off automatic thermal execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging

from homeassistant.core import HomeAssistant

from poolos.physical_command_authority import (
    AutomaticThermalDispatchPurpose,
    PhysicalAuthorityReason,
    PhysicalRequestSource,
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
from poolos.pool_circulation_ownership import PoolCirculationOwnershipRegistry
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    SpaAutomaticControlSuppression,
)
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDeliveryFactory,
    ThermalAutomaticExecutionDriver,
    ThermalAutomaticExecutionFrame,
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

from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterControl
from .observation import ObservationSnapshot
from .thermal_live_delivery import ManualIntelliCenterThermalLiveDelivery
from .thermal_runtime import PoolOSThermalRuntime


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ManualDeliveryFactory(ThermalAutomaticDeliveryFactory):
    manual: ManualIntelliCenterControl
    authority: PoolOSPhysicalCommandAuthority

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
        context = self.authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch_identity,
            session_identity=session.execution_plan.plan_id,
            body=session.assessment.desired.body.value,
            pump_circuit_id=pump_circuit_id,
            operating_purpose=operating_purpose,
            purpose=purpose,
            probe_operation_id=probe_operation_id,
        )
        return ManualIntelliCenterThermalLiveDelivery(
            manual=self.manual,
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
    _unloaded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.driver = ThermalAutomaticExecutionDriver(
            self.orchestrator,
            circulation_ownership=self.circulation_ownership,
        )
        self._sync_authority_configuration()

    @property
    def enabled(self) -> bool:
        return self.driver.requested_enabled

    def set_enabled(self, enabled: bool) -> None:
        """Change the dedicated gate; never process the cached candidate."""

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
        reason = self.authority.base_authority_reason
        ready = reason is PhysicalAuthorityReason.ALLOWED
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
            pool_automatic_control_suppressed=(
                self.pool_automatic_control.state.suppressed
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
        reserve = getattr(self.driver, "reserve_circulation_candidate", None)
        if reserve is not None:
            reserve(frame)
        self.authority.begin_automatic_thermal_epoch(frame.epoch_identity)
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
        factory = _ManualDeliveryFactory(self.manual, self.authority)
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
        if self._unloaded or not self.driver.requested_enabled:
            return
        latest = self._latest_frame
        if (
            latest is not None
            and latest.epoch_identity != self.driver.last_epoch_identity
        ):
            self._schedule_if_idle()


__all__ = ["PoolOSThermalAutomaticRuntime"]
