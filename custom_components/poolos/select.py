"""PoolOS requested heat-mode selectors for Pool and Hot Tub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_thermal import (
    HEAT_MODE_GAS,
    HEAT_MODE_OFF,
    HEAT_MODE_OPTIONS,
    HEAT_MODE_SOLAR,
    HEAT_MODE_SOLAR_PREFERRED,
    async_request_heat_mode,
    requested_heat_mode,
)
from poolos.integration import ThermalBody
from poolos.thermal_live_execution import ThermalLiveCommissioningScope
from poolos.thermal_runtime_assessment import ThermalRequestedMode

__all__ = [
    "HEAT_MODE_GAS",
    "HEAT_MODE_OFF",
    "HEAT_MODE_OPTIONS",
    "HEAT_MODE_SOLAR",
    "HEAT_MODE_SOLAR_PREFERRED",
]


_EFFECTIVE_SOURCE_BY_HEATER = {
    "00000": "Off",
    "H0001": "Gas",
    "H0002": "Solar",
}


@dataclass(frozen=True, slots=True)
class PoolOSHeatModeDescription:
    """Describe one body-specific requested heat-mode selector."""

    key: str
    name: str
    body_objnam: str
    heater_id_concept: str
    default_mode: str
    icon: str
    body: ThermalBody


HEAT_MODE_DESCRIPTIONS = (
    PoolOSHeatModeDescription(
        key="pool",
        name="Pool Heat Mode",
        body_objnam="B1101",
        heater_id_concept="pool.raw_heater_id",
        default_mode=HEAT_MODE_SOLAR,
        icon="mdi:pool-thermometer",
        body=ThermalBody.POOL,
    ),
    PoolOSHeatModeDescription(
        key="hot_tub",
        name="Hot Tub Heat Mode",
        body_objnam="B1202",
        heater_id_concept="spa.raw_heater_id",
        default_mode=HEAT_MODE_SOLAR_PREFERRED,
        icon="mdi:hot-tub",
        body=ThermalBody.HOT_TUB,
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


class PoolOSHeatModeSelect(
    CoordinatorEntity[PoolOSCoordinator],
    RestoreEntity,
    SelectEntity,
):
    """Represent user-requested PoolOS heat policy for one body."""

    _attr_has_entity_name = True
    _attr_options = list(HEAT_MODE_OPTIONS)

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSHeatModeDescription,
    ) -> None:
        super().__init__(coordinator)

        self._runtime = entry.runtime_data
        self._description = description
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_"
            f"{description.key}_heat_mode"
        )
        self._attr_device_info = {
            "identifiers": {
                (DOMAIN, f"{entry.entry_id}_native_intellicenter")
            },
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "PoolOS Requested Heat Mode",
            "sw_version": INTEGRATION_VERSION,
        }

    async def async_added_to_hass(self) -> None:
        """Restore requested PoolOS mode without commanding equipment."""

        await super().async_added_to_hass()

        previous = await self.async_get_last_state()

        if (
            previous is not None
            and previous.state in HEAT_MODE_OPTIONS
        ):
            requested = previous.state
        else:
            requested = self._description.default_mode
        self._runtime.thermal_runtime.set_requested_mode(
            self._description.body,
            ThermalRequestedMode(requested),
            publish=False,
        )

    @property
    def available(self) -> bool:
        """Require native body truth; writes independently fail closed."""

        snapshot = self.coordinator.native_intellicenter_snapshot

        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and _native_observation(
                self.coordinator,
                self._description.heater_id_concept,
            )
            is not None
        )

    @property
    def current_option(self) -> str:
        """Return persistent user-requested PoolOS heat mode."""

        return requested_heat_mode(
            self._runtime,
            self._description.body,
        ).value

    @property
    def effective_native_heater_id(self) -> str | None:
        """Return authoritative native IntelliCenter HEATER selection."""

        value = _native_value(
            self.coordinator,
            self._description.heater_id_concept,
        )

        return value if isinstance(value, str) else None

    @property
    def effective_heat_source(self) -> str | None:
        """Normalize authoritative native HEATER selection."""

        heater_id = self.effective_native_heater_id

        if heater_id is None:
            return None

        return _EFFECTIVE_SOURCE_BY_HEATER.get(
            heater_id,
            f"Unknown ({heater_id})",
        )

    async def async_select_option(self, option: str) -> None:
        """Set requested mode, commanding only commissioned direct modes."""

        await async_request_heat_mode(
            self._runtime,
            self._description.body,
            option,
        )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose requested policy separately from effective native source."""

        manual = self._runtime.manual_intellicenter

        return {
            "body_objnam": self._description.body_objnam,
            "requested_heat_mode": self.current_option,
            "default_heat_mode": self._description.default_mode,
            "effective_heat_source": self.effective_heat_source,
            "effective_native_heater_id": self.effective_native_heater_id,
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "solar_preferred_owner": "poolos",
            "pentair_solar_preferred_used": False,
            "solar_preferred_autonomous_delivery_enabled": False,
            "direct_htmode_write_enabled": False,
            "configuration_independent_of_body_activity": True,
            "configuration_activates_body": False,
            "allowed_native_heater_ids": (
                "00000",
                "H0001",
                "H0002",
            ),
        }


_COMMISSIONING_SCOPE_OPTION = {
    "Disabled": ThermalLiveCommissioningScope.DISABLED,
    "Pool": ThermalLiveCommissioningScope.POOL,
    "Hot Tub": ThermalLiveCommissioningScope.HOT_TUB,
}


class PoolOSThermalCommissioningScopeSelect(RestoreEntity, SelectEntity):
    """Configure one-body dry-run scope without executing any plan."""

    _attr_has_entity_name = True
    _attr_name = "Thermal Commissioning Scope"
    _attr_icon = "mdi:shield-account-outline"
    _attr_options = list(_COMMISSIONING_SCOPE_OPTION)

    def __init__(self, entry: ConfigEntry[PoolOSRuntimeData]) -> None:
        self._runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_thermal_commissioning_scope"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is not None and previous.state in _COMMISSIONING_SCOPE_OPTION:
            self._runtime.thermal_runtime.set_commissioning_scope(
                _COMMISSIONING_SCOPE_OPTION[previous.state]
            )
            self._runtime.thermal_automatic_runtime.authority_configuration_changed()

    @property
    def current_option(self) -> str:
        scope = self._runtime.thermal_runtime.commissioning_scope
        return next(
            label for label, value in _COMMISSIONING_SCOPE_OPTION.items() if value is scope
        )

    async def async_select_option(self, option: str) -> None:
        if option not in _COMMISSIONING_SCOPE_OPTION:
            raise ValueError(f"unsupported thermal commissioning scope: {option}")
        self._runtime.thermal_runtime.set_commissioning_scope(
            _COMMISSIONING_SCOPE_OPTION[option]
        )
        self._runtime.thermal_automatic_runtime.authority_configuration_changed()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "configuration_only": True,
            "automatic_execution_driver_enabled": (
                self._runtime.thermal_automatic_runtime.enabled
            ),
            "command_delivery_performed": False,
            "authority": "none",
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS requested heat-mode selectors."""

    del hass
    runtime = entry.runtime_data

    async_add_entities(
        [
            *(
                PoolOSHeatModeSelect(
                    runtime.coordinator,
                    entry,
                    description,
                )
                for description in HEAT_MODE_DESCRIPTIONS
            ),
            PoolOSThermalCommissioningScopeSelect(entry),
        ]
    )
