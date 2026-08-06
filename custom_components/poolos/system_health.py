"""System health information for PoolOS."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, INTEGRATION_VERSION


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register PoolOS system health information."""
    register.async_register_info(_async_system_health_info)


async def _async_system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return read-only commissioning health information."""
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [entry for entry in entries if getattr(entry, "runtime_data", None)]
    snapshots = [entry.runtime_data.coordinator.data for entry in loaded]
    return {
        "integration_version": INTEGRATION_VERSION,
        "configured_entries": len(entries),
        "loaded_entries": len(loaded),
        "observation_enabled": bool(loaded),
        "observation_healthy": bool(snapshots) and all(
            snapshot is not None and snapshot.healthy for snapshot in snapshots
        ),
        "command_delivery_enabled": False,
    }
