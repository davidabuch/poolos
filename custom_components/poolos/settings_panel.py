"""Dedicated Home Assistant settings panel for PoolOS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .config_flow import _mapping_schema
from .const import DOMAIN, INTEGRATION_VERSION

_PANEL_FLAG = "poolos_settings_panel_registered"
_PANEL_PATH = "poolos-settings"
_PANEL_ELEMENT = "poolos-settings-panel"
_PANEL_MODULE_URL = "/poolos_static/settings-panel.js"


def _entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise RuntimeError("PoolOS is not configured")
    return entries[0]


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
    schema = _mapping_schema(current)
    settings = schema(dict(entry.options))
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "version": INTEGRATION_VERSION,
            "settings": settings,
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
    validated = _mapping_schema(current)(dict(msg["settings"]))
    hass.config_entries.async_update_entry(entry, options=validated)
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "version": INTEGRATION_VERSION,
            "settings": validated,
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
