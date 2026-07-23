"""Translate raw IntelliChem and IntelliChlor objects into stable snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pyintellicenter import (
    ALK_ATTR,
    BODY_ATTR,
    CALC_ATTR,
    CYACID_ATTR,
    ORPHI_ATTR,
    ORPLO_ATTR,
    ORPSET_ATTR,
    ORPTNK_ATTR,
    ORPVAL_ATTR,
    ORPVOL_ATTR,
    PHHI_ATTR,
    PHLO_ATTR,
    PHSET_ATTR,
    PHTNK_ATTR,
    PHVAL_ATTR,
    PHVOL_ATTR,
    PRIM_ATTR,
    QUALTY_ATTR,
    SALT_ATTR,
    SEC_ATTR,
    SUPER_ATTR,
    PoolObject,
)

from .models import ChemistryState, ChemistryType


def _safe_float(value: Any) -> float | None:
    """Convert a panel value to float without leaking parsing failures."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert a panel value to int without leaking parsing failures."""
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else None


def _scalar(value: Any) -> float | str | None:
    """Preserve non-numeric diagnostic values without exposing raw objects."""
    if value in (None, ""):
        return None
    parsed = _safe_float(value)
    return parsed if parsed is not None else str(value)


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


def _chemistry_type(subtype: Any) -> ChemistryType:
    """Normalize a chemistry-controller subtype."""
    normalized = str(subtype or "").strip().casefold()
    if normalized == "ichem":
        return ChemistryType.INTELLICHEM
    if normalized == "ichlor":
        return ChemistryType.INTELLICHLOR
    return ChemistryType.UNKNOWN


def _body_ids(value: Any) -> tuple[str, ...]:
    """Normalize the space-delimited BODY relationship into object ids."""
    if value in (None, ""):
        return ()
    return tuple(part for part in str(value).split() if part)


def _tank_level(value: Any) -> int | None:
    """Normalize IntelliChem's one-based tank-level protocol value."""
    parsed = _safe_int(value)
    return parsed - 1 if parsed is not None else None


def build_chemistry_state(
    chemistry: PoolObject,
    body_names: Mapping[str, str],
) -> ChemistryState:
    """Build one immutable chemistry snapshot from the live model."""
    body_ids = _body_ids(chemistry[BODY_ATTR])

    return ChemistryState(
        id=chemistry.objnam,
        name=str(chemistry.sname or chemistry.objnam),
        chemistry_type=_chemistry_type(chemistry.subtype),
        subtype=str(chemistry.subtype) if chemistry.subtype is not None else None,
        body_ids=body_ids,
        body_names=tuple(body_names.get(body_id, body_id) for body_id in body_ids),
        ph=_safe_float(chemistry[PHVAL_ATTR]),
        orp_mv=_safe_float(chemistry[ORPVAL_ATTR]),
        water_quality=_scalar(chemistry[QUALTY_ATTR]),
        ph_setpoint=_safe_float(chemistry[PHSET_ATTR]),
        orp_setpoint_mv=_safe_int(chemistry[ORPSET_ATTR]),
        alkalinity_ppm=_safe_int(chemistry[ALK_ATTR]),
        calcium_hardness_ppm=_safe_int(chemistry[CALC_ATTR]),
        cyanuric_acid_ppm=_safe_int(chemistry[CYACID_ATTR]),
        ph_tank_level=_tank_level(chemistry[PHTNK_ATTR]),
        orp_tank_level=_tank_level(chemistry[ORPTNK_ATTR]),
        ph_dosing_volume_ml=_safe_float(chemistry[PHVOL_ATTR]),
        orp_dosing_volume_ml=_safe_float(chemistry[ORPVOL_ATTR]),
        ph_high_alarm=_is_enabled(chemistry[PHHI_ATTR]),
        ph_low_alarm=_is_enabled(chemistry[PHLO_ATTR]),
        orp_high_alarm=_is_enabled(chemistry[ORPHI_ATTR]),
        orp_low_alarm=_is_enabled(chemistry[ORPLO_ATTR]),
        salt_ppm=_safe_int(chemistry[SALT_ATTR]),
        primary_output_percent=_safe_int(chemistry[PRIM_ATTR]),
        secondary_output_percent=_safe_int(chemistry[SEC_ATTR]),
        superchlorinate=_is_enabled(chemistry[SUPER_ATTR]),
    )
