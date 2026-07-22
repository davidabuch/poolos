"""Translate raw pyintellicenter pump objects into stable read-model snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pyintellicenter import (
    CIRCUIT_ATTR,
    GPM_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    PARENT_ATTR,
    PUMP_STATUS_ON,
    PWR_ATTR,
    RPM_ATTR,
    SELECT_ATTR,
    SPEED_ATTR,
    STATUS_ATTR,
    PoolObject,
)

from .models import PumpCircuitState, PumpMode, PumpState, PumpType


def _safe_float(value: Any) -> float | None:
    """Convert a device value to float without leaking parsing failures."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any) -> float | None:
    """Return a positive float, or None when the value is absent or invalid."""
    parsed = _safe_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def _pump_type(pump: PoolObject) -> PumpType:
    """Normalize pump capability into a stable type."""
    supports_rpm = _positive_float(pump[MAX_ATTR]) is not None
    supports_flow = _positive_float(pump[MAXF_ATTR]) is not None

    if supports_rpm and supports_flow:
        return PumpType.VARIABLE_SPEED_FLOW
    if supports_rpm:
        return PumpType.VARIABLE_SPEED
    if supports_flow:
        return PumpType.VARIABLE_FLOW

    subtype = pump.subtype.casefold() if isinstance(pump.subtype, str) else ""
    if subtype in {"vsf", "speedflow", "speed_flow"}:
        return PumpType.VARIABLE_SPEED_FLOW
    if subtype in {"speed", "vs"}:
        return PumpType.VARIABLE_SPEED
    if subtype in {"flow", "vf"}:
        return PumpType.VARIABLE_FLOW
    return PumpType.UNKNOWN


def _pump_mode(value: Any) -> PumpMode:
    """Normalize a PMPCIRC selection into RPM, GPM, or unknown."""
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "RPM":
            return PumpMode.RPM
        if normalized == "GPM":
            return PumpMode.GPM
    return PumpMode.UNKNOWN


def build_pump_circuit_state(
    pump_circuit: PoolObject,
    circuit_name: str | None,
) -> PumpCircuitState:
    """Build one immutable per-circuit pump-program snapshot."""
    return PumpCircuitState(
        id=pump_circuit.objnam,
        pump_id=str(pump_circuit[PARENT_ATTR] or ""),
        circuit_id=str(pump_circuit[CIRCUIT_ATTR] or ""),
        circuit_name=circuit_name,
        mode=_pump_mode(pump_circuit[SELECT_ATTR]),
        rpm_setpoint=_safe_float(pump_circuit[SPEED_ATTR]),
        flow_setpoint_gpm=_safe_float(pump_circuit[GPM_ATTR]),
    )


def build_pump_state(
    pump: PoolObject,
    pump_circuits: Iterable[PumpCircuitState],
) -> PumpState:
    """Build one immutable pump snapshot from the live model."""
    return PumpState(
        id=pump.objnam,
        name=pump.sname or pump.objnam,
        pump_type=_pump_type(pump),
        is_running=pump[STATUS_ATTR] == PUMP_STATUS_ON,
        power_watts=_safe_float(pump[PWR_ATTR]),
        rpm=_safe_float(pump[RPM_ATTR]),
        flow_gpm=_safe_float(pump[GPM_ATTR]),
        minimum_rpm=_positive_float(pump[MIN_ATTR]),
        maximum_rpm=_positive_float(pump[MAX_ATTR]),
        minimum_flow_gpm=_positive_float(pump[MINF_ATTR]),
        maximum_flow_gpm=_positive_float(pump[MAXF_ATTR]),
        circuits=tuple(pump_circuits),
    )
