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
from poolos.integration import ThermalBody
from poolos.external_change import ExternalChangeBatch
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDeliveryFactory,
    ThermalAutomaticExecutionDriver,
    ThermalAutomaticExecutionFrame,
)
from poolos.thermal_live_execution import (
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
)
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
        context = self.authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch_identity,
            session_identity=session.execution_plan.plan_id,
            body=session.assessment.desired.body.value,
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


@dataclass(slots=True)
class PoolOSThermalAutomaticRuntime:
    """Own one event-driven automatic driver instance per config entry."""

    hass: HomeAssistant
    coordinator: PoolOSCoordinator
    thermal_runtime: PoolOSThermalRuntime
    orchestrator: ThermalRuntimeOrchestrator
    authority: PoolOSPhysicalCommandAuthority
    manual: ManualIntelliCenterControl | None
    driver: ThermalAutomaticExecutionDriver = field(init=False)
    _latest_frame: ThermalAutomaticExecutionFrame | None = field(
        default=None, init=False, repr=False
    )
    _task: asyncio.Task[object] | None = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.driver = ThermalAutomaticExecutionDriver(self.orchestrator)
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
            filtration_remaining_runtime=(
                None
                if getattr(self.thermal_runtime, "filtration_runtime", None) is None
                or self.thermal_runtime.filtration_runtime.assessment is None
                else self.thermal_runtime.filtration_runtime.assessment.total_remaining_runtime
            ),
            external_changes=external_changes,
        )
        if (
            self._latest_frame is not None
            and self._latest_frame.epoch_identity == frame.epoch_identity
        ):
            return
        self._latest_frame = frame
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
        return dict(self.driver.diagnostics())

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
