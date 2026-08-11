"""Read-only conversion from the reference protocol snapshot into PoolOS."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, NamedTuple

from poolos.intellicenter_readonly import (
    NativeBodyKind,
    NativeBodyState,
    NativeCircuitState,
    NativeIntelliCenterTransportSnapshot,
    NativePumpState,
    NativeTemperatureKind,
    NativeTemperatureState,
)

_INVENTORY_COLLECTION_LIMIT = 24
_INVENTORY_TEXT_LIMIT = 64
_COLLECTION_NAMES = ("bodies", "circuits", "pumps", "temperature_sensors")


class NativeInventoryItem(NamedTuple):
    """One bounded equipment identity copied for diagnostics only."""

    native_id: str
    name: str
    native_type: str

    def to_dict(self) -> Mapping[str, str]:
        return MappingProxyType(
            {"id": self.native_id, "name": self.name, "type": self.native_type}
        )


class NativeSnapshotInventory(NamedTuple):
    """Immutable, bounded description of the reference snapshot shape."""

    snapshot_type: str
    api_version: str | None
    connected: bool
    temperature_unit: str
    observed_at: datetime
    observed_at_source: str
    available_collections: tuple[str, ...]
    body_count: int
    pump_count: int
    temperature_sensor_count: int
    circuit_count: int
    bodies: tuple[NativeInventoryItem, ...]
    pumps: tuple[NativeInventoryItem, ...]
    temperature_sensors: tuple[NativeInventoryItem, ...]
    circuits: tuple[NativeInventoryItem, ...]
    truncated_collections: tuple[str, ...]

    def diagnostics(self) -> Mapping[str, Any]:
        collections = {
            "bodies": self.bodies,
            "pumps": self.pumps,
            "temperature_sensors": self.temperature_sensors,
            "circuits": self.circuits,
        }
        return MappingProxyType(
            {
                "snapshot_type": self.snapshot_type,
                "api_version": self.api_version,
                "connected": self.connected,
                "temperature_unit": self.temperature_unit,
                "observed_at": self.observed_at.isoformat(),
                "observed_at_source": self.observed_at_source,
                "available_collections": list(self.available_collections),
                "counts": {
                    "bodies": self.body_count,
                    "pumps": self.pump_count,
                    "temperature_sensors": self.temperature_sensor_count,
                    "circuits": self.circuit_count,
                },
                "displayed_counts": {
                    name: len(items) for name, items in collections.items()
                },
                "bodies": [dict(item.to_dict()) for item in self.bodies],
                "pumps": [dict(item.to_dict()) for item in self.pumps],
                "temperature_sensors": [
                    dict(item.to_dict()) for item in self.temperature_sensors
                ],
                "circuits": [dict(item.to_dict()) for item in self.circuits],
                "truncated_collections": list(self.truncated_collections),
                "inventory_limit_per_collection": _INVENTORY_COLLECTION_LIMIT,
                "authority": "none",
                "command_delivery_enabled": False,
            }
        )


def native_snapshot_inventory(
    snapshot: Any, *, fallback_observed_at: datetime
) -> NativeSnapshotInventory:
    """Describe only known read-model collections without retaining the source."""

    raw_observed_at = getattr(snapshot, "observed_at", None)
    observed_at = raw_observed_at or fallback_observed_at
    available = tuple(name for name in _COLLECTION_NAMES if hasattr(snapshot, name))
    bodies, bodies_truncated, body_count = _inventory_items(
        getattr(snapshot, "bodies", ()), "body_type"
    )
    pumps, pumps_truncated, pump_count = _inventory_items(
        getattr(snapshot, "pumps", ()), "pump_type"
    )
    temperatures, temperatures_truncated, temperature_sensor_count = _inventory_items(
        getattr(snapshot, "temperature_sensors", ()), "sensor_type"
    )
    circuits, circuits_truncated, circuit_count = _inventory_items(
        getattr(snapshot, "circuits", ()), "use", fallback_type_attribute="subtype"
    )
    truncated = tuple(
        name
        for name, is_truncated in (
            ("bodies", bodies_truncated),
            ("circuits", circuits_truncated),
            ("pumps", pumps_truncated),
            ("temperature_sensors", temperatures_truncated),
        )
        if is_truncated
    )
    api_version = getattr(snapshot, "api_version", None)
    return NativeSnapshotInventory(
        snapshot_type=_compact_text(type(snapshot).__name__),
        api_version=None if api_version is None else _compact_text(api_version),
        connected=bool(getattr(snapshot, "connected", False)),
        temperature_unit=_compact_text(getattr(snapshot, "temperature_unit", "unknown")),
        observed_at=observed_at,
        observed_at_source="snapshot" if raw_observed_at is not None else "refresh_fallback",
        available_collections=available,
        body_count=body_count,
        pump_count=pump_count,
        temperature_sensor_count=temperature_sensor_count,
        circuit_count=circuit_count,
        bodies=bodies,
        pumps=pumps,
        temperature_sensors=temperatures,
        circuits=circuits,
        truncated_collections=truncated,
    )


def native_transport_snapshot(
    snapshot: Any,
    *,
    source_id: str,
    fallback_observed_at: datetime,
) -> NativeIntelliCenterTransportSnapshot:
    """Copy only immutable read fields; never retain a controller reference."""

    observed_at = getattr(snapshot, "observed_at", None) or fallback_observed_at
    return NativeIntelliCenterTransportSnapshot(
        source_id=source_id,
        observed_at=observed_at,
        connected=bool(snapshot.connected),
        temperature_unit=str(snapshot.temperature_unit),
        bodies=tuple(
            NativeBodyState(
                native_id=str(item.id),
                name=str(item.name),
                kind=_body_kind(item.body_type),
                active=bool(item.is_on),
                heating_active=bool(item.heating_active),
                current_temperature=_number(item.current_temperature),
                target_temperature=_number(item.target_temperature),
                active_heat_source=_enum_text(getattr(item, "active_heat_source", None)),
                selected_heat_mode=_enum_text(getattr(item, "selected_heat_mode", None)),
            )
            for item in getattr(snapshot, "bodies", ())
        ),
        pumps=tuple(
            NativePumpState(
                native_id=str(item.id),
                name=str(item.name),
                running=bool(item.is_running),
                rpm=_number(item.rpm),
                gpm=_number(item.flow_gpm),
                power_watts=_number(item.power_watts),
            )
            for item in getattr(snapshot, "pumps", ())
        ),
        temperatures=tuple(
            NativeTemperatureState(
                native_id=str(item.id),
                name=str(item.name),
                kind=_temperature_kind(item.sensor_type),
                temperature=_number(item.temperature),
            )
            for item in getattr(snapshot, "temperature_sensors", ())
        ),
        circuits=tuple(
            NativeCircuitState(
                native_id=str(item.id),
                name=str(item.name),
                active=bool(item.is_on),
                use=None if item.use is None else str(item.use),
                subtype=None if item.subtype is None else str(item.subtype),
            )
            for item in getattr(snapshot, "circuits", ())
        ),
    )


def _body_kind(value: Any) -> NativeBodyKind:
    normalized = str(getattr(value, "value", value)).strip().casefold()
    if normalized == "pool":
        return NativeBodyKind.POOL
    if normalized == "spa":
        return NativeBodyKind.SPA
    return NativeBodyKind.UNKNOWN


def _temperature_kind(value: Any) -> NativeTemperatureKind:
    normalized = str(getattr(value, "value", value)).strip().casefold()
    try:
        return NativeTemperatureKind(normalized)
    except ValueError:
        return NativeTemperatureKind.UNKNOWN


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inventory_items(
    items: Any,
    type_attribute: str,
    *,
    fallback_type_attribute: str | None = None,
) -> tuple[tuple[NativeInventoryItem, ...], bool, int]:
    copied = tuple(items or ())
    ordered = sorted(copied, key=lambda item: _compact_text(getattr(item, "id", "")))
    result = tuple(
        NativeInventoryItem(
            native_id=_compact_text(getattr(item, "id", "unknown")),
            name=_compact_text(getattr(item, "name", "unknown")),
            native_type=_compact_text(
                _enum_text(getattr(item, type_attribute, None))
                or (
                    _enum_text(getattr(item, fallback_type_attribute, None))
                    if fallback_type_attribute is not None
                    else None
                )
                or "unknown"
            ),
        )
        for item in ordered[:_INVENTORY_COLLECTION_LIMIT]
    )
    return result, len(ordered) > _INVENTORY_COLLECTION_LIMIT, len(ordered)


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _compact_text(value: Any) -> str:
    return str(value).strip()[:_INVENTORY_TEXT_LIMIT]
