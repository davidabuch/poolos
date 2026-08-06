"""PoolOS Home Assistant integration skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULT_OPERATING_MODE
from .coordinator import PoolOSCoordinator


@dataclass(frozen=True, slots=True)
class PoolOSRuntimeData:
    """Runtime data owned by one PoolOS config entry."""

    coordinator: PoolOSCoordinator
    loaded_at: str
    operating_mode: str


type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Set up PoolOS from a config entry without external observation or control."""
    coordinator = PoolOSCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = PoolOSRuntimeData(
        coordinator=coordinator,
        loaded_at=datetime.now(UTC).isoformat(),
        operating_mode=DEFAULT_OPERATING_MODE,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Unload the inert PoolOS config entry."""
    return True
