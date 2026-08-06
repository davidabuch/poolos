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
    """Return commissioning-safe system health information."""
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded_entries = sum(1 for entry in entries if getattr(entry, "runtime_data", None))
    return {
        "integration_version": INTEGRATION_VERSION,
        "configured_entries": len(entries),
        "loaded_entries": loaded_entries,
        "observation_enabled": False,
        "command_delivery_enabled": False,
    }
