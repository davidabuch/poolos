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
    CONF_POOL_COMMISSIONED_PUMP_MODE,
    CONF_POOL_COMMISSIONED_PUMP_PROVIDER,
    CONF_POOL_COMMISSIONED_PUMP_ID,
    CONF_POOL_COMMISSIONED_PUMP_MIN_GPM,
    CONF_POOL_COMMISSIONED_PUMP_MAX_GPM,
    CONF_SPA_COMMISSIONED_PUMP_MODE,
    CONF_SPA_COMMISSIONED_PUMP_PROVIDER,
    CONF_SPA_COMMISSIONED_PUMP_ID,
    CONF_SPA_COMMISSIONED_PUMP_MIN_GPM,
    CONF_SPA_COMMISSIONED_PUMP_MAX_GPM,
    COMMISSIONED_PUMP_MODE_AUTOMATIC,
    COMMISSIONED_PUMP_MODE_RPM_ONLY,
    COMMISSIONED_PUMP_MODE_RPM_GPM,
    DOMAIN,
    INTEGRATION_VERSION,
    PUMP_TARGET_UNIT_GPM,
)
from poolos.pump_capability import PumpCapabilitySupport

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
    provider = (
        None if runtime is None else getattr(runtime, "pump_capability_provider", None)
    )
    if provider is None:
        unavailable = _unsupported_capability("pump_capability_provider_not_configured")
        return {
            "filtration": dict(unavailable),
            "solar_heating": dict(unavailable),
            "gas_heating": dict(unavailable),
            "temperature_probe": dict(unavailable),
            "sanitation": dict(unavailable),
        }

    pool_profile = provider.pump_capability_profile(body="pool")
    spa_profile = provider.pump_capability_profile(body="hot_tub")

    pool = (
        _unsupported_capability("pool_pump_capability_not_proven")
        if pool_profile is None or not pool_profile.as_mapping()["gpm_control"]
        else {
            "supported": True,
            "reason": "canonical_pump_flow_control_proven",
            "pump_circuit_id": pool_profile.pump_circuit_id,
            "parent_pump_id": pool_profile.pump_id,
            "minimum_gpm": pool_profile.minimum_gpm,
            "maximum_gpm": pool_profile.maximum_gpm,
            "provider": pool_profile.provider,
            "evidence_source": pool_profile.evidence_source.value,
        }
    )
    spa = (
        _unsupported_capability("hot_tub_pump_capability_not_proven")
        if spa_profile is None or not spa_profile.as_mapping()["gpm_control"]
        else {
            "supported": True,
            "reason": "canonical_pump_flow_control_proven",
            "pump_circuit_id": spa_profile.pump_circuit_id,
            "parent_pump_id": spa_profile.pump_id,
            "minimum_gpm": spa_profile.minimum_gpm,
            "maximum_gpm": spa_profile.maximum_gpm,
            "provider": spa_profile.provider,
            "evidence_source": spa_profile.evidence_source.value,
        }
    )

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


_COMMISSIONING_BINDINGS = {
    "pool": (
        CONF_POOL_COMMISSIONED_PUMP_MODE,
        CONF_POOL_COMMISSIONED_PUMP_PROVIDER,
        CONF_POOL_COMMISSIONED_PUMP_ID,
        CONF_POOL_COMMISSIONED_PUMP_MIN_GPM,
        CONF_POOL_COMMISSIONED_PUMP_MAX_GPM,
    ),
    "hot_tub": (
        CONF_SPA_COMMISSIONED_PUMP_MODE,
        CONF_SPA_COMMISSIONED_PUMP_PROVIDER,
        CONF_SPA_COMMISSIONED_PUMP_ID,
        CONF_SPA_COMMISSIONED_PUMP_MIN_GPM,
        CONF_SPA_COMMISSIONED_PUMP_MAX_GPM,
    ),
}


def _native_pump_profiles(entry: ConfigEntry) -> dict[str, Any]:
    runtime = getattr(entry, "runtime_data", None)
    provider = (
        None if runtime is None else getattr(runtime, "pump_capability_provider", None)
    )
    if provider is None or not hasattr(provider, "native_pump_capability_profile"):
        return {"pool": None, "hot_tub": None}
    return {
        body: provider.native_pump_capability_profile(body=body)
        for body in ("pool", "hot_tub")
    }


def _pump_capability_commissioning(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Describe whether exact-identity manual commissioning is currently allowed."""

    current = {**dict(entry.data), **dict(entry.options)}
    profiles = _native_pump_profiles(entry)
    result: dict[str, dict[str, Any]] = {}
    for body, profile in profiles.items():
        mode_key, provider_key, pump_id_key, minimum_key, maximum_key = (
            _COMMISSIONING_BINDINGS[body]
        )
        record: dict[str, Any] = {
            "mode": current.get(mode_key, COMMISSIONED_PUMP_MODE_AUTOMATIC),
            "eligible": False,
            "reason": "pump_identity_not_proven",
        }
        if profile is not None:
            mapping = profile.as_mapping()
            record.update(
                {
                    "provider": profile.provider,
                    "pump_id": profile.pump_id,
                    "pump_circuit_id": profile.pump_circuit_id,
                    "native_gpm_control_status": mapping["gpm_control_status"],
                    "native_gpm_sensing": mapping["gpm_sensing"],
                    "eligible": (
                        profile.effective_flow_control_support
                        is PumpCapabilitySupport.UNKNOWN
                    ),
                    "reason": (
                        "native_flow_control_unknown"
                        if profile.effective_flow_control_support
                        is PumpCapabilitySupport.UNKNOWN
                        else "native_capability_authoritative"
                    ),
                    "commissioned_provider": current.get(provider_key),
                    "commissioned_pump_id": current.get(pump_id_key),
                    "minimum_gpm": current.get(minimum_key),
                    "maximum_gpm": current.get(maximum_key),
                }
            )
        result[body] = record
    return result


def _bind_and_validate_commissioning(
    settings: dict[str, Any],
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Bind commissioned claims to live native identity and reject contradictions."""

    profiles = _native_pump_profiles(entry)
    bound = dict(settings)
    identities: dict[tuple[str, str], tuple[str, int | None, int | None]] = {}

    for body, profile in profiles.items():
        mode_key, provider_key, pump_id_key, minimum_key, maximum_key = (
            _COMMISSIONING_BINDINGS[body]
        )
        mode = str(bound.get(mode_key, COMMISSIONED_PUMP_MODE_AUTOMATIC))
        if mode == COMMISSIONED_PUMP_MODE_AUTOMATIC:
            for key in (provider_key, pump_id_key, minimum_key, maximum_key):
                bound.pop(key, None)
            continue
        if profile is None:
            raise vol.Invalid(f"{body} pump identity is not currently proven")
        if (
            profile.effective_flow_control_support
            is not PumpCapabilitySupport.UNKNOWN
        ):
            raise vol.Invalid(
                f"{body} pump GPM capability is already authoritative: "
                f"{profile.effective_flow_control_support.value}"
            )

        bound[provider_key] = profile.provider
        bound[pump_id_key] = profile.pump_id

        minimum = bound.get(minimum_key)
        maximum = bound.get(maximum_key)
        if mode == COMMISSIONED_PUMP_MODE_RPM_GPM:
            if not isinstance(minimum, int) or not isinstance(maximum, int):
                raise vol.Invalid(
                    f"{body} commissioned GPM support requires minimum and maximum GPM"
                )
            if minimum <= 0 or maximum <= 0 or minimum > maximum:
                raise vol.Invalid(f"{body} commissioned GPM range is invalid")
        elif mode == COMMISSIONED_PUMP_MODE_RPM_ONLY:
            bound.pop(minimum_key, None)
            bound.pop(maximum_key, None)
            minimum = maximum = None
        else:
            raise vol.Invalid(f"{body} commissioned pump mode is invalid")

        identity = (profile.provider, profile.pump_id)
        claim = (mode, minimum, maximum)
        prior = identities.get(identity)
        if prior is not None and prior != claim:
            raise vol.Invalid(
                "conflicting commissioned capability claims for the same physical pump"
            )
        identities[identity] = claim

    return bound


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
            "pump_capability_commissioning": _pump_capability_commissioning(entry),
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
    validated = _bind_and_validate_commissioning(validated, entry)
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
            "pump_capability_commissioning": _pump_capability_commissioning(entry),
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
        module_url=_PANEL_MODULE_URL + "?v=" + INTEGRATION_VERSION,
        require_admin=True,
        config_panel_domain=DOMAIN,
        config={"version": INTEGRATION_VERSION},
        handle_safe_area=True,
    )
    hass.data[_PANEL_FLAG] = True
