"""Local diagnostic buttons for the PoolOS Control Center."""

from __future__ import annotations

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
    async_add_entities([PoolOSResetHealthIncidentButton(runtime.coordinator, entry)])


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
