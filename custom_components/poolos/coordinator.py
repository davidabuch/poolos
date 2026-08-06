"""Read-only commissioning coordinator for PoolOS."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from poolos.homeassistant.observations import HomeAssistantState

from .const import DOMAIN, INTEGRATION_VERSION, OBSERVATION_UPDATE_INTERVAL
from .observation import ObservationSnapshot, build_snapshot, configured_entity_mapping
from .shadow import HomeAssistantShadowRuntime


class PoolOSCoordinator(DataUpdateCoordinator[ObservationSnapshot]):
    """Read configured Home Assistant entities without invoking services."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the read-only commissioning coordinator."""
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=OBSERVATION_UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.shadow_runtime = HomeAssistantShadowRuntime.create()

    async def _async_update_data(self) -> ObservationSnapshot:
        """Build a canonical snapshot from the current Home Assistant state machine."""

        configured = {**dict(self.config_entry.data), **dict(self.config_entry.options)}
        states: dict[str, HomeAssistantState] = {}
        for entity_id in configured_entity_mapping(configured).values():
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            states[entity_id] = HomeAssistantState(
                entity_id=entity_id,
                state=state.state,
                last_changed=state.last_changed,
                last_updated=state.last_updated,
                attributes=state.attributes,
            )
        snapshot = build_snapshot(
            options=configured,
            states=states,
            now=datetime.now(UTC),
        )
        self.shadow_runtime.evaluate(snapshot)
        return snapshot

    def lifecycle_diagnostics(self) -> dict[str, object]:
        """Return stable integration lifecycle data for diagnostics and health."""

        snapshot = self.data
        return {
            "integration_version": INTEGRATION_VERSION,
            "lifecycle": "loaded",
            "observation_enabled": True,
            "command_delivery_enabled": False,
            "observation_healthy": None if snapshot is None else snapshot.healthy,
            "refreshed_at": None if snapshot is None else snapshot.generated_at.isoformat(),
            "shadow_runtime_enabled": True,
            "shadow_runtime": self.shadow_runtime.diagnostics(),
        }
