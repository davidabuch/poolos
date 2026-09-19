"""Local diagnostic buttons for the PoolOS Control Center."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN
from .coordinator import PoolOSCoordinator


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
            authority.begin_reset_recovery()
            runtime.thermal_automatic_runtime.driver.restrictive_authority_changed(
                changed_at=reset_at
            )
            runtime.thermal_runtime_orchestrator.reset_session_authority(
                reset_at=reset_at
            )
            runtime.thermal_automatic_runtime.circulation_ownership.unload()
            runtime.thermal_runtime_orchestrator.ownership.invalidate_residual_termination()

            try:
                native = self.coordinator.native_intellicenter_snapshot
                values = {} if native is None else {
                    item.observation_id: item.value for item in native.observations
                }

                # Source Off precedes body Off whenever a source is selected.
                if values.get("spa.raw_heater_id") not in {None, "00000"}:
                    await manual.async_set_body_heat_source(
                        "B1202", "00000", reset_recovery=True
                    )
                if values.get("pool.raw_heater_id") not in {None, "00000"}:
                    await manual.async_set_body_heat_source(
                        "B1101", "00000", reset_recovery=True
                    )
                if values.get("spa.active") is True:
                    await manual.async_set_body_active(
                        "B1202", False, reset_recovery=True
                    )
                if values.get("pool.active") is True:
                    await manual.async_set_body_active(
                        "B1101", False, reset_recovery=True
                    )

                await self.coordinator.async_request_refresh()
                native = self.coordinator.native_intellicenter_snapshot
                values = {} if native is None else {
                    item.observation_id: item.value for item in native.observations
                }
                safe = (
                    values.get("pool.active") is False
                    and values.get("spa.active") is False
                    and values.get("pump.rpm") in {0, 0.0}
                    and values.get("pool.raw_heater_id") in {None, "00000"}
                    and values.get("spa.raw_heater_id") in {None, "00000"}
                )
                if not safe:
                    raise RuntimeError(
                        "Reset shutdown dispatched but safe baseline is not yet verified"
                    )
            finally:
                # Closing Reset never restores an old session. The next native
                # epoch is evaluated from durable policy/accounting only.
                authority.finish_reset_recovery()
                await self.coordinator.async_request_refresh()
