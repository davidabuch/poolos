"""Local diagnostic buttons for the PoolOS Control Center."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from poolos.observations import ObservationQuality, ObservationSourceKind

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN
from .coordinator import PoolOSCoordinator


_RESET_REFRESH_TIMEOUT_SECONDS = 5.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the non-actuating diagnostic reset button."""

    runtime = entry.runtime_data
    async_add_entities(
        [
            PoolOSResetHealthIncidentButton(runtime.coordinator, entry),
            PoolOSAcknowledgeExpectedOutageButton(runtime.coordinator, entry),
            PoolOSResetControlButton(runtime.coordinator, entry),
        ]
    )


class PoolOSResetHealthIncidentButton(
    CoordinatorEntity[PoolOSCoordinator], ButtonEntity
):
    """Acknowledge and clear the local health-incident latch only."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Reset Health Incident"
    _attr_icon = "mdi:restore-alert"

    def __init__(
        self, coordinator: PoolOSCoordinator, entry: ConfigEntry[PoolOSRuntimeData]
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_reset_health_incident"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "PoolOS Control Center",
            "manufacturer": "PoolOS",
            "model": "Operational Commissioning Runtime",
        }

    @property
    def available(self) -> bool:
        """Allow reset only after the current observation state is healthy."""

        return super().available and self.coordinator.observation_health_state() == "HEALTHY"

    async def async_press(self) -> None:
        """Clear acknowledged diagnostic history; never actuate pool equipment."""

        self.coordinator.reset_health_incident_latch()


class PoolOSAcknowledgeExpectedOutageButton(
    CoordinatorEntity[PoolOSCoordinator], ButtonEntity
):
    """Persist operator annotation evidence without controlling equipment."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Acknowledge Expected Pentair Outage"
    _attr_icon = "mdi:power-plug-off-outline"

    def __init__(
        self, coordinator: PoolOSCoordinator, entry: ConfigEntry[PoolOSRuntimeData]
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_acknowledge_expected_pentair_outage"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "PoolOS Control Center",
            "manufacturer": "PoolOS",
            "model": "Operational Commissioning Runtime",
        }

    async def async_press(self) -> None:
        """Record local annotation context; never actuate or clear health."""

        await self.coordinator.async_acknowledge_expected_outage()


class PoolOSResetControlButton(
    CoordinatorEntity[PoolOSCoordinator], ButtonEntity
):
    """Explicit operator recovery to a verified physical Off baseline."""

    _attr_has_entity_name = True
    _attr_name = "Reset PoolOS Control"
    _attr_icon = "mdi:restart-alert"

    def __init__(
        self, coordinator: PoolOSCoordinator, entry: ConfigEntry[PoolOSRuntimeData]
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_reset_poolos_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "PoolOS Control Center",
            "manufacturer": "PoolOS",
            "model": "Operational Commissioning Runtime",
        }
        self._reset_lock = asyncio.Lock()
        self._reset_generation: int | None = None
        self._reset_observation_after: datetime | None = None
        self._reset_running = False
        self._reset_sessions_invalidated = False
        entry.async_on_unload(
            coordinator.async_add_listener(self._observe_reset_completion)
        )

    def _observe_reset_completion(self) -> None:
        """Continue verification after service cancellation/timeout, never delivery."""

        authority = self._runtime.physical_command_authority
        if (
            self._reset_running
            or not self._reset_sessions_invalidated
            or self._reset_generation != authority.reset_recovery_generation
            or not authority.reset_recovery_active
        ):
            return
        if self._safe_reset_baseline():
            authority.finish_reset_recovery()
            # Reset closure invalidates every pre-close runtime context. The
            # publication that proved the safe baseline may already have passed
            # normal runtime listeners before this button listener runs, so it
            # cannot be relied on as the required post-Reset epoch. Always
            # schedule one fresh coordinator evaluation after authority closes.
            asyncio.get_running_loop().create_task(
                self._async_request_post_reset_refresh(),
                name="PoolOS post-reset authoritative refresh",
            )

    @property
    def available(self) -> bool:
        manual = self._runtime.manual_intellicenter
        authority = self._runtime.physical_command_authority
        return bool(
            super().available
            and manual is not None
            and manual.available
            and authority.base_authority_reason.value == "allowed"
        )

    async def async_press(self) -> None:
        """Fence old work, reduce to Off, refresh, then reopen fresh policy."""

        async with self._reset_lock:
            runtime = self._runtime
            authority = runtime.physical_command_authority
            manual = runtime.manual_intellicenter
            if manual is None:
                raise RuntimeError("Reset PoolOS Control requires IntelliCenter delivery")

            reset_at = datetime.now(UTC)
            sanitation_runtime = getattr(runtime, "sanitation_runtime", None)
            if sanitation_runtime is not None:
                await sanitation_runtime.async_abandon_for_higher_authority(
                    reason="reset_poolos_control",
                )
            self._reset_generation = authority.begin_reset_recovery()
            self._reset_observation_after = reset_at
            self._reset_running = True
            self._reset_sessions_invalidated = False
            safe_baseline_verified = False

            try:
                runtime.thermal_automatic_runtime.driver.restrictive_authority_changed(
                    changed_at=reset_at
                )
                runtime.thermal_runtime_orchestrator.reset_session_authority(
                    reset_at=reset_at
                )
                runtime.thermal_automatic_runtime.circulation_ownership.unload()
                runtime.thermal_runtime_orchestrator.ownership.invalidate_residual_termination()
                # Reset clears session-scoped operator restraints but preserves
                # durable policy/accounting. It must not leave future autonomy
                # suppressed after reaching the safe baseline.
                runtime.pool_automatic_control.resume(resumed_at=reset_at)
                runtime.spa_automatic_control.resume(resumed_at=reset_at)
                self._reset_sessions_invalidated = True

                native = self.coordinator.native_intellicenter_snapshot
                values = {} if native is None else {
                    item.observation_id: item.value for item in native.observations
                }

                # Source Off precedes body Off whenever a source is selected.
                if values.get("spa.raw_heater_id") not in {None, "00000"}:
                    self._reset_observation_after = datetime.now(UTC)
                    await manual.async_set_body_heat_source(
                        "B1202", "00000", reset_recovery=True
                    )
                if values.get("pool.raw_heater_id") not in {None, "00000"}:
                    self._reset_observation_after = datetime.now(UTC)
                    await manual.async_set_body_heat_source(
                        "B1101", "00000", reset_recovery=True
                    )
                if values.get("spa.active") is True:
                    self._reset_observation_after = datetime.now(UTC)
                    await manual.async_set_body_active(
                        "B1202", False, reset_recovery=True
                    )
                if values.get("pool.active") is True:
                    self._reset_observation_after = datetime.now(UTC)
                    await manual.async_set_body_active(
                        "B1101", False, reset_recovery=True
                    )

                safe_baseline_verified = await self._async_verify_reset_baseline()
                if not safe_baseline_verified:
                    raise RuntimeError(
                        "Reset shutdown dispatched but safe baseline was not verified "
                        "within the bounded recovery window"
                    )
            finally:
                try:
                    if not safe_baseline_verified:
                        safe_baseline_verified = await self._async_verify_reset_baseline()
                finally:
                    # This synchronous continuation is installed even when the
                    # awaited final refresh itself is cancelled or raises. The
                    # same Reset epoch remains fenced until real native evidence
                    # verifies completion; no command is retried by observation.
                    self._reset_running = False
                    authority.wait_for_reset_evidence(
                        generation=self._reset_generation,
                        invalidated=self._reset_sessions_invalidated,
                    )
                    self._observe_reset_completion()
    async def _async_request_post_reset_refresh(self) -> None:
        """Publish one fresh authoritative epoch after Reset authority closes."""

        try:
            await self.coordinator.async_request_refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("PoolOS post-reset authoritative refresh failed")

    async def _async_verify_reset_baseline(self) -> bool:
        # IntelliCenter body/source shutdown is asynchronous and the pump can
        # remain in a native transition for tens of seconds after the command
        # has been accepted. Do not strand Reset authority merely because the
        # first one or two coordinator snapshots arrive before that transition
        # settles. Keep the Reset fence active and bound the wait.
        for attempt in range(16):
            try:
                await asyncio.wait_for(
                    self.coordinator.async_request_refresh(),
                    timeout=_RESET_REFRESH_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                # A coordinator refresh can stall even while the normal native
                # event stream continues to publish fresh authoritative truth.
                # Do not strand Reset merely because this awaited refresh did
                # not return; accept only the same strict safe-baseline proof.
                if self._safe_reset_baseline():
                    return True
                if attempt == 15:
                    return False
            except Exception:
                if attempt == 15:
                    return False
            else:
                if self._safe_reset_baseline():
                    return True
            if attempt != 15:
                await asyncio.sleep(2)
        return False

    def _safe_reset_baseline(self) -> bool:
        native = self.coordinator.native_intellicenter_snapshot
        observations = {} if native is None else {
            item.observation_id: item for item in native.observations
        }
        required = {
            "pool.active": False, "spa.active": False, "pump.rpm": 0,
            "pool.raw_heater_id": "00000", "spa.raw_heater_id": "00000",
            "solar.active": False, "heater.active": False,
        }
        now = datetime.now(UTC)
        boundary = self._reset_observation_after
        for concept, expected in required.items():
            item = observations.get(concept)
            if (
                boundary is None or item is None
                or item.value != expected
                or item.quality != ObservationQuality.GOOD
                or item.source_kind != ObservationSourceKind.LIVE
                or not item.source_id.startswith("intellicenter_native:")
                or not boundary < item.observed_at <= now
                or now - item.observed_at > timedelta(seconds=30)
            ):
                return False
        return True
