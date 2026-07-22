"""Translate raw pyintellicenter circuit objects into stable snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyintellicenter import (
    FEATR_ATTR,
    FREEZE_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    TIME_ATTR,
    USE_ATTR,
    PoolObject,
)

from .models import CircuitState

if TYPE_CHECKING:
    from ..coordinator import IntelliCenterCoordinator


def _safe_int(value: Any) -> int | None:
    """Convert a panel value to int without leaking parsing failures."""
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_enabled(value: Any) -> bool:
    """Normalize common IntelliCenter boolean representations."""
    if isinstance(value, str):
        return value.strip().casefold() not in {
            "",
            "0",
            "false",
            "no",
            "off",
            "disabled",
            "none",
        }
    return bool(value)


def build_circuit_state(
    coordinator: IntelliCenterCoordinator,
    circuit: PoolObject,
) -> CircuitState:
    """Build one immutable circuit snapshot from the live model."""
    del coordinator  # Reserved for future circuit relationships and capabilities.

    return CircuitState(
        id=circuit.objnam,
        name=str(circuit.sname or circuit.objnam),
        is_on=circuit[STATUS_ATTR] != STATUS_OFF,
        subtype=str(circuit.subtype) if circuit.subtype is not None else None,
        use=(
            str(circuit[USE_ATTR])
            if circuit[USE_ATTR] not in (None, "")
            else None
        ),
        feature=_is_enabled(circuit[FEATR_ATTR]),
        freeze_protected=_is_enabled(circuit[FREEZE_ATTR]),
        egg_timer_minutes=_safe_int(circuit[TIME_ATTR]),
    )
