"""PoolOS Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_HOMEASSISTANT_STOP,
)
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
from .filtration_runtime import PoolOSFiltrationRuntime  # noqa: E402
from .external_change_runtime import PoolOSExternalChangeRuntime  # noqa: E402
from .manual_intellicenter import ManualIntelliCenterControl  # noqa: E402
from .observation import ObservationSnapshot  # noqa: E402
from .thermal_runtime import PoolOSThermalRuntime  # noqa: E402
from .thermal_automatic_runtime import PoolOSThermalAutomaticRuntime  # noqa: E402
from poolos.thermal_runtime_orchestration import (  # noqa: E402
    ThermalRuntimeOrchestrator,
)
from poolos.physical_command_authority import (  # noqa: E402
    PoolOSPhysicalCommandAuthority,
)
from poolos.thermal_runtime_assessment import (  # noqa: E402
    ThermalRuntimeAssessment,
)


@dataclass(frozen=True, slots=True)
class PoolOSRuntimeData:
    """Runtime data owned by one PoolOS config entry."""

    coordinator: PoolOSCoordinator
    loaded_at: str
    operating_mode: str
    manual_intellicenter: ManualIntelliCenterControl | None
    filtration_runtime: PoolOSFiltrationRuntime
    thermal_runtime: PoolOSThermalRuntime
    physical_command_authority: PoolOSPhysicalCommandAuthority
    external_change_runtime: PoolOSExternalChangeRuntime
    thermal_runtime_orchestrator: ThermalRuntimeOrchestrator
    thermal_automatic_runtime: PoolOSThermalAutomaticRuntime


type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Set up read-only PoolOS observation from a config entry."""

    coordinator = PoolOSCoordinator(hass, entry)
    await coordinator.async_initialize_persistence()
    filtration_runtime = PoolOSFiltrationRuntime(coordinator=coordinator)
    await filtration_runtime.async_restore(restored_at=datetime.now(UTC))
    coordinator.set_filtration_runtime_refresh(filtration_runtime.refresh)
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(coordinator.async_stop_event_observation)
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP,
            coordinator.async_handle_homeassistant_stop,
        )
    )
    configured = {**dict(entry.data), **dict(entry.options)}
    manual_host = str(configured.get("intellicenter_host", "")).strip()
    physical_command_authority = PoolOSPhysicalCommandAuthority()
    manual_intellicenter = (
        None
        if not manual_host
        else ManualIntelliCenterControl(
            host=manual_host,
            command_authority=physical_command_authority,
            transport=str(configured.get("intellicenter_transport", "tcp")),
        )
    )

    thermal_runtime = PoolOSThermalRuntime(
        coordinator=coordinator,
        manual_intellicenter=manual_intellicenter,
        filtration_runtime=filtration_runtime,
    )
    external_change_runtime = PoolOSExternalChangeRuntime(
        hass=hass,
        authority=physical_command_authority,
        thermal_runtime=thermal_runtime,
    )
    thermal_runtime_orchestrator = ThermalRuntimeOrchestrator()
    thermal_automatic_runtime = PoolOSThermalAutomaticRuntime(
        hass=hass,
        coordinator=coordinator,
        thermal_runtime=thermal_runtime,
        orchestrator=thermal_runtime_orchestrator,
        authority=physical_command_authority,
        manual=manual_intellicenter,
    )
    entry.runtime_data = PoolOSRuntimeData(
        coordinator=coordinator,
        loaded_at=datetime.now(UTC).isoformat(),
        operating_mode=DEFAULT_OPERATING_MODE,
        manual_intellicenter=manual_intellicenter,
        filtration_runtime=filtration_runtime,
        thermal_runtime=thermal_runtime,
        physical_command_authority=physical_command_authority,
        external_change_runtime=external_change_runtime,
        thermal_runtime_orchestrator=thermal_runtime_orchestrator,
        thermal_automatic_runtime=thermal_automatic_runtime,
    )
    coordinator.set_thermal_runtime_refresh(thermal_runtime.refresh)
    coordinator.set_native_snapshot_observer(external_change_runtime.process)
    thermal_runtime.set_assessment_observer(
        external_change_runtime.refresh_ownership
    )
    def observe_thermal_orchestration(
        snapshot: ObservationSnapshot | None,
        assessment: ThermalRuntimeAssessment | None,
    ) -> None:
        if snapshot is None:
            return
        orchestration = thermal_runtime_orchestrator.refresh(
            generated_at=snapshot.generated_at,
            observations=snapshot.observations,
            thermal=assessment,
            external_changes=external_change_runtime.latest_batch,
        )
        thermal_automatic_runtime.observe(snapshot, assessment, orchestration)

    thermal_runtime.set_orchestration_observer(observe_thermal_orchestration)
    def fail_thermal_orchestration_closed(
        snapshot: ObservationSnapshot,
        error: Exception,
    ) -> None:
        thermal_runtime_orchestrator.fail_closed(
            failed_at=snapshot.generated_at,
            reason_code=(
                "thermal_orchestration_processing_failed:"
                f"{type(error).__name__}"
            ),
        )
        thermal_automatic_runtime.orchestration_failed(snapshot, error)

    thermal_runtime.set_orchestration_failure_observer(
        fail_thermal_orchestration_closed
    )
    thermal_runtime.refresh(coordinator.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def async_activate_poolos_post_start() -> None:
        """Start deferred PoolOS facilities after Home Assistant startup."""

        if coordinator._unloading:
            return

        if manual_intellicenter is not None:
            await manual_intellicenter.async_start()
            thermal_runtime.refresh(publish=True)

        if coordinator._unloading:
            return

        coordinator.async_activate_post_start()

    if hass.is_running:
        await async_activate_poolos_post_start()
    else:
        startup_unsub = None

        async def async_handle_homeassistant_started(_event: object) -> None:
            """Activate deferred PoolOS work after Home Assistant is operational."""
            nonlocal startup_unsub
            startup_unsub = None
            await async_activate_poolos_post_start()

        startup_unsub = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            async_handle_homeassistant_started,
        )

        def async_remove_startup_listener() -> None:
            """Remove the pending startup listener at most once."""
            nonlocal startup_unsub
            if startup_unsub is None:
                return
            unsubscribe = startup_unsub
            startup_unsub = None
            unsubscribe()

        entry.async_on_unload(async_remove_startup_listener)

    return True


async def _async_options_updated(hass: HomeAssistant, entry: PoolOSConfigEntry) -> None:
    """Reload the entry after entity mappings change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Unload the read-only PoolOS config entry."""

    entry.runtime_data.thermal_runtime.set_orchestration_observer(None)
    entry.runtime_data.thermal_runtime.set_orchestration_failure_observer(None)
    await entry.runtime_data.thermal_automatic_runtime.async_unload()
    entry.runtime_data.thermal_runtime_orchestrator.unload(
        unloaded_at=datetime.now(UTC)
    )
    await entry.runtime_data.coordinator.async_prepare_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if entry.runtime_data.manual_intellicenter is not None:
        await entry.runtime_data.manual_intellicenter.async_stop()
    await entry.runtime_data.coordinator.async_stop_independent_intellicenter()
    return unloaded
