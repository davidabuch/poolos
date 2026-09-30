"""Dedicated Home Assistant settings panel for PoolOS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .config_flow import _settings_schema
from .const import (
    CONF_PUMP_FILTRATION_GPM,
    CONF_PUMP_FILTRATION_UNIT,
    CONF_PUMP_GAS_HEATING_GPM,
    CONF_PUMP_GAS_HEATING_UNIT,
    CONF_PUMP_SOLAR_HEATING_GPM,
    CONF_PUMP_SOLAR_HEATING_UNIT,
    CONF_PUMP_TEMPERATURE_PROBE_GPM,
    CONF_PUMP_TEMPERATURE_PROBE_UNIT,
    CONF_SANITATION_GPM,
    CONF_SANITATION_UNIT,
    DOMAIN,
    INTEGRATION_VERSION,
    PUMP_TARGET_UNIT_GPM,
)

_PANEL_FLAG = "poolos_settings_panel_registered"
_PANEL_PATH = "poolos-settings"
_PANEL_ELEMENT = "poolos-settings-panel"
_PANEL_MODULE_URL = "/poolos_static/settings-panel.js"


def _entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise RuntimeError("PoolOS is not configured")
    return entries[0]


def _unsupported_capability(reason: str) -> dict[str, Any]:
    return {
        "supported": False,
        "reason": reason,
    }


def _pump_target_capabilities(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Return fail-closed live GPM capability for exposed automatic purposes."""

    runtime = getattr(entry, "runtime_data", None)
    manual = (
        None if runtime is None else getattr(runtime, "manual_intellicenter", None)
    )
    if manual is None:
        unavailable = _unsupported_capability("manual_transport_not_configured")
        return {
            "filtration": dict(unavailable),
            "solar_heating": dict(unavailable),
            "gas_heating": dict(unavailable),
            "temperature_probe": dict(unavailable),
            "sanitation": dict(unavailable),
        }

    pool = dict(manual.pump_flow_capability(body="pool"))
    spa = dict(manual.pump_flow_capability(body="hot_tub"))

    filtration = dict(pool)
    if not pool.get("supported") or not spa.get("supported"):
        thermal = _unsupported_capability(
            "pool_and_hot_tub_flow_capability_required"
        )
    else:
        minimum = max(int(pool["minimum_gpm"]), int(spa["minimum_gpm"]))
        maximum = min(int(pool["maximum_gpm"]), int(spa["maximum_gpm"]))
        if minimum > maximum:
            thermal = _unsupported_capability(
                "pool_and_hot_tub_flow_ranges_do_not_overlap"
            )
        else:
            thermal = {
                "supported": True,
                "reason": "common_pool_hot_tub_native_flow_range_proven",
                "minimum_gpm": minimum,
                "maximum_gpm": maximum,
                "pool_pump_circuit_id": pool.get("pump_circuit_id"),
                "spa_pump_circuit_id": spa.get("pump_circuit_id"),
                "pool_parent_pump_id": pool.get("parent_pump_id"),
                "spa_parent_pump_id": spa.get("parent_pump_id"),
            }
    return {
        "filtration": filtration,
        "solar_heating": dict(thermal),
        "gas_heating": dict(thermal),
        "temperature_probe": dict(thermal),
        "sanitation": dict(thermal),
    }


_GPM_SETTING_BINDINGS = (
    (
        CONF_PUMP_FILTRATION_UNIT,
        CONF_PUMP_FILTRATION_GPM,
        "filtration",
    ),
    (
        CONF_PUMP_SOLAR_HEATING_UNIT,
        CONF_PUMP_SOLAR_HEATING_GPM,
        "solar_heating",
    ),
    (
        CONF_PUMP_GAS_HEATING_UNIT,
        CONF_PUMP_GAS_HEATING_GPM,
        "gas_heating",
    ),
    (
        CONF_PUMP_TEMPERATURE_PROBE_UNIT,
        CONF_PUMP_TEMPERATURE_PROBE_GPM,
        "temperature_probe",
    ),
    (
        CONF_SANITATION_UNIT,
        CONF_SANITATION_GPM,
        "sanitation",
    ),
)


def _validate_live_gpm_settings(
    settings: dict[str, Any],
    capabilities: dict[str, dict[str, Any]],
) -> None:
    """Reject GPM configuration without current native capability proof."""

    for unit_key, gpm_key, purpose in _GPM_SETTING_BINDINGS:
        if settings.get(unit_key) != PUMP_TARGET_UNIT_GPM:
            continue
        capability = capabilities[purpose]
        if not capability.get("supported"):
            raise vol.Invalid(
                f"{purpose} GPM is unavailable: {capability.get('reason', 'unknown')}"
            )
        value = settings.get(gpm_key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise vol.Invalid(f"{gpm_key} is required for GPM mode")
        minimum = int(capability["minimum_gpm"])
        maximum = int(capability["maximum_gpm"])
        if not minimum <= value <= maximum:
            raise vol.Invalid(
                f"{gpm_key} must be between {minimum} and {maximum} GPM"
            )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "poolos/settings/get"})
@websocket_api.async_response
async def websocket_settings_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return validated PoolOS settings for the dedicated panel."""

    entry = _entry(hass)
    current = {**dict(entry.data), **dict(entry.options)}
    schema = _settings_schema(current)
    settings = schema(dict(entry.options))
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "version": INTEGRATION_VERSION,
            "settings": settings,
            "pump_target_capabilities": _pump_target_capabilities(entry),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "poolos/settings/update",
        vol.Required("settings"): dict,
    }
)
@websocket_api.async_response
async def websocket_settings_update(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Validate and persist PoolOS settings from the dedicated panel."""

    entry = _entry(hass)
    current = {**dict(entry.data), **dict(entry.options)}
    validated = _settings_schema(current)(dict(msg["settings"]))
    capabilities = _pump_target_capabilities(entry)
    _validate_live_gpm_settings(validated, capabilities)
    hass.config_entries.async_update_entry(entry, options=validated)
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "version": INTEGRATION_VERSION,
            "settings": validated,
            "pump_target_capabilities": capabilities,
            "reload_requested": True,
        },
    )


async def async_setup_settings_panel(hass: HomeAssistant) -> None:
    """Register the PoolOS settings panel and websocket API once."""

    if hass.data.get(_PANEL_FLAG):
        return

    module_path = Path(__file__).resolve().parent / "settings_panel.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_PANEL_MODULE_URL, str(module_path), False)]
    )
    websocket_api.async_register_command(hass, websocket_settings_get)
    websocket_api.async_register_command(hass, websocket_settings_update)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=_PANEL_PATH,
        webcomponent_name=_PANEL_ELEMENT,
        sidebar_title="PoolOS Settings",
        sidebar_icon="mdi:pool",
        module_url=_PANEL_MODULE_URL,
        require_admin=True,
        config_panel_domain=DOMAIN,
        config={"version": INTEGRATION_VERSION},
        handle_safe_area=True,
    )
    hass.data[_PANEL_FLAG] = True
