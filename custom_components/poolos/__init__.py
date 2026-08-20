"""PoolOS Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
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
from .manual_intellicenter import ManualIntelliCenterControl  # noqa: E402


@dataclass(frozen=True, slots=True)
class PoolOSRuntimeData:
    """Runtime data owned by one PoolOS config entry."""

    coordinator: PoolOSCoordinator
    loaded_at: str
    operating_mode: str
    manual_intellicenter: ManualIntelliCenterControl | None


type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Set up read-only PoolOS observation from a config entry."""

    coordinator = PoolOSCoordinator(hass, entry)
    await coordinator.async_initialize_persistence()
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_event_observation()
    entry.async_on_unload(coordinator.async_stop_event_observation)
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP,
            coordinator.async_handle_homeassistant_stop,
        )
    )
    configured = {**dict(entry.data), **dict(entry.options)}
    manual_host = str(configured.get("intellicenter_host", "")).strip()
    manual_intellicenter = (
        None
        if not manual_host
        else ManualIntelliCenterControl(
            host=manual_host,
            transport=str(configured.get("intellicenter_transport", "tcp")),
        )
    )
    if manual_intellicenter is not None:
        await manual_intellicenter.async_start()

    entry.runtime_data = PoolOSRuntimeData(
        coordinator=coordinator,
        loaded_at=datetime.now(UTC).isoformat(),
        operating_mode=DEFAULT_OPERATING_MODE,
        manual_intellicenter=manual_intellicenter,
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

    await entry.runtime_data.coordinator.async_prepare_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if entry.runtime_data.manual_intellicenter is not None:
        await entry.runtime_data.manual_intellicenter.async_stop()
    await entry.runtime_data.coordinator.async_stop_independent_intellicenter()
    return unloaded
