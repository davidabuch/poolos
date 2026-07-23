"""Cover read model for Buch IntelliCenter."""

from __future__ import annotations

from pyintellicenter import NORMAL_ATTR, STATUS_ATTR, STATUS_OFF, STATUS_ON, PoolObject

from .models import CoverState


def _status_to_bool(value: object) -> bool | None:
    """Normalize an IntelliCenter ON/OFF value without inventing state."""
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if normalized == STATUS_ON:
        return True
    if normalized == STATUS_OFF:
        return False
    return None


def build_cover_state(cover: PoolObject) -> CoverState:
    """Build an immutable cover snapshot from an external-instrument object."""
    status_is_on = _status_to_bool(cover[STATUS_ATTR])
    normal_is_on = _status_to_bool(cover[NORMAL_ATTR])

    # IntelliCenter's NORMAL flag defines which STATUS value means closed.
    # If either value is unavailable or malformed, position must remain unknown.
    is_closed = (
        status_is_on == normal_is_on
        if status_is_on is not None and normal_is_on is not None
        else None
    )

    subtype = str(cover.subtype).strip() if cover.subtype is not None else None
    if subtype == "":
        subtype = None

    return CoverState(
        id=cover.objnam,
        name=str(cover.sname or cover.objnam),
        subtype=subtype,
        is_closed=is_closed,
        status_is_on=status_is_on,
        normal_is_on=normal_is_on,
    )
