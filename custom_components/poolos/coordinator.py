"""Idle commissioning coordinator for PoolOS."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, INTEGRATION_VERSION


class PoolOSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Own the config-entry lifecycle without observing or controlling equipment."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the idle commissioning coordinator."""
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=None,
        )
        self.config_entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Return local lifecycle state without external I/O."""
        return {
            "integration_version": INTEGRATION_VERSION,
            "lifecycle": "loaded",
            "observation_enabled": False,
            "command_delivery_enabled": False,
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
