"""PoolOS Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


def _enable_local_vendored_core() -> None:
    """Prefer the bundled PoolOS core when using a local commissioning package."""

    vendor_root = Path(__file__).resolve().parent / "_vendor"
    if not (vendor_root / "poolos" / "__init__.py").is_file():
        return
    vendor_path = str(vendor_root)
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)


_enable_local_vendored_core()

from .const import DEFAULT_OPERATING_MODE, PLATFORMS  # noqa: E402
from .coordinator import PoolOSCoordinator  # noqa: E402


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
    coordinator.async_start_event_observation()
    entry.async_on_unload(coordinator.async_stop_event_observation)
    entry.runtime_data = PoolOSRuntimeData(
        coordinator=coordinator,
        loaded_at=datetime.now(UTC).isoformat(),
        operating_mode=DEFAULT_OPERATING_MODE,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    coordinator.async_start_independent_intellicenter()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: PoolOSConfigEntry) -> None:
    """Reload the entry after entity mappings change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Unload the read-only PoolOS config entry."""

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.coordinator.async_stop_independent_intellicenter()
    return unloaded
