"""Translate physical IntelliCenter temperature probes into stable snapshots."""

from __future__ import annotations

from typing import Any

from pyintellicenter import SOURCE_ATTR, PoolObject

from .models import TemperatureSensorState, TemperatureSensorType


def _safe_float(value: Any) -> float | None:
    """Convert a panel value to float without leaking parsing failures."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sensor_type(probe: PoolObject) -> TemperatureSensorType:
    """Normalize a physical probe subtype/name into a stable category."""
    candidates = (probe.subtype, probe.sname, probe.objnam)
    normalized = " ".join(str(value or "").casefold() for value in candidates)
    if "air" in normalized:
        return TemperatureSensorType.AIR
    if "solar" in normalized:
        return TemperatureSensorType.SOLAR
    if "water" in normalized or "pool" in normalized or "spa" in normalized:
        return TemperatureSensorType.WATER
    return TemperatureSensorType.UNKNOWN


def build_temperature_sensor_state(probe: PoolObject) -> TemperatureSensorState:
    """Build one immutable physical temperature-probe snapshot."""
    return TemperatureSensorState(
        id=probe.objnam,
        name=str(probe.sname or probe.objnam),
        sensor_type=_sensor_type(probe),
        subtype=str(probe.subtype) if probe.subtype is not None else None,
        temperature=_safe_float(probe[SOURCE_ATTR]),
    )
