"""Config-entry migrations for the PoolOS Home Assistant integration."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .const import (
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    RETIRED_LEGACY_INTELLICENTER_ENTITY_OPTIONS,
)


class _ConfigEntry(Protocol):
    version: int
    minor_version: int
    data: Mapping[str, Any]
    options: Mapping[str, Any]


class _ConfigEntries(Protocol):
    def async_update_entry(self, entry: _ConfigEntry, **changes: Any) -> None: ...


class _HomeAssistant(Protocol):
    config_entries: _ConfigEntries


def migrate_config_entry(hass: _HomeAssistant, entry: _ConfigEntry) -> bool:
    """Remove retired legacy shadow mappings from config data and options."""

    if entry.version != CONFIG_ENTRY_VERSION:
        return False
    if entry.minor_version > CONFIG_ENTRY_MINOR_VERSION:
        return False

    data = _without_retired_options(entry.data)
    options = _without_retired_options(entry.options)
    if (
        entry.minor_version != CONFIG_ENTRY_MINOR_VERSION
        or data != dict(entry.data)
        or options != dict(entry.options)
    ):
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            version=CONFIG_ENTRY_VERSION,
            minor_version=CONFIG_ENTRY_MINOR_VERSION,
        )
    return True


def _without_retired_options(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if key not in RETIRED_LEGACY_INTELLICENTER_ENTITY_OPTIONS
    }
