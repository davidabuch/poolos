"""Diagnostics for the PoolOS integration skeleton."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PoolOSConfigEntry
from .const import CONF_DIAGNOSTICS_ENABLED, INTEGRATION_VERSION

_TO_REDACT = {"access_token", "token", "api_key", "host", "url"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PoolOSConfigEntry
) -> dict[str, Any]:
    """Return secret-safe lifecycle diagnostics."""
    runtime = getattr(entry, "runtime_data", None)
    coordinator_data = None if runtime is None else runtime.coordinator.data
    payload: dict[str, Any] = {
        "integration_version": INTEGRATION_VERSION,
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": None
        if runtime is None
        else {
            "loaded_at": runtime.loaded_at,
            "operating_mode": runtime.operating_mode,
            "coordinator_data": coordinator_data,
        },
        "diagnostics_enabled": entry.options.get(CONF_DIAGNOSTICS_ENABLED, True),
        "safety": {
            "observation_enabled": False,
            "command_delivery_enabled": False,
        },
    }
    return dict(async_redact_data(payload, _TO_REDACT))
