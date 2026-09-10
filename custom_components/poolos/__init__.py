"""PoolOS Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
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

from .const import (  # noqa: E402
    CONF_PREFERRED_FILTRATION_CATCHUP_START,
    DEFAULT_OPERATING_MODE,
    DEFAULT_PREFERRED_FILTRATION_CATCHUP_START,
    PLATFORMS,
)
from .config_entry_migration import migrate_config_entry  # noqa: E402
from .coordinator import PoolOSCoordinator  # noqa: E402
from .filtration_runtime import PoolOSFiltrationRuntime  # noqa: E402
from .filtration_automatic_runtime import (  # noqa: E402
    PoolOSFiltrationAutomaticRuntime,
)
from .external_change_runtime import PoolOSExternalChangeRuntime  # noqa: E402
from .grid_outage_runtime import PoolOSGridOutageSafetyRuntime  # noqa: E402
from .manual_intellicenter import ManualIntelliCenterControl  # noqa: E402
from .observation import ObservationSnapshot  # noqa: E402
from .pump_baselines import compose_pump_baseline_runtime  # noqa: E402
from .pump_speed_session import PoolOSPumpSpeedSessionRuntime  # noqa: E402
from .thermal_runtime import PoolOSThermalRuntime  # noqa: E402
from .thermal_automatic_runtime import PoolOSThermalAutomaticRuntime  # noqa: E402
from poolos.thermal_runtime_orchestration import (  # noqa: E402
    ThermalRuntimeOrchestrator,
    assess_pool_temperature_probe_continuity,
)
from poolos.pool_temperature_probe_execution import (  # noqa: E402
    PoolTemperatureProbeContinuityEvidence,
)
from poolos.physical_command_authority import (  # noqa: E402
    PhysicalAuthorityReason,
    PoolOSPhysicalCommandAuthority,
)
from poolos.operating_baselines import PumpOperatingBaselines  # noqa: E402
from poolos.intellicenter_readonly import (  # noqa: E402
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.pump_speed_session import PumpSpeedSessionPurpose  # noqa: E402
from poolos.grid_outage_confirmation import GridOutageDisposition  # noqa: E402
from poolos.pool_circulation_ownership import (  # noqa: E402
    PoolCirculationOwnershipRegistry,
)
from poolos.pool_automatic_control_suppression import (  # noqa: E402
    PoolAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppression,
    SpaAutomaticControlSuppressionSource,
    pool_suppression_is_current,
    spa_suppression_is_current,
)
from poolos.thermal_live_execution import ThermalLiveCommissioningScope  # noqa: E402
from poolos.thermal_runtime_assessment import ThermalRuntimeAssessment  # noqa: E402


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
    grid_outage_safety_runtime: PoolOSGridOutageSafetyRuntime
    filtration_automatic_runtime: PoolOSFiltrationAutomaticRuntime
    pool_automatic_control: PoolAutomaticControlSuppression
    pump_operating_baselines: PumpOperatingBaselines
    pump_speed_session: PoolOSPumpSpeedSessionRuntime | None = None
    spa_automatic_control: SpaAutomaticControlSuppression = field(
        default_factory=SpaAutomaticControlSuppression
    )


type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: PoolOSConfigEntry,
) -> bool:
    """Remove retired legacy IntelliCenter HA shadow mappings."""

    return migrate_config_entry(hass, entry)


async def async_setup_entry(hass: HomeAssistant, entry: PoolOSConfigEntry) -> bool:
    """Set up read-only PoolOS observation from a config entry."""

    coordinator = PoolOSCoordinator(hass, entry)
    await coordinator.async_initialize_persistence()

    configured = {**dict(entry.data), **dict(entry.options)}
    pump_composition = compose_pump_baseline_runtime(configured)
    pump_baselines = pump_composition.baselines
    preferred_catchup_text = str(
        configured.get(
            CONF_PREFERRED_FILTRATION_CATCHUP_START,
            DEFAULT_PREFERRED_FILTRATION_CATCHUP_START,
        )
    ).strip()

    try:
        preferred_catchup_start = time.fromisoformat(preferred_catchup_text)
    except ValueError:
        preferred_catchup_start = time.fromisoformat(
            DEFAULT_PREFERRED_FILTRATION_CATCHUP_START
        )

    filtration_runtime = PoolOSFiltrationRuntime(
        coordinator=coordinator,
        preferred_catchup_start=preferred_catchup_start,
        baselines=pump_baselines,
    )
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
    manual_host = str(configured.get("intellicenter_host", "")).strip()
    physical_command_authority = pump_composition.physical_authority
    pump_speed_session = PoolOSPumpSpeedSessionRuntime(
        pump_composition.pump_speed_session,
        physical_command_authority,
    )
    physical_command_authority.require_automatic_restraint_restoration()
    pool_automatic_control = PoolAutomaticControlSuppression()
    spa_automatic_control = SpaAutomaticControlSuppression()

    def arm_manual_pool_off(suppressed_at: datetime) -> None:
        pool_automatic_control.suppress(
            source=(
                PoolAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST
            ),
            suppressed_at=suppressed_at,
            reason="manual_pool_off_requested_before_delivery",
        )

    def arm_manual_spa_off(suppressed_at: datetime) -> None:
        spa_automatic_control.suppress(
            source=SpaAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
            suppressed_at=suppressed_at,
            reason="manual_spa_off_requested_before_delivery",
        )

    manual_intellicenter = (
        None
        if not manual_host
        else ManualIntelliCenterControl(
            host=manual_host,
            command_authority=physical_command_authority,
            transport=str(configured.get("intellicenter_transport", "tcp")),
            pool_manual_off_requested=arm_manual_pool_off,
            spa_manual_off_requested=arm_manual_spa_off,
        )
    )

    thermal_runtime = PoolOSThermalRuntime(
        coordinator=coordinator,
        manual_intellicenter=manual_intellicenter,
        filtration_runtime=filtration_runtime,
        baselines=pump_baselines,
        evaluator=pump_composition.thermal_evaluator,
        pump_speed_session=pump_speed_session,
    )
    external_change_runtime = PoolOSExternalChangeRuntime(
        hass=hass,
        authority=physical_command_authority,
        thermal_runtime=thermal_runtime,
        pool_automatic_control=pool_automatic_control,
        spa_automatic_control=spa_automatic_control,
    )
    thermal_runtime_orchestrator = pump_composition.thermal_orchestrator
    pool_circulation_ownership = PoolCirculationOwnershipRegistry()
    thermal_automatic_runtime = PoolOSThermalAutomaticRuntime(
        hass=hass,
        coordinator=coordinator,
        thermal_runtime=thermal_runtime,
        orchestrator=thermal_runtime_orchestrator,
        authority=physical_command_authority,
        manual=manual_intellicenter,
        baselines=pump_baselines,
        pump_speed_session=pump_speed_session,
        circulation_ownership=pool_circulation_ownership,
        pool_automatic_control=pool_automatic_control,
        spa_automatic_control=spa_automatic_control,
    )
    filtration_automatic_runtime = PoolOSFiltrationAutomaticRuntime(
        hass=hass,
        coordinator=coordinator,
        filtration_runtime=filtration_runtime,
        thermal_runtime=thermal_runtime,
        ownership=pool_circulation_ownership,
        authority=physical_command_authority,
        manual=manual_intellicenter,
        baselines=pump_baselines,
        pump_speed_session=pump_speed_session,
        pool_automatic_control=pool_automatic_control,
    )
    grid_outage_safety_runtime = PoolOSGridOutageSafetyRuntime(
        hass=hass,
        coordinator=coordinator,
        thermal_runtime=thermal_runtime,
        authority=physical_command_authority,
        manual=manual_intellicenter,
        engine=pump_composition.grid_outage_engine,
    )

    def synchronize_pool_automatic_restraint(_state: object) -> None:
        physical_command_authority.set_pool_automatic_control_suppressed(
            pool_automatic_control.state.suppressed
        )
        thermal_automatic_runtime.driver.restrictive_authority_changed(
            changed_at=datetime.now(UTC)
        )

    def synchronize_spa_automatic_restraint(_state: object) -> None:
        physical_command_authority.set_spa_automatic_control_suppressed(
            spa_automatic_control.state.suppressed
        )
        thermal_automatic_runtime.driver.restrictive_authority_changed(
            changed_at=datetime.now(UTC)
        )

    entry.async_on_unload(
        pool_automatic_control.add_listener(synchronize_pool_automatic_restraint)
    )
    entry.async_on_unload(
        spa_automatic_control.add_listener(synchronize_spa_automatic_restraint)
    )
    thermal_runtime.set_probe_execution_provider(
        thermal_automatic_runtime.driver.probe_execution_evidence
    )
    thermal_runtime.set_spa_session_kind_provider(
        thermal_automatic_runtime.driver.spa_session_kind
    )
    def probe_continuity(
        snapshot: ObservationSnapshot,
    ) -> PoolTemperatureProbeContinuityEvidence:
        outage = thermal_runtime_orchestrator.assessment
        base_reason = physical_command_authority.base_authority_reason
        lifecycle_blocker = None
        if not thermal_automatic_runtime.driver.requested_enabled:
            lifecycle_blocker = "temperature_probe_automatic_execution_disabled"
        elif not thermal_runtime.effective_live_enabled:
            lifecycle_blocker = "temperature_probe_thermal_live_disabled"
        elif thermal_runtime.commissioning_scope is not ThermalLiveCommissioningScope.POOL:
            lifecycle_blocker = "temperature_probe_pool_scope_not_commissioned"
        elif base_reason is not PhysicalAuthorityReason.ALLOWED:
            lifecycle_blocker = f"physical_authority:{base_reason.value}"
        return assess_pool_temperature_probe_continuity(
            generated_at=snapshot.generated_at,
            observations=snapshot.observations,
            prior_grid_disposition=(
                None if outage is None or outage.outage is None else outage.outage.disposition
            ),
            lifecycle_blocker=lifecycle_blocker,
            external_preemption_reason=(
                thermal_runtime_orchestrator.ownership.current_external_preemption_reason(
                    external_change_runtime.latest_batch
                )
            ),
            baselines=pump_baselines,
        )

    thermal_runtime.set_probe_continuity_provider(probe_continuity)
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
        grid_outage_safety_runtime=grid_outage_safety_runtime,
        filtration_automatic_runtime=filtration_automatic_runtime,
        pool_automatic_control=pool_automatic_control,
        spa_automatic_control=spa_automatic_control,
        pump_operating_baselines=pump_baselines,
        pump_speed_session=pump_speed_session,
    )
    coordinator.set_thermal_runtime_refresh(thermal_runtime.refresh)
    def synchronize_pump_session(
        native: NativeIntelliCenterObservationSnapshot,
        transport: NativeIntelliCenterTransportSnapshot,
        connection_generation: int,
    ) -> None:
        special = thermal_automatic_runtime.driver.active_pump_session_purpose()
        outage = thermal_runtime_orchestrator.assessment
        pump_speed_session.synchronize(
            native,
            transport,
            connection_generation=connection_generation,
            probe_active=special is PumpSpeedSessionPurpose.TEMPERATURE_PROBE,
            priming_active=special is PumpSpeedSessionPurpose.PRIMING,
            outage_active=bool(
                outage is not None
                and outage.outage is not None
                and outage.outage.disposition
                is GridOutageDisposition.CONFIRMED_OUTAGE
            ),
        )

    def observe_native_snapshot(
        native: NativeIntelliCenterObservationSnapshot,
        transport: NativeIntelliCenterTransportSnapshot,
        connection_generation: int,
    ) -> None:
        evaluated_at = datetime.now(UTC)

        if not pool_suppression_is_current(
            pool_automatic_control.state,
            evaluated_at=evaluated_at,
            timezone=coordinator.local_timezone,
        ):
            pool_automatic_control.resume(resumed_at=evaluated_at)

        if not spa_suppression_is_current(
            spa_automatic_control.state,
            evaluated_at=evaluated_at,
            timezone=coordinator.local_timezone,
        ):
            spa_automatic_control.resume(resumed_at=evaluated_at)

        synchronize_pump_session(native, transport, connection_generation)
        external_change_runtime.process(native, transport, connection_generation)
        pump_speed_session.apply_external_changes(
            external_change_runtime.latest_batch,
            native,
        )

    coordinator.set_native_snapshot_observer(observe_native_snapshot)
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
        native = coordinator.native_intellicenter_snapshot
        transport_runtime = coordinator.independent_intellicenter_transport
        transport = (
            None if transport_runtime is None else transport_runtime.latest_snapshot
        )
        if native is not None and transport is not None:
            synchronize_pump_session(
                native,
                transport,
                getattr(transport_runtime, "discovery_generation", 0),
            )
        thermal_automatic_runtime.observe(
            snapshot,
            assessment,
            orchestration,
            external_change_runtime.latest_batch,
        )
        filtration_automatic_runtime.observe(
            snapshot,
            orchestration,
            external_changes=external_change_runtime.latest_batch,
        )
        grid_outage_safety_runtime.observe(
            snapshot,
            orchestration,
            external_change_runtime.latest_batch,
        )

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
        filtration_automatic_runtime.orchestration_failed(snapshot, error)
        grid_outage_safety_runtime.orchestration_failed(snapshot, error)

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
    await entry.runtime_data.grid_outage_safety_runtime.async_unload()
    await entry.runtime_data.thermal_automatic_runtime.async_unload()
    await entry.runtime_data.filtration_automatic_runtime.async_unload()
    entry.runtime_data.thermal_runtime_orchestrator.unload(
        unloaded_at=datetime.now(UTC)
    )
    await entry.runtime_data.coordinator.async_prepare_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if entry.runtime_data.manual_intellicenter is not None:
        await entry.runtime_data.manual_intellicenter.async_stop()
    await entry.runtime_data.coordinator.async_stop_independent_intellicenter()
    return unloaded
