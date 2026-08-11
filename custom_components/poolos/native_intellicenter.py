"""Read-only conversion from the reference protocol snapshot into PoolOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from poolos.intellicenter_readonly import (
    NativeBodyKind,
    NativeBodyState,
    NativeCircuitState,
    NativeIntelliCenterTransportSnapshot,
    NativePumpState,
    NativeTemperatureKind,
    NativeTemperatureState,
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
