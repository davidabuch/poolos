"""Native PoolOS manual Pool and Spa climate entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError


@dataclass(frozen=True, slots=True)
class PoolOSClimateDescription:
    """Describe one PoolOS body thermostat."""

    key: str
    name: str
    body_objnam: str
    active_concept: str
    temperature_concept: str
    target_concept: str
    heating_demand_concept: str
    icon: str


CLIMATE_DESCRIPTIONS = (
    PoolOSClimateDescription(
        key="pool",
        name="Pool Thermostat",
        body_objnam="B1101",
        active_concept="pool.active",
        temperature_concept="pool.temperature",
        target_concept="pool.target_temperature",
        heating_demand_concept="pool.heating_demand_active",
        icon="mdi:pool-thermometer",
    ),
    PoolOSClimateDescription(
        key="spa",
        name="Hot Tub Thermostat",
        body_objnam="B1202",
        active_concept="spa.active",
        temperature_concept="spa.temperature",
        target_concept="spa.target_temperature",
        heating_demand_concept="spa.heating_demand_active",
        icon="mdi:hot-tub",
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


class PoolOSNativeClimate(
    CoordinatorEntity[PoolOSCoordinator],
    ClimateEntity,
):
    """Represent one native IntelliCenter Pool/Spa thermostat."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = 40
    _attr_max_temp = 104
    _attr_target_temperature_step = 1

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSClimateDescription,
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_{description.key}_thermostat"
        )
        self._attr_icon = description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Climate Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Return whether observation and manual control are available."""

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
            and _native_observation(
                self.coordinator,
                self._description.temperature_concept,
            )
            is not None
            and _native_observation(
                self.coordinator,
                self._description.target_concept,
            )
            is not None
            and manual is not None
            and manual.available
        )

    @property
    def current_temperature(self) -> float | None:
        """Return native authoritative body temperature."""

        value = _native_value(
            self.coordinator,
            self._description.temperature_concept,
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @property
    def target_temperature(self) -> float | None:
        """Return native authoritative heating target."""

        value = _native_value(
            self.coordinator,
            self._description.target_concept,
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @property
    def hvac_mode(self) -> HVACMode:
        """Map IntelliCenter body activity to thermostat Off/Heat."""

        active = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        return HVACMode.HEAT if active is True else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Expose actual heating demand independently of body activity."""

        active = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        heating = _native_value(
            self.coordinator,
            self._description.heating_demand_concept,
        )

        if active is not True:
            return HVACAction.OFF
        if heating is True:
            return HVACAction.HEATING
        return HVACAction.IDLE

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Explicitly turn Pool/Spa circulation on or off."""

        if hvac_mode not in self.hvac_modes:
            raise ValueError(f"unsupported HVAC mode: {hvac_mode}")

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_body_active(
            self._description.body_objnam,
            hvac_mode is HVACMode.HEAT,
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the native IntelliCenter heating target."""

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if isinstance(temperature, bool) or not isinstance(
            temperature,
            (int, float),
        ):
            raise ValueError("temperature must be numeric")

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_heating_setpoint(
            self._description.body_objnam,
            temperature,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded authority and command-path diagnostics."""

        manual = self._runtime.manual_intellicenter
        return {
            "body_objnam": self._description.body_objnam,
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS native manual climate entities."""

    del hass
    runtime = entry.runtime_data

    async_add_entities(
        PoolOSNativeClimate(
            runtime.coordinator,
            entry,
            description,
        )
        for description in CLIMATE_DESCRIPTIONS
    )
