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
from .manual_intellicenter import ManualIntelliCenterCommandError


HEAT_MODE_OFF = "Off"
HEAT_MODE_SOLAR = "Solar"
HEAT_MODE_GAS = "Gas"
HEAT_MODE_SOLAR_PREFERRED = "Solar Preferred"

HEAT_MODE_OPTIONS = (
    HEAT_MODE_OFF,
    HEAT_MODE_SOLAR,
    HEAT_MODE_GAS,
    HEAT_MODE_SOLAR_PREFERRED,
)

_NATIVE_HEATER_BY_DIRECT_MODE = {
    HEAT_MODE_OFF: "00000",
    HEAT_MODE_GAS: "H0001",
    HEAT_MODE_SOLAR: "H0002",
}

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


HEAT_MODE_DESCRIPTIONS = (
    PoolOSHeatModeDescription(
        key="pool",
        name="Pool Heat Mode",
        body_objnam="B1101",
        heater_id_concept="pool.raw_heater_id",
        default_mode=HEAT_MODE_SOLAR,
        icon="mdi:pool-thermometer",
    ),
    PoolOSHeatModeDescription(
        key="hot_tub",
        name="Hot Tub Heat Mode",
        body_objnam="B1202",
        heater_id_concept="spa.raw_heater_id",
        default_mode=HEAT_MODE_SOLAR_PREFERRED,
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
        self._requested_mode = description.default_mode

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
            self._requested_mode = previous.state

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

        return self._requested_mode

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

        if option not in HEAT_MODE_OPTIONS:
            raise ValueError(f"unsupported heat mode: {option}")

        if option == HEAT_MODE_SOLAR_PREFERRED:
            # This is PoolOS policy intent, not a native Pentair Solar Preferred selection.
            # Autonomous source selection remains intentionally disabled.
            self._requested_mode = option
            self.async_write_ha_state()
            return

        manual = self._runtime.manual_intellicenter

        if manual is None or not manual.available:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is unavailable"
            )

        heater_objnam = _NATIVE_HEATER_BY_DIRECT_MODE[option]

        await manual.async_set_body_heat_source(
            self._description.body_objnam,
            heater_objnam,
        )

        # Requested mode is PoolOS operator intent. Effective heat source
        # remains native-authoritative and is never optimistically mutated.
        self._requested_mode = option
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose requested policy separately from effective native source."""

        manual = self._runtime.manual_intellicenter

        return {
            "body_objnam": self._description.body_objnam,
            "requested_heat_mode": self._requested_mode,
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS requested heat-mode selectors."""

    del hass
    runtime = entry.runtime_data

    async_add_entities(
        PoolOSHeatModeSelect(
            runtime.coordinator,
            entry,
            description,
        )
        for description in HEAT_MODE_DESCRIPTIONS
    )
