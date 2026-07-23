"""Translate the IntelliCenter SYSTEM object into a stable snapshot."""

from __future__ import annotations

from typing import Any

from pyintellicenter import MODE_ATTR, SERVICE_ATTR, VACFLO_ATTR, VER_ATTR, PoolObject

from .models import SystemMode, SystemState


_SYSTEM_MODE_ALIASES = {
    "auto": SystemMode.AUTO,
    "service": SystemMode.SERVICE,
    "timeout": SystemMode.TIMEOUT,
    # Pentair's protocol uses this misspelling on real hardware.
    "timout": SystemMode.TIMEOUT,
}


def _optional_text(value: Any) -> str | None:
    """Return a trimmed string, or None for an absent panel value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _system_mode(value: Any) -> SystemMode:
    """Normalize the SYSTEM SERVICE value into a stable enum."""
    normalized = str(value or "").strip().casefold().replace(" ", "")
    return _SYSTEM_MODE_ALIASES.get(normalized, SystemMode.UNKNOWN)


def build_system_state(system: PoolObject) -> SystemState:
    """Build one immutable controller-wide system snapshot."""
    return SystemState(
        id=system.objnam,
        name=str(system.sname or system.objnam),
        operating_mode=_system_mode(system[SERVICE_ATTR]),
        raw_operating_mode=_optional_text(system[SERVICE_ATTR]),
        controller_mode=_optional_text(system[MODE_ATTR]),
        vacation_mode=_is_enabled(system[VACFLO_ATTR]),
        firmware_version=_optional_text(system[VER_ATTR]),
    )
