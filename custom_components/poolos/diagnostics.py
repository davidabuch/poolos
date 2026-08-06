"""Diagnostics for the PoolOS read-only observation bridge."""

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
    """Return secret-safe observation and lifecycle diagnostics."""
    runtime = getattr(entry, "runtime_data", None)
    coordinator = None if runtime is None else runtime.coordinator
    snapshot = None if coordinator is None else coordinator.data
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
            "lifecycle": coordinator.lifecycle_diagnostics(),
            "observation": None if snapshot is None else snapshot.diagnostics(),
            "shadow_runtime": coordinator.shadow_runtime.diagnostics(),
        },
        "diagnostics_enabled": entry.options.get(CONF_DIAGNOSTICS_ENABLED, True),
        "safety": {
            "observation_enabled": runtime is not None,
            "command_delivery_enabled": False,
            "shadow_runtime_enabled": runtime is not None,
        },
    }
    return dict(async_redact_data(payload, _TO_REDACT))
