"""PoolOS Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULT_OPERATING_MODE, PLATFORMS
from .coordinator import PoolOSCoordinator


@dataclass(frozen=True, slots=True)
class PoolOSRuntimeData:
    """Runtime data owned by one PoolOS config entry."""

    coordinator: PoolOSCoordinator
    loaded_at: str
    operating_mode: str


type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Set up read-only PoolOS observation from a config entry."""

    coordinator = PoolOSCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = PoolOSRuntimeData(
        coordinator=coordinator,
        loaded_at=datetime.now(UTC).isoformat(),
        operating_mode=DEFAULT_OPERATING_MODE,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: PoolOSConfigEntry) -> None:
    """Reload the entry after entity mappings change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Unload the read-only PoolOS config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
