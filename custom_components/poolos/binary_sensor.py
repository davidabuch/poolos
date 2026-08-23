"""Read-only native IntelliCenter binary sensors for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator


@dataclass(frozen=True, slots=True)
class PoolOSNativeBinarySensorDescription:
    """Describe one native IntelliCenter boolean observation."""

    concept: str
    name: str
    icon: str | None = None


NATIVE_BINARY_SENSORS: tuple[PoolOSNativeBinarySensorDescription, ...] = (
    PoolOSNativeBinarySensorDescription(
        "heater.active",
        "Heater Active",
        "mdi:fire",
    ),
    PoolOSNativeBinarySensorDescription(
        "jets.active",
        "Jets Active",
        "mdi:weather-windy",
    ),
    PoolOSNativeBinarySensorDescription(
        "pool.active",
        "Pool Active",
        "mdi:pool",
    ),
    PoolOSNativeBinarySensorDescription(
        "pool.command_active",
        "Pool Command Active",
        "mdi:toggle-switch",
    ),
    PoolOSNativeBinarySensorDescription(
        "pool.heating_demand_active",
        "Pool Heating Demand",
        "mdi:heat-wave",
    ),
    PoolOSNativeBinarySensorDescription(
        "pool_light.active",
        "Pool Light Active",
        "mdi:lightbulb",
    ),
    PoolOSNativeBinarySensorDescription(
        "slide.active",
        "Slide Active",
        "mdi:slide",
    ),
    PoolOSNativeBinarySensorDescription(
        "solar.active",
        "Solar Active",
        "mdi:solar-power",
    ),
    PoolOSNativeBinarySensorDescription(
        "spa.active",
        "Spa Active",
        "mdi:hot-tub",
    ),
    PoolOSNativeBinarySensorDescription(
        "spa.command_active",
        "Spa Command Active",
        "mdi:toggle-switch",
    ),
    PoolOSNativeBinarySensorDescription(
        "spa.heating_demand_active",
        "Spa Heating Demand",
        "mdi:heat-wave",
    ),
    PoolOSNativeBinarySensorDescription(
        "waterfall.active",
        "Waterfall Active",
        "mdi:waves-arrow-down",
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


class PoolOSNativeIntelliCenterBinarySensor(
    CoordinatorEntity[PoolOSCoordinator],
    BinarySensorEntity,
):
    """Expose one canonical native IntelliCenter boolean observation."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSNativeBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_name = description.name
        key = description.concept.replace(".", "_")
        self._attr_unique_id = f"{entry.entry_id}_native_intellicenter_{key}"
        self._attr_icon = description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Independent IntelliCenter Read-Only Transport",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def is_on(self) -> bool | None:
        observation = _native_observation(
            self.coordinator,
            self._description.concept,
        )
        if observation is None or not isinstance(observation.value, bool):
            return None
        return observation.value

    @property
    def available(self) -> bool:
        observation = _native_observation(
            self.coordinator,
            self._description.concept,
        )
        snapshot = self.coordinator.native_intellicenter_snapshot
        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and observation is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        observation = _native_observation(
            self.coordinator,
            self._description.concept,
        )
        snapshot = self.coordinator.native_intellicenter_snapshot

        if observation is None:
            return {
                "canonical_concept": self._description.concept,
                "source": "poolos.independent_intellicenter",
                "available": False,
                "authority": "none",
                "command_delivery_enabled": False,
                "read_only": True,
            }

        quality = observation.quality
        quality_value = getattr(quality, "value", str(quality))

        return {
            "canonical_concept": self._description.concept,
            "source": "poolos.independent_intellicenter",
            "source_id": observation.source_id,
            "observed_at": (
                None if observation.observed_at is None else observation.observed_at.isoformat()
            ),
            "quality": quality_value,
            "available": bool(getattr(snapshot, "available", False)),
            "authority": "none",
            "command_delivery_enabled": False,
            "read_only": True,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up native IntelliCenter binary sensors."""

    runtime = entry.runtime_data
    async_add_entities(
        PoolOSNativeIntelliCenterBinarySensor(
            runtime.coordinator,
            entry,
            description,
        )
        for description in NATIVE_BINARY_SENSORS
    )
