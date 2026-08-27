"""Native PoolOS manual IntelliCenter Pool RPM setpoint."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError


_POOL_PMPCIRC_OBJNAM = "p0102"
_POOL_PMPCIRC_TYPE = "PMPCIRC"
_RPM_MODE = "RPM"
_DEFAULT_MIN_RPM = 450
_DEFAULT_MAX_RPM = 3450
_RPM_STEP = 50


def _raw_snapshot(coordinator: PoolOSCoordinator) -> Any:
    transport = coordinator.independent_intellicenter_transport

    if transport is None:
        return None

    return transport.latest_snapshot


def _raw_object(
    coordinator: PoolOSCoordinator,
    native_id: str,
) -> Any:
    snapshot = _raw_snapshot(coordinator)

    if snapshot is None:
        return None

    for item in snapshot.raw_inventory:
        if item.native_id == native_id:
            return item

    return None


def _raw_attributes(item: Any) -> dict[str, Any]:
    if item is None:
        return {}

    return {
        str(attribute.name): attribute.value
        for attribute in item.attributes
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None

    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return None

    return result if result > 0 else None


def _pool_pump_circuit(
    coordinator: PoolOSCoordinator,
) -> tuple[Any, dict[str, Any]] | tuple[None, dict[str, Any]]:
    item = _raw_object(coordinator, _POOL_PMPCIRC_OBJNAM)

    if item is None:
        return None, {}

    if str(item.object_type).upper() != _POOL_PMPCIRC_TYPE:
        return None, {}

    return item, _raw_attributes(item)


def _rpm_limits(
    coordinator: PoolOSCoordinator,
    attributes: dict[str, Any],
) -> tuple[int, int]:
    parent_id = attributes.get("PARENT")

    if parent_id is None:
        return _DEFAULT_MIN_RPM, _DEFAULT_MAX_RPM

    parent = _raw_object(coordinator, str(parent_id))
    parent_attributes = _raw_attributes(parent)

    minimum = (
        _positive_int(parent_attributes.get("MIN"))
        or _DEFAULT_MIN_RPM
    )
    maximum = (
        _positive_int(parent_attributes.get("MAX"))
        or _DEFAULT_MAX_RPM
    )

    if minimum > maximum:
        return _DEFAULT_MIN_RPM, _DEFAULT_MAX_RPM

    return minimum, maximum


class PoolOSNativeIntelliCenterPoolRPM(
    CoordinatorEntity[PoolOSCoordinator],
    NumberEntity,
):
    """Represent the native Pool PMPCIRC RPM setpoint."""

    _attr_has_entity_name = True
    _attr_name = "Pool RPM"
    _attr_icon = "mdi:speedometer"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = _RPM_STEP
    _attr_native_unit_of_measurement = "rpm"

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
    ) -> None:
        super().__init__(coordinator)

        self._runtime = entry.runtime_data
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_pool_rpm"
        )
        self._attr_device_info = {
            "identifiers": {
                (DOMAIN, f"{entry.entry_id}_native_intellicenter")
            },
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Pump Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Return whether native PMPCIRC truth and manual delivery are usable."""

        native = self.coordinator.native_intellicenter_snapshot
        manual = self._runtime.manual_intellicenter
        item, attributes = _pool_pump_circuit(self.coordinator)

        mode = str(attributes.get("SELECT") or _RPM_MODE).upper()

        return (
            native is not None
            and bool(getattr(native, "available", False))
            and item is not None
            and mode == _RPM_MODE
            and _positive_int(attributes.get("SPEED")) is not None
            and manual is not None
            and manual.available
        )

    @property
    def native_value(self) -> int | None:
        """Return native-authoritative p0102 SPEED."""

        _item, attributes = _pool_pump_circuit(self.coordinator)
        return _positive_int(attributes.get("SPEED"))

    @property
    def native_min_value(self) -> float:
        """Return parent pump minimum RPM when native evidence is available."""

        _item, attributes = _pool_pump_circuit(self.coordinator)
        minimum, _maximum = _rpm_limits(self.coordinator, attributes)
        return float(minimum)

    @property
    def native_max_value(self) -> float:
        """Return parent pump maximum RPM when native evidence is available."""

        _item, attributes = _pool_pump_circuit(self.coordinator)
        _minimum, maximum = _rpm_limits(self.coordinator, attributes)
        return float(maximum)

    async def async_set_native_value(self, value: float) -> None:
        """Send an explicit manual Pool PMPCIRC RPM request."""

        manual = self._runtime.manual_intellicenter

        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_pump_circuit_speed(
            _POOL_PMPCIRC_OBJNAM,
            value,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded identity, source, and authority diagnostics."""

        manual = self._runtime.manual_intellicenter
        item, attributes = _pool_pump_circuit(self.coordinator)
        minimum, maximum = _rpm_limits(
            self.coordinator,
            attributes,
        )

        return {
            "pmpcirc_objnam": _POOL_PMPCIRC_OBJNAM,
            "native_object_type": (
                None if item is None else item.object_type
            ),
            "parent_pump_objnam": attributes.get("PARENT"),
            "circuit_objnam": attributes.get("CIRCUIT"),
            "control_mode": attributes.get("SELECT"),
            "native_speed_setpoint": _positive_int(
                attributes.get("SPEED")
            ),
            "native_min_rpm": minimum,
            "native_max_rpm": maximum,
            "actual_pump_rpm_concept": "pump.rpm",
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
            "optimistic": False,
        }


async def async_setup_entry(
    hass,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the native Pool PMPCIRC RPM number."""

    del hass

    async_add_entities(
        [
            PoolOSNativeIntelliCenterPoolRPM(
                entry.runtime_data.coordinator,
                entry,
            )
        ]
    )
