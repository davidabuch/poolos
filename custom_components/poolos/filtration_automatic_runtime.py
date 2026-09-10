"""Home Assistant lifecycle bridge for default-off automatic filtration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import logging

from homeassistant.core import HomeAssistant

from poolos.filtration_automatic_execution import (
    FiltrationAutomaticDeliveryFactory,
    FiltrationAutomaticExecutionDriver,
    FiltrationAutomaticExecutionFrame,
)
from poolos.external_change import ExternalChangeBatch
from poolos.grid_outage_confirmation import GridOutageDisposition
from poolos.integration import PoolOperation, SetBodyActive, SetPumpSpeed, ThermalBody
from poolos.physical_command_authority import (
    PhysicalAuthorityReason,
    PoolOSPhysicalCommandAuthority,
)
from poolos.pool_circulation_ownership import PoolCirculationOwnershipRegistry
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_speed_session import (
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionPurpose,
    PumpSpeedSessionRuntime,
)
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
)
from poolos.thermal_runtime_orchestration import (
    ThermalOrchestrationLifecycle,
    ThermalRuntimeOrchestrationAssessment,
)

from .coordinator import PoolOSCoordinator
from .filtration_live_delivery import ManualIntelliCenterFiltrationDelivery
from .filtration_runtime import PoolOSFiltrationRuntime
from .manual_intellicenter import ManualIntelliCenterControl
from .observation import ObservationSnapshot
from .pump_speed_session import PoolOSPumpSpeedSessionRuntime
from .thermal_runtime import PoolOSThermalRuntime

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _DeliveryFactory(FiltrationAutomaticDeliveryFactory):
    manual: ManualIntelliCenterControl
    authority: PoolOSPhysicalCommandAuthority
    ownership: PoolCirculationOwnershipRegistry
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    pump_speed_session: PumpSpeedSessionRuntime | None = None

    def for_operation(
        self,
        *,
        frame: FiltrationAutomaticExecutionFrame,
        session_id: str,
        operation: PoolOperation,
        cleanup: bool,
    ) -> ManualIntelliCenterFiltrationDelivery:
        if isinstance(operation, SetBodyActive):
            operation_name = "body_active"
            target = "B1101"
            value: bool | int = operation.active
        elif isinstance(operation, SetPumpSpeed):
            operation_name = "pump_circuit_speed"
            target = operation.equipment_id
            value = operation.rpm
        else:
            raise ValueError("unsupported automatic filtration operation")
        if frame.pool_pump_circuit_id is None:
            raise ValueError("Pool PMPCIRC identity is unresolved")
        ownership_lease_id = None
        body_activation_receipt_id = None
        if cleanup:
            lease = self.ownership.filtration_lease
            if (
                lease is None
                or lease.session_id != session_id
                or not lease.verified
                or lease.body_activation is None
            ):
                raise ValueError("filtration cleanup ownership is not current")
            ownership_lease_id = lease.lease_id
            body_activation_receipt_id = lease.body_activation.receipt_id
        pump_session_id = None
        effective_pump_rpm = None
        if self.pump_speed_session is not None:
            effective_pump_rpm = self.pump_speed_session.effective_rpm_for(
                body=PumpSpeedSessionBody.POOL,
                purpose=PumpSpeedSessionPurpose.ORDINARY,
                pump_circuit_id=frame.pool_pump_circuit_id,
            )
            if effective_pump_rpm is not None:
                pump_session_id = self.pump_speed_session.snapshot.session_id
        context = self.authority.bind_automatic_filtration_dispatch(
            epoch_identity=frame.epoch_identity,
            session_identity=session_id,
            operation_identity=operation.operation_id,
            operation=operation_name,
            target=target,
            requested_value=value,
            pump_circuit_id=frame.pool_pump_circuit_id,
            cleanup=cleanup,
            ownership_lease_id=ownership_lease_id,
            body_activation_receipt_id=body_activation_receipt_id,
            pump_session_id=pump_session_id,
            effective_pump_rpm=effective_pump_rpm,
        )
        return ManualIntelliCenterFiltrationDelivery(
            self.manual,
            context,
            self.baselines,
        )


@dataclass(slots=True)
class PoolOSFiltrationAutomaticRuntime:
    hass: HomeAssistant
    coordinator: PoolOSCoordinator
    filtration_runtime: PoolOSFiltrationRuntime
    thermal_runtime: PoolOSThermalRuntime
    ownership: PoolCirculationOwnershipRegistry
    authority: PoolOSPhysicalCommandAuthority
    manual: ManualIntelliCenterControl | None
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    pump_speed_session: PoolOSPumpSpeedSessionRuntime | None = None
    pool_automatic_control: PoolAutomaticControlSuppression = field(
        default_factory=PoolAutomaticControlSuppression
    )
    driver: FiltrationAutomaticExecutionDriver = field(init=False)
    _latest_frame: FiltrationAutomaticExecutionFrame | None = field(
        default=None, init=False, repr=False
    )
    _task: asyncio.Task[object] | None = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)
    _desired_enabled: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.driver = FiltrationAutomaticExecutionDriver(self.ownership)
        self.authority.configure_automatic_filtration(enabled=False)

    @property
    def enabled(self) -> bool:
        return self._desired_enabled

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._desired_enabled = enabled
        current = None if self._latest_frame is None else self._latest_frame.epoch_identity
        self.driver.set_enabled(
            enabled,
            changed_at=datetime.now(UTC),
            current_epoch_identity=current,
        )
        self.authority.configure_automatic_filtration(enabled=enabled)
        self.coordinator.async_update_listeners()

    def observe(
        self,
        snapshot: ObservationSnapshot,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        *,
        external_changes: ExternalChangeBatch,
    ) -> None:
        if self._unloaded:
            return
        authority_reason = self.authority.base_authority_reason
        thermal = self.thermal_runtime.assessment
        filtration = self.filtration_runtime.assessment
        pump_session_state = None
        session_rpm = None
        if filtration is not None and self.pump_speed_session is not None:
            pump_session_state = self.pump_speed_session.session.snapshot
            session_rpm = self.pump_speed_session.session.effective_rpm_for(
                body=PumpSpeedSessionBody.POOL,
                purpose=PumpSpeedSessionPurpose.ORDINARY,
                pump_circuit_id=(
                    "" if thermal is None or thermal.pool_pump_circuit_id is None
                    else thermal.pool_pump_circuit_id
                ),
            )
            if session_rpm is not None:
                filtration = replace(
                    filtration,
                    ordinary_filtration_rpm=session_rpm,
                )
        frame = FiltrationAutomaticExecutionFrame(
            epoch_identity=orchestration.snapshot_identity,
            observed_at=snapshot.generated_at,
            observations=tuple(snapshot.observations),
            filtration=filtration,
            pool_pump_circuit_id=(
                None if thermal is None else thermal.pool_pump_circuit_id
            ),
            physical_authority_ready=(
                authority_reason is PhysicalAuthorityReason.ALLOWED
            ),
            physical_authority_blocker=(
                None
                if authority_reason is PhysicalAuthorityReason.ALLOWED
                else f"physical_authority:{authority_reason.value}"
            ),
            grid_on=bool(
                orchestration.outage
                and orchestration.outage.disposition is GridOutageDisposition.ON_GRID
            ),
            thermal_candidate_ready=bool(
                self.ownership.thermal_reserved_for(
                    orchestration.snapshot_identity
                )
                and orchestration.candidate_body is ThermalBody.POOL
                and orchestration.lifecycle
                in {
                    ThermalOrchestrationLifecycle.CANDIDATE_READY,
                    ThermalOrchestrationLifecycle.OWNED,
                }
            ),
            thermal_owned=self.ownership.owner.value == "thermal",
            external_changes=external_changes,
            pool_automatic_control_suppressed=(
                self.pool_automatic_control.state.suppressed
            ),
            pump_session_id=(
                pump_session_state.session_id if session_rpm is not None else None
            ),
            pump_session_effective_rpm=session_rpm,
            pump_session_override_current=bool(
                session_rpm is not None
                and pump_session_state is not None
                and pump_session_state.override_state
                is PumpSpeedOverrideState.VERIFIED
            ),
        )
        if self._latest_frame is not None and self._latest_frame.epoch_identity == frame.epoch_identity:
            return
        self._latest_frame = frame
        self.authority.begin_automatic_filtration_epoch(frame.epoch_identity)
        if not self.driver.requested_enabled and self.ownership.filtration_lease is None:
            self.driver.process_disabled_epoch(frame)
            self.coordinator.async_update_listeners()
            return
        self._schedule_if_idle()

    def diagnostics(self) -> dict[str, object]:
        return {
            **dict(self.driver.diagnostics()),
            **dict(self.pool_automatic_control.diagnostics()),
        }

    def orchestration_failed(
        self,
        snapshot: ObservationSnapshot,
        error: Exception,
    ) -> None:
        """Invalidate stale execution truth without disturbing publication."""

        if self._unloaded:
            return
        self.authority.begin_automatic_filtration_epoch(
            f"filtration-orchestration-failed:{snapshot.generated_at.isoformat()}"
        )
        self.driver.fail_closed(
            failed_at=snapshot.generated_at,
            reason=(
                "automatic_filtration_orchestration_failed:"
                f"{type(error).__name__}"
            ),
        )
        self.coordinator.async_update_listeners()

    async def async_unload(self) -> None:
        if self._unloaded:
            return
        self._unloaded = True
        self.authority.unload_automatic_filtration_driver()
        self.driver.unload(unloaded_at=datetime.now(UTC))
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception("PoolOS automatic filtration task failed during unload")
        self._task = None

    def _schedule_if_idle(self) -> None:
        if self._unloaded or self._task is not None or self._latest_frame is None:
            return
        if self.manual is None:
            self.driver.fail_closed(
                failed_at=self._latest_frame.observed_at,
                reason="automatic_filtration_manual_delivery_unavailable",
            )
            self.coordinator.async_update_listeners()
            return
        factory = _DeliveryFactory(
            self.manual,
            self.authority,
            self.ownership,
            self.baselines,
            None if self.pump_speed_session is None else self.pump_speed_session.session,
        )
        frame = self._latest_frame
        self._task = self.hass.async_create_task(
            self.driver.process_epoch(frame, delivery_factory=factory),
            "PoolOS automatic filtration execution epoch",
        )
        self._task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[object]) -> None:
        if task is not self._task:
            return
        self._task = None
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            LOGGER.exception("PoolOS automatic filtration execution failed closed")
            at = datetime.now(UTC) if self._latest_frame is None else self._latest_frame.observed_at
            self.driver.fail_closed(
                failed_at=at,
                reason=f"automatic_filtration_driver_exception:{type(exc).__name__}",
            )
        self.coordinator.async_update_listeners()
        latest = self._latest_frame
        if (
            not self._unloaded
            and latest is not None
            and latest.epoch_identity != self.driver.last_epoch_identity
        ):
            self._schedule_if_idle()


__all__ = ["PoolOSFiltrationAutomaticRuntime"]
