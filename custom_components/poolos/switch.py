"""Native PoolOS manual IntelliCenter feature switches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError
from .manual_thermal import (
    HEAT_MODE_OFF,
    HEAT_MODE_SOLAR,
    async_request_heat_mode,
    requested_heat_mode,
)
from poolos.integration import ThermalBody
from poolos.physical_command_authority import (
    PhysicalCommandRequest,
    PhysicalRequestSource,
)
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppressionSource,
    pool_suppression_is_current,
    spa_suppression_is_current,
)
from poolos.thermal_runtime_assessment import ThermalRequestedMode


@dataclass(frozen=True, slots=True)
class PoolOSSwitchDescription:
    """Describe one explicitly controllable IntelliCenter feature."""

    key: str
    name: str
    objnam: str
    active_concept: str
    icon: str
    required_parent_concept: str | None = None
    required_parent_name: str | None = None


SWITCH_DESCRIPTIONS = (
    PoolOSSwitchDescription(
        key="jets",
        name="Jets / Bubbles",
        objnam="C0003",
        active_concept="jets.active",
        icon="mdi:weather-windy",
        required_parent_concept="spa.active",
        required_parent_name="Spa",
    ),
    PoolOSSwitchDescription(
        key="slide",
        name="Water Slide",
        objnam="C0004",
        active_concept="slide.active",
        icon="mdi:slide",
    ),
    PoolOSSwitchDescription(
        key="waterfall",
        name="Spillway",
        objnam="FTR01",
        active_concept="waterfall.active",
        icon="mdi:waves-arrow-down",
        required_parent_concept="pool.active",
        required_parent_name="Pool",
    ),
)


def _native_observation(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> Any:
    snapshot = coordinator.native_intellicenter_snapshot
    if snapshot is None:
        return None

    for observation in snapshot.observations:
        if observation.observation_id == concept:
            return observation

    return None


def _native_value(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> Any:
    observation = _native_observation(coordinator, concept)
    return None if observation is None else observation.value


class PoolOSNativeIntelliCenterSolarSwitch(
    CoordinatorEntity[PoolOSCoordinator],
    SwitchEntity,
):
    """Represent explicit native Pool Solar heat-source selection."""

    _attr_has_entity_name = True
    _attr_name = "Solar"
    _attr_icon = "mdi:solar-power"

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_pool_solar_switch"
        )
        self._attr_device_info = {
            "identifiers": {
                (DOMAIN, f"{entry.entry_id}_native_intellicenter")
            },
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Solar Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Require native Solar truth and manual command delivery."""

        snapshot = self.coordinator.native_intellicenter_snapshot
        manual = self._runtime.manual_intellicenter

        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and _native_observation(
                self.coordinator,
                "solar.active",
            )
            is not None
            and manual is not None
            and manual.available
        )

    @property
    def is_on(self) -> bool | None:
        """Return confirmed native Solar state."""

        value = _native_value(
            self.coordinator,
            "solar.active",
        )
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Explicitly select Solar for the active Pool body."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        pool_active = _native_value(
            self.coordinator,
            "pool.active",
        )

        if pool_active is not True:
            raise ManualIntelliCenterCommandError(
                "Solar cannot be turned on unless Pool is active"
            )

        if _native_value(self.coordinator, "pool.raw_heater_id") is None:
            raise ManualIntelliCenterCommandError(
                "effective Pool heat source is unavailable"
            )

        await async_request_heat_mode(
            self._runtime,
            ThermalBody.POOL,
            HEAT_MODE_SOLAR,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Explicitly deselect Solar without changing Pool circulation."""

        del kwargs

        native_heater = _native_value(
            self.coordinator,
            "pool.raw_heater_id",
        )
        if native_heater in {"00000", "H0001"}:
            return
        if native_heater != "H0002":
            raise ManualIntelliCenterCommandError(
                "effective Pool heat source is unavailable or unknown"
            )

        requested = requested_heat_mode(
            self._runtime,
            ThermalBody.POOL,
        )
        if requested is ThermalRequestedMode.SOLAR_PREFERRED:
            raise ManualIntelliCenterCommandError(
                "Solar OFF cannot replace a Solar Preferred policy request"
            )
        if requested is not ThermalRequestedMode.SOLAR:
            raise ManualIntelliCenterCommandError(
                "Solar OFF conflicts with the current requested Pool heat mode"
            )

        await async_request_heat_mode(
            self._runtime,
            ThermalBody.POOL,
            HEAT_MODE_OFF,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded native Solar command semantics."""

        manual = self._runtime.manual_intellicenter

        return {
            "pool_body_objnam": "B1101",
            "solar_heater_objnam": "H0002",
            "off_heater_objnam": "00000",
            "canonical_concept": "solar.active",
            "operator_intent_surface": "pool_heat_mode",
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
            "optimistic": False,
            "required_parent_concept": "pool.active",
            "direct_htmode_write_enabled": False,
            "arbitrary_heater_selection_enabled": False,
        }


class PoolOSThermalLiveExecutionSwitch(RestoreEntity, SwitchEntity):
    """Persist commissioned desired readiness; never restore a live session."""

    _attr_has_entity_name = True
    _attr_name = "Thermal Live Execution"
    _attr_icon = "mdi:shield-lock-outline"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_thermal_live_execution"

    @property
    def is_on(self) -> bool:
        return self._runtime.thermal_runtime.effective_live_enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state == "on":
            self._runtime.thermal_runtime.set_effective_live_enabled(True)
            self._runtime.thermal_automatic_runtime.authority_configuration_changed()

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.thermal_runtime.set_effective_live_enabled(True)
        automatic = getattr(self._runtime, "thermal_automatic_runtime", None)
        if automatic is not None:
            automatic.authority_configuration_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.thermal_runtime.set_effective_live_enabled(False)
        automatic = getattr(self._runtime, "thermal_automatic_runtime", None)
        if automatic is not None:
            automatic.authority_configuration_changed()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "commissioned_desired_state_persists_across_restart": True,
            "physical_session_ownership_restored": False,
            "configuration_only": True,
            "automatic_execution_driver_enabled": bool(
                getattr(
                    getattr(self._runtime, "thermal_automatic_runtime", None),
                    "enabled",
                    False,
                )
            ),
            "command_delivery_performed": False,
            "manual_controls_unchanged": True,
            "authority": "none",
        }


class PoolOSThermalAutomaticExecutionSwitch(RestoreEntity, SwitchEntity):
    """Persist desired automation while runtime ownership always starts empty."""

    _attr_has_entity_name = True
    _attr_name = "Automatic Thermal Execution"
    _attr_icon = "mdi:robot-off-outline"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_automatic_thermal_execution"

    @property
    def is_on(self) -> bool:
        return self._runtime.thermal_automatic_runtime.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state == "on":
            self._runtime.thermal_automatic_runtime.set_enabled(True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.thermal_automatic_runtime.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.thermal_automatic_runtime.set_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self._runtime.thermal_automatic_runtime.diagnostics(),
            "commissioned_desired_state_persists_across_restart": True,
            "physical_session_ownership_restored": False,
            "thermal_live_gate_is_independent": True,
            "cached_candidate_executes_on_enable": False,
            "fresh_authoritative_epoch_required": True,
        }


class PoolOSFiltrationAutomaticExecutionSwitch(RestoreEntity, SwitchEntity):
    """Persist desired filtration automation without restoring ownership."""

    _attr_has_entity_name = True
    _attr_name = "Automatic Filtration Execution"
    _attr_icon = "mdi:pool"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_automatic_filtration_execution"

    @property
    def is_on(self) -> bool:
        return self._runtime.filtration_automatic_runtime.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state == "on":
            self._runtime.filtration_automatic_runtime.set_enabled(True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.filtration_automatic_runtime.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.filtration_automatic_runtime.set_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self._runtime.filtration_automatic_runtime.diagnostics(),
            "commissioned_desired_state_persists_across_restart": True,
            "physical_session_ownership_restored": False,
            "cached_candidate_executes_on_enable": False,
            "fresh_authoritative_epoch_required": True,
            "filtration_accounting_remains_command_free": True,
        }


class PoolOSGridOutagePhysicalSafetySwitch(SwitchEntity):
    """Independent restart-reset gate for confirmed-outage reductions."""

    _attr_has_entity_name = True
    _attr_name = "Grid Outage Physical Safety"
    _attr_icon = "mdi:transmission-tower-off"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_grid_outage_physical_safety"

    @property
    def is_on(self) -> bool:
        return self._runtime.grid_outage_safety_runtime.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.grid_outage_safety_runtime.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.grid_outage_safety_runtime.set_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._runtime.grid_outage_safety_runtime.diagnostics()


class PoolOSMaintenanceModeSwitch(RestoreEntity, SwitchEntity):
    """Persistent global deny for every PoolOS physical mutation."""

    _attr_name = "PoolOS Maintenance Mode"
    _attr_icon = "mdi:tools"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_maintenance_mode"

    async def async_added_to_hass(self) -> None:
        """Resolve persisted state; authority remains denied until this completes."""

        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        enabled = previous is not None and previous.state == "on"
        self._runtime.physical_command_authority.resolve_maintenance(enabled)
        pump_session = getattr(self._runtime, "pump_speed_session", None)
        if pump_session is not None:
            pump_session.session.reset_currentness("maintenance_state_restored")
            pump_session.synchronize_authority()
        if enabled:
            self._runtime.external_change_runtime.maintenance_entered()

    @property
    def available(self) -> bool:
        return self._runtime.physical_command_authority.maintenance_resolved

    @property
    def is_on(self) -> bool:
        # Unresolved startup state is effectively denied and is never exposed
        # as a transient permissive OFF state.
        return self._runtime.physical_command_authority.maintenance_mode is not False

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.physical_command_authority.resolve_maintenance(True)
        pump_session = getattr(self._runtime, "pump_speed_session", None)
        if pump_session is not None:
            pump_session.session.reset_currentness("maintenance_entered")
            pump_session.synchronize_authority()
        self._runtime.external_change_runtime.maintenance_entered()
        self._publish_authority_change()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.physical_command_authority.resolve_maintenance(False)
        pump_session = getattr(self._runtime, "pump_speed_session", None)
        if pump_session is not None:
            pump_session.session.reset_currentness("maintenance_exited")
            pump_session.synchronize_authority()
        self._runtime.external_change_runtime.maintenance_exited()
        self._publish_authority_change()
        self.async_write_ha_state()

    def _publish_authority_change(self) -> None:
        """Reevaluate entities from current truth without replaying a request."""

        coordinator = getattr(self._runtime, "coordinator", None)
        publish = getattr(coordinator, "async_update_listeners", None)
        if callable(publish):
            publish()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **dict(
                self._runtime.physical_command_authority.diagnostics(
                    now=datetime.now(UTC)
                )
            ),
            "global_physical_command_deny": self.is_on,
            "thermal_live_execution_distinct": True,
            "observation_continues": True,
            "parity_continues": True,
            "commands_replayed_on_exit": False,
            "physical_state_restored_on_exit": False,
        }


class PoolOSPoolAutonomousControlSwitch(RestoreEntity, SwitchEntity):
    """Persistent human-Off restraint; changing it never commands equipment."""

    _attr_name = "PoolOS Autonomous Pool Control"
    _attr_icon = "mdi:hand-back-right-off"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_autonomous_pool_control"

    async def async_added_to_hass(self) -> None:
        """Restore only the restraint, never execution or equipment ownership."""

        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if (
            previous is not None
            and previous.state == "off"
            and not self._runtime.pool_automatic_control.state.suppressed
        ):
            source_value = previous.attributes.get(
                "pool_manual_off_suppression_source"
            )
            try:
                source = PoolAutomaticControlSuppressionSource(str(source_value))
            except ValueError:
                source = PoolAutomaticControlSuppressionSource.RESTORED
            at_value = previous.attributes.get("pool_manual_off_suppression_at")
            try:
                suppressed_at = datetime.fromisoformat(str(at_value))
                if suppressed_at.tzinfo is None:
                    raise ValueError
            except (TypeError, ValueError):
                suppressed_at = datetime.now(UTC)
            reason = str(
                previous.attributes.get("pool_manual_off_suppression_reason")
                or "restored_manual_pool_off_suppression"
            )
            restored = self._runtime.pool_automatic_control.suppress(
                source=source,
                suppressed_at=suppressed_at,
                reason=reason,
            )
            if not pool_suppression_is_current(
                restored,
                evaluated_at=datetime.now(UTC),
                timezone=self._runtime.coordinator.local_timezone,
            ):
                self._runtime.pool_automatic_control.resume(
                    resumed_at=datetime.now(UTC)
                )
        self._runtime.physical_command_authority.resolve_pool_automatic_control_suppressed(
            self._runtime.pool_automatic_control.state.suppressed
        )
        self.async_on_remove(
            self._runtime.pool_automatic_control.add_listener(
                lambda _state: self.async_write_ha_state()
            )
        )

    @property
    def is_on(self) -> bool:
        """On means autonomous Pool control is eligible for fresh evaluation."""

        return not self._runtime.pool_automatic_control.state.suppressed

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Explicitly resume future automation without issuing a command."""

        del kwargs
        self._runtime.pool_automatic_control.resume(resumed_at=datetime.now(UTC))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Proactively restrain future automatic Pool mutations."""

        del kwargs
        self._runtime.pool_automatic_control.suppress(
            source=PoolAutomaticControlSuppressionSource.OPERATOR_RESTRAINT,
            suppressed_at=datetime.now(UTC),
            reason="operator_disabled_autonomous_pool_control",
        )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **dict(self._runtime.pool_automatic_control.diagnostics()),
            "resume_issues_equipment_command": False,
            "resume_creates_ownership": False,
            "manual_controls_remain_available": True,
            "baseline_off_creates_suppression": False,
            "suppression_persists_across_restart": True,
            "offline_operator_off_detection_possible": False,
        }


class PoolOSSpaAutonomousControlSwitch(RestoreEntity, SwitchEntity):
    """Persistent human-Off restraint scoped only to automatic Spa work."""

    _attr_name = "PoolOS Autonomous Hot Tub Control"
    _attr_icon = "mdi:hot-tub"

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_autonomous_hot_tub_control"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if (
            previous is not None
            and previous.state == "off"
            and not self._runtime.spa_automatic_control.state.suppressed
        ):
            source_value = previous.attributes.get(
                "spa_manual_off_suppression_source"
            )
            try:
                source = SpaAutomaticControlSuppressionSource(str(source_value))
            except ValueError:
                source = SpaAutomaticControlSuppressionSource.RESTORED
            at_value = previous.attributes.get("spa_manual_off_suppression_at")
            try:
                suppressed_at = datetime.fromisoformat(str(at_value))
                if suppressed_at.tzinfo is None:
                    raise ValueError
            except (TypeError, ValueError):
                suppressed_at = datetime.now(UTC)
            reason = str(
                previous.attributes.get("spa_manual_off_suppression_reason")
                or "restored_manual_spa_off_suppression"
            )
            restored = self._runtime.spa_automatic_control.suppress(
                source=source,
                suppressed_at=suppressed_at,
                reason=reason,
            )
            if not spa_suppression_is_current(
                restored,
                evaluated_at=datetime.now(UTC),
                timezone=self._runtime.coordinator.local_timezone,
            ):
                self._runtime.spa_automatic_control.resume(
                    resumed_at=datetime.now(UTC)
                )
        self._runtime.physical_command_authority.resolve_spa_automatic_control_suppressed(
            self._runtime.spa_automatic_control.state.suppressed
        )
        self.async_on_remove(
            self._runtime.spa_automatic_control.add_listener(
                lambda _state: self.async_write_ha_state()
            )
        )

    @property
    def is_on(self) -> bool:
        return not self._runtime.spa_automatic_control.state.suppressed

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.spa_automatic_control.resume(resumed_at=datetime.now(UTC))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        self._runtime.spa_automatic_control.suppress(
            source=SpaAutomaticControlSuppressionSource.OPERATOR_RESTRAINT,
            suppressed_at=datetime.now(UTC),
            reason="operator_disabled_autonomous_spa_control",
        )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **dict(self._runtime.spa_automatic_control.diagnostics()),
            "resume_issues_equipment_command": False,
            "resume_creates_ownership": False,
            "manual_controls_remain_available": True,
            "baseline_off_creates_suppression": False,
            "suppression_persists_across_restart": True,
            "offline_operator_off_detection_possible": False,
        }


class PoolOSNativeIntelliCenterSwitch(
    CoordinatorEntity[PoolOSCoordinator],
    SwitchEntity,
):
    """Represent one explicit manual IntelliCenter feature switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._description = description
        self._safety_interlock_off_pending = False
        self._safety_interlock_blocked_reason: str | None = None

        self._attr_name = description.name
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_{description.key}_switch"
        )
        self._attr_icon = description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Feature Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Return whether native truth and manual command delivery are available."""

        snapshot = self.coordinator.native_intellicenter_snapshot
        manual = self._runtime.manual_intellicenter

        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and _native_observation(
                self.coordinator,
                self._description.active_concept,
            )
            is not None
            and manual is not None
            and manual.available
        )

    @property
    def is_on(self) -> bool | None:
        """Return confirmed native IntelliCenter state."""

        value = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Explicitly turn the feature on."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        parent_concept = self._description.required_parent_concept
        if parent_concept is not None:
            parent_active = _native_value(
                self.coordinator,
                parent_concept,
            )
            if parent_active is not True:
                parent_name = (
                    self._description.required_parent_name
                    or parent_concept
                )
                raise ManualIntelliCenterCommandError(
                    f"{self._description.name} cannot be turned on "
                    f"unless {parent_name} is active"
                )

        await manual.async_set_circuit_state(
            self._description.objnam,
            True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Explicitly turn the feature off."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_circuit_state(
            self._description.objnam,
            False,
        )

    async def _async_enforce_parent_interlock(self) -> None:
        """Force the child feature off if its required parent is not active."""

        parent_concept = self._description.required_parent_concept
        if parent_concept is None:
            return

        child_active = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        parent_active = _native_value(
            self.coordinator,
            parent_concept,
        )

        if child_active is not True:
            self._safety_interlock_off_pending = False
            self._safety_interlock_blocked_reason = None
            return

        if parent_active is True:
            self._safety_interlock_off_pending = False
            self._safety_interlock_blocked_reason = None
            return

        if self._safety_interlock_off_pending:
            return

        manual = self._runtime.manual_intellicenter
        if manual is None or not manual.available:
            self._safety_interlock_blocked_reason = "manual_transport_unavailable"
            return

        request = self._safety_interlock_request()
        decision = self._runtime.physical_command_authority.assess(request)
        if not decision.allowed:
            self._safety_interlock_blocked_reason = decision.reason.value
            return

        self._safety_interlock_blocked_reason = None
        self._safety_interlock_off_pending = True

        try:
            await manual.async_set_circuit_state(
                self._description.objnam,
                False,
                request_source=PhysicalRequestSource.SAFETY_INTERLOCK,
            )
        except ManualIntelliCenterCommandError:
            self._safety_interlock_off_pending = False
            decision = self._runtime.physical_command_authority.assess(request)
            if not decision.allowed:
                self._safety_interlock_blocked_reason = decision.reason.value
                return
            raise

    def _safety_interlock_request(self) -> PhysicalCommandRequest:
        return PhysicalCommandRequest(
            operation="circuit_active",
            target=self._description.objnam,
            source=PhysicalRequestSource.SAFETY_INTERLOCK,
            requested_value=False,
        )

    def _handle_coordinator_update(self) -> None:
        """Enforce safety invariants whenever fresh native state is published."""

        parent_concept = self._description.required_parent_concept

        if parent_concept is not None:
            child_active = _native_value(
                self.coordinator,
                self._description.active_concept,
            )
            parent_active = _native_value(
                self.coordinator,
                parent_concept,
            )

            if child_active is not True or parent_active is True:
                self._safety_interlock_off_pending = False
                self._safety_interlock_blocked_reason = None
            elif not self._safety_interlock_off_pending:
                manual = self._runtime.manual_intellicenter
                request = self._safety_interlock_request()
                decision = self._runtime.physical_command_authority.assess(request)
                if manual is None or not manual.available:
                    self._safety_interlock_blocked_reason = (
                        "manual_transport_unavailable"
                    )
                elif not decision.allowed:
                    self._safety_interlock_blocked_reason = decision.reason.value
                else:
                    self._safety_interlock_blocked_reason = None
                    self.hass.async_create_task(
                        self._async_enforce_parent_interlock(),
                        (
                            "PoolOS safety interlock "
                            f"{self._description.key} parent loss"
                        ),
                    )

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded authority and command-path diagnostics."""

        manual = self._runtime.manual_intellicenter

        return {
            "circuit_objnam": self._description.objnam,
            "canonical_concept": self._description.active_concept,
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
            "optimistic": False,
            "required_parent_concept": (
                self._description.required_parent_concept
            ),
            "required_parent_name": self._description.required_parent_name,
            "safety_interlock_delivery_enabled": (
                self._description.required_parent_concept is not None
            ),
            "safety_interlock_off_pending": (
                self._safety_interlock_off_pending
            ),
            "safety_interlock_blocked_reason": (
                self._safety_interlock_blocked_reason
            ),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS native manual feature switches."""

    del hass
    runtime = entry.runtime_data

    async_add_entities(
        [
            *(
                PoolOSNativeIntelliCenterSwitch(
                    runtime.coordinator,
                    entry,
                    description,
                )
                for description in SWITCH_DESCRIPTIONS
            ),
            PoolOSNativeIntelliCenterSolarSwitch(
                runtime.coordinator,
                entry,
            ),
            PoolOSThermalLiveExecutionSwitch(entry),
            PoolOSThermalAutomaticExecutionSwitch(entry),
            PoolOSFiltrationAutomaticExecutionSwitch(entry),
            PoolOSGridOutagePhysicalSafetySwitch(entry),
            PoolOSMaintenanceModeSwitch(entry),
            PoolOSPoolAutonomousControlSwitch(entry),
            PoolOSSpaAutonomousControlSwitch(entry),
        ]
    )
