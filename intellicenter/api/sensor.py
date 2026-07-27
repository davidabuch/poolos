"""Pentair IntelliCenter sensors backed by the immutable read model.

Entity discovery still inspects raw ``PoolObject`` instances so dynamically
appearing equipment continues to create entities without a restart. Entity
state, however, is read exclusively from ``IntelliCenterAPI`` snapshots.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    EntityCategory,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyintellicenter import (
    BODY_TYPE,
    CHEM_TYPE,
    GPM_ATTR,
    LSTTMP_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    ORPTNK_ATTR,
    ORPVAL_ATTR,
    ORPVOL_ATTR,
    PHTNK_ATTR,
    PHVAL_ATTR,
    PHVOL_ATTR,
    PUMP_TYPE,
    PWR_ATTR,
    QUALTY_ATTR,
    RPM_ATTR,
    SALT_ATTR,
    SENSE_TYPE,
    SERVICE_ATTR,
    SOURCE_ATTR,
    SYSTEM_TYPE,
    VER_ATTR,
    PoolObject,
)

from . import IntelliCenterConfigEntry, PoolEntity, async_setup_pool_entities, safe_int
from .api import SystemMode
from .const import CONST_GPM, CONST_RPM
from .coordinator import IntelliCenterCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

StateGetter = Callable[[], Any]


def _state_field(
    lookup: Callable[[str], Any], object_id: str, field_name: str
) -> Any:
    """Return one field from an immutable API object, or None if absent."""
    state = lookup(object_id)
    return getattr(state, field_name, None) if state is not None else None


def _system_field(coordinator: IntelliCenterCoordinator, field_name: str) -> Any:
    """Return one field from immutable controller-wide state."""
    state = coordinator.api.system
    return getattr(state, field_name, None) if state is not None else None


def _build_entities(
    coordinator: IntelliCenterCoordinator, candidates: Iterable[PoolObject]
) -> list[PoolSensor]:
    """Build sensor entities for candidate pool objects."""
    sensors: list[PoolSensor] = []

    for obj in candidates:
        if obj.objtype == SENSE_TYPE:
            sensors.append(
                PoolSensor(
                    coordinator,
                    obj,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    attribute_key=SOURCE_ATTR,
                    value_getter=partial(
                        _state_field,
                        coordinator.api.temperature_sensor,
                        obj.objnam,
                        "temperature",
                    ),
                )
            )

        elif obj.objtype == BODY_TYPE:
            if LSTTMP_ATTR in obj.attribute_keys:
                sensors.append(
                    PoolSensor(
                        coordinator,
                        obj,
                        device_class=SensorDeviceClass.TEMPERATURE,
                        attribute_key=LSTTMP_ATTR,
                        name="+ Last Temp",
                        value_getter=partial(
                            _state_field,
                            coordinator.api.body,
                            obj.objnam,
                            "current_temperature",
                        ),
                    )
                )

        elif obj.objtype == PUMP_TYPE:
            pump_fields = (
                (
                    PWR_ATTR,
                    "power_watts",
                    SensorDeviceClass.POWER,
                    UnitOfPower.WATT,
                    "+ power",
                    25,
                    None,
                    None,
                ),
                (RPM_ATTR, "rpm", None, CONST_RPM, "+ rpm", 0, None, None),
                (GPM_ATTR, "flow_gpm", None, CONST_GPM, "+ gpm", 0, None, None),
                (
                    MAX_ATTR,
                    "maximum_rpm",
                    None,
                    CONST_RPM,
                    "+ Max RPM",
                    0,
                    "mdi:speedometer",
                    EntityCategory.DIAGNOSTIC,
                ),
                (
                    MIN_ATTR,
                    "minimum_rpm",
                    None,
                    CONST_RPM,
                    "+ Min RPM",
                    0,
                    "mdi:speedometer-slow",
                    EntityCategory.DIAGNOSTIC,
                ),
            )
            for (
                attribute_key,
                field_name,
                device_class,
                unit,
                name,
                rounding_factor,
                icon,
                category,
            ) in pump_fields:
                if attribute_key not in obj.attribute_keys:
                    continue
                if attribute_key in {PWR_ATTR, RPM_ATTR, GPM_ATTR} and not obj[attribute_key]:
                    continue
                sensors.append(
                    PoolSensor(
                        coordinator,
                        obj,
                        device_class=device_class,
                        unit_of_measurement=unit,
                        attribute_key=attribute_key,
                        name=name,
                        rounding_factor=rounding_factor,
                        icon=icon,
                        entity_category=category,
                        value_getter=partial(
                            _state_field,
                            coordinator.api.pump,
                            obj.objnam,
                            field_name,
                        ),
                    )
                )

            flow_limits = (
                (MAXF_ATTR, "maximum_flow_gpm", "+ Max GPM", "mdi:water-pump"),
                (MINF_ATTR, "minimum_flow_gpm", "+ Min GPM", "mdi:water-pump-off"),
            )
            for attribute_key, field_name, name, icon in flow_limits:
                if attribute_key not in obj.attribute_keys:
                    continue
                if (safe_int(obj[attribute_key]) or 0) <= 0:
                    continue
                sensors.append(
                    PoolSensor(
                        coordinator,
                        obj,
                        device_class=None,
                        unit_of_measurement=CONST_GPM,
                        attribute_key=attribute_key,
                        name=name,
                        icon=icon,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        value_getter=partial(
                            _state_field,
                            coordinator.api.pump,
                            obj.objnam,
                            field_name,
                        ),
                    )
                )

        elif obj.objtype == CHEM_TYPE:
            if obj.subtype == "ICHEM":
                chemistry_fields = (
                    (PHVAL_ATTR, "ph", SensorDeviceClass.PH, None, "+ (pH)", None, None, SensorStateClass.MEASUREMENT),
                    (ORPVAL_ATTR, "orp_mv", None, "mV", "+ (ORP)", "mdi:react", None, SensorStateClass.MEASUREMENT),
                    (QUALTY_ATTR, "water_quality", None, None, "+ (Water Quality)", "mdi:test-tube", None, SensorStateClass.MEASUREMENT),
                    (PHTNK_ATTR, "ph_tank_level", None, None, "+ (pH Tank Level)", "mdi:barrel", EntityCategory.DIAGNOSTIC, SensorStateClass.MEASUREMENT),
                    (ORPTNK_ATTR, "orp_tank_level", None, None, "+ (ORP Tank Level)", "mdi:barrel", EntityCategory.DIAGNOSTIC, SensorStateClass.MEASUREMENT),
                    (PHVOL_ATTR, "ph_dosing_volume_ml", None, "mL", "+ (pH Dosing Volume)", "mdi:beaker-outline", EntityCategory.DIAGNOSTIC, SensorStateClass.TOTAL_INCREASING),
                    (ORPVOL_ATTR, "orp_dosing_volume_ml", None, "mL", "+ (ORP Dosing Volume)", "mdi:beaker-outline", EntityCategory.DIAGNOSTIC, SensorStateClass.TOTAL_INCREASING),
                )
                for (
                    attribute_key,
                    field_name,
                    device_class,
                    unit,
                    name,
                    icon,
                    category,
                    state_class,
                ) in chemistry_fields:
                    if attribute_key not in obj.attribute_keys:
                        continue
                    sensors.append(
                        PoolSensor(
                            coordinator,
                            obj,
                            device_class=device_class,
                            attribute_key=attribute_key,
                            unit_of_measurement=unit,
                            name=name,
                            icon=icon,
                            entity_category=category,
                            state_class=state_class,
                            value_getter=partial(
                                _state_field,
                                coordinator.api.chemistry,
                                obj.objnam,
                                field_name,
                            ),
                        )
                    )
            elif obj.subtype == "ICHLOR" and SALT_ATTR in obj.attribute_keys:
                sensors.append(
                    PoolSensor(
                        coordinator,
                        obj,
                        device_class=None,
                        unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
                        attribute_key=SALT_ATTR,
                        name="+ (Salt)",
                        icon="mdi:shaker-outline",
                        value_getter=partial(
                            _state_field,
                            coordinator.api.chemistry,
                            obj.objnam,
                            "salt_ppm",
                        ),
                    )
                )

        elif obj.objtype == SYSTEM_TYPE:
            if VER_ATTR in obj.attribute_keys:
                sensors.append(
                    PoolSensor(
                        coordinator,
                        obj,
                        device_class=None,
                        attribute_key=VER_ATTR,
                        name="Firmware Version",
                        icon="mdi:chip",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        state_class=None,
                        value_getter=partial(
                            _system_field, coordinator, "firmware_version"
                        ),
                    )
                )
            if SERVICE_ATTR in obj.attribute_keys:
                sensors.append(SystemModeSensor(coordinator, obj))

    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntelliCenterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load pool sensors based on a config entry."""
    async_setup_pool_entities(entry, async_add_entities, _build_entities)


class PoolSensor(PoolEntity, SensorEntity):
    """Representation of an IntelliCenter sensor using immutable API state."""

    def __init__(
        self,
        coordinator: IntelliCenterCoordinator,
        pool_object: PoolObject,
        device_class: SensorDeviceClass | None,
        value_getter: StateGetter,
        rounding_factor: int = 0,
        entity_category: EntityCategory | None = None,
        state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
        **kwargs: Any,
    ) -> None:
        """Initialize a read-model-backed pool sensor."""
        super().__init__(coordinator, pool_object, **kwargs)
        self._attr_device_class = device_class
        self._value_getter = value_getter
        self._rounding_factor = rounding_factor
        if state_class is not None:
            self._attr_state_class = state_class
        if entity_category is not None:
            self._attr_entity_category = entity_category

    @property
    def native_value(self) -> float | int | str | None:
        """Return the normalized value from the latest immutable snapshot."""
        raw_value = self._value_getter()
        if raw_value is None:
            return None

        if isinstance(raw_value, bool):
            return int(raw_value)
        if isinstance(raw_value, int):
            value: float | int = raw_value
        elif isinstance(raw_value, float):
            value = int(raw_value) if raw_value.is_integer() else raw_value
        else:
            text = str(raw_value)
            try:
                value = int(text)
            except ValueError:
                try:
                    value = float(text)
                except ValueError:
                    return text

        if self._rounding_factor:
            return int(round(float(value) / self._rounding_factor) * self._rounding_factor)
        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement of this entity, if any."""
        if self._attr_device_class == SensorDeviceClass.TEMPERATURE:
            return self.coordinator.api.snapshot.temperature_unit
        return self._attr_native_unit_of_measurement


SYSTEM_MODE_OPTIONS = ["auto", "service", "timeout"]


class SystemModeSensor(PoolSensor):
    """System operating-mode sensor backed by immutable system state."""

    _attr_translation_key = "system_mode"

    def __init__(
        self,
        coordinator: IntelliCenterCoordinator,
        pool_object: PoolObject,
    ) -> None:
        """Initialize the system mode sensor."""
        super().__init__(
            coordinator,
            pool_object,
            device_class=SensorDeviceClass.ENUM,
            attribute_key=SERVICE_ATTR,
            name="System Mode",
            icon="mdi:cog-sync",
            state_class=None,
            value_getter=partial(_system_field, coordinator, "operating_mode"),
        )
        self._attr_options = SYSTEM_MODE_OPTIONS

    @property
    def native_value(self) -> str | None:
        """Return a supported normalized system mode, or unknown."""
        mode = self._value_getter()
        if mode is None or mode is SystemMode.UNKNOWN:
            return None
        value = str(mode)
        return value if value in self._attr_options else None
