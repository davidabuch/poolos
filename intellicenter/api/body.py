"""Translate raw pyintellicenter body objects into stable read-model snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.const import UnitOfTemperature
from pyintellicenter import (
    HEATER_ATTR,
    HITMP_ATTR,
    HTMODE_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    NULL_OBJNAM,
    STATUS_ATTR,
    STATUS_OFF,
    PoolObject,
)

from .models import (
    BodyHeatMode,
    BodyState,
    BodyType,
    HeatMode,
    HeatSource,
    HeaterState,
)

if TYPE_CHECKING:
    from ..coordinator import IntelliCenterCoordinator


def _safe_float(value: Any) -> float | None:
    """Convert a device value to float without leaking parsing failures."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _body_type(body: PoolObject) -> BodyType:
    """Infer Pool versus Spa from stable panel-provided names.

    IntelliCenter body objects do not expose a dedicated normalized Pool/Spa enum
    through pyintellicenter. Keep the inference isolated here so it can be replaced
    later without affecting API consumers.
    """
    text = " ".join(
        value
        for value in (body.objnam, body.sname, body.subtype)
        if isinstance(value, str)
    ).casefold()
    if "spa" in text:
        return BodyType.SPA
    if "pool" in text:
        return BodyType.POOL
    return BodyType.UNKNOWN


def _heat_source(heater: PoolObject) -> HeatSource:
    """Normalize a heater subtype/name into a stable heat-source value."""
    text = " ".join(
        value
        for value in (heater.subtype, heater.sname, heater.objnam)
        if isinstance(value, str)
    ).casefold()

    if "hybrid" in text or "hcombo" in text:
        return HeatSource.HYBRID
    if "solar" in text:
        return HeatSource.SOLAR
    if "heat pump" in text or "heatpump" in text or "ultratemp" in text:
        return HeatSource.HEAT_PUMP
    if "gas" in text or "mastertemp" in text:
        return HeatSource.GAS
    if "electric" in text:
        return HeatSource.ELECTRIC
    return HeatSource.UNKNOWN



def _body_heat_mode(heater: PoolObject) -> BodyHeatMode:
    """Normalize a selectable heater object into a user-facing heat strategy.

    IntelliCenter represents Gas, Solar, and Solar Preferred as selectable
    heater entries. Solar Preferred must be checked before Solar because its
    label contains the word ``solar``.
    """
    text = " ".join(
        value
        for value in (heater.subtype, heater.sname, heater.objnam)
        if isinstance(value, str)
    ).casefold().replace("-", " ").replace("_", " ")

    if "solar preferred" in text or "solarpref" in text:
        return BodyHeatMode.SOLAR_PREFERRED
    if "solar" in text:
        return BodyHeatMode.SOLAR
    if "hybrid" in text or "hcombo" in text:
        return BodyHeatMode.HYBRID
    if "heat pump" in text or "heatpump" in text or "ultratemp" in text:
        return BodyHeatMode.HEAT_PUMP
    if "gas" in text or "mastertemp" in text:
        return BodyHeatMode.GAS
    if "electric" in text:
        return BodyHeatMode.ELECTRIC
    return BodyHeatMode.UNKNOWN


def _normalize_heat_mode(
    *,
    is_on: bool,
    selected_heater: str | None,
    htmode: Any,
    supports_cooling: bool,
) -> HeatMode:
    """Normalize raw body mode attributes into a small stable enum."""
    if not is_on or selected_heater in (None, "", NULL_OBJNAM):
        return HeatMode.OFF
    if htmode in (None, "", "0", 0):
        return HeatMode.OFF
    if supports_cooling:
        return HeatMode.HEAT_COOL
    return HeatMode.HEAT


def build_body_state(
    coordinator: IntelliCenterCoordinator,
    body: PoolObject,
    heater_objnams: Iterable[str],
    minimum_temperature: float,
    maximum_temperature: float,
    temperature_unit: UnitOfTemperature,
) -> BodyState:
    """Build one immutable body snapshot from the coordinator's live model."""
    heater_states: list[HeaterState] = []
    heater_modes: dict[str, BodyHeatMode] = {}
    for heater_objnam in heater_objnams:
        heater = coordinator.model[heater_objnam]
        if heater is None:
            continue
        heater_modes[heater.objnam] = _body_heat_mode(heater)
        heater_states.append(
            HeaterState(
                id=heater.objnam,
                name=str(heater.sname or heater.objnam),
                source=_heat_source(heater),
                subtype=str(heater.subtype) if heater.subtype is not None else None,
            )
        )

    is_on = body[STATUS_ATTR] != STATUS_OFF
    current_temperature = _safe_float(body[LSTTMP_ATTR])
    target_temperature = _safe_float(body[LOTMP_ATTR])
    cooling_target = _safe_float(body[HITMP_ATTR])
    selected = body[HEATER_ATTR]
    selected_heater_id = (
        str(selected) if selected not in (None, "", NULL_OBJNAM) else None
    )
    supports_cooling = coordinator.controller.body_supports_cooling(body.objnam)

    heat_mode = _normalize_heat_mode(
        is_on=is_on,
        selected_heater=selected_heater_id,
        htmode=body[HTMODE_ATTR],
        supports_cooling=supports_cooling,
    )

    heating_requested = bool(
        is_on
        and heat_mode is not HeatMode.OFF
        and current_temperature is not None
        and target_temperature is not None
        and current_temperature < target_temperature
    )
    cooling_requested = bool(
        is_on
        and supports_cooling
        and current_temperature is not None
        and cooling_target is not None
        and current_temperature > cooling_target
    )

    heating_active = bool(
        is_on and coordinator.controller.is_body_heating(body.objnam)
    )
    cooling_active = bool(
        is_on and coordinator.controller.is_body_cooling(body.objnam)
    )

    selected_heat_mode = (
        heater_modes.get(selected_heater_id, BodyHeatMode.UNKNOWN)
        if selected_heater_id is not None
        else BodyHeatMode.OFF
    )
    available_heat_modes = [BodyHeatMode.OFF]
    for heater in heater_states:
        mode = heater_modes[heater.id]
        if mode not in available_heat_modes:
            available_heat_modes.append(mode)

    selected_state = next(
        (heater for heater in heater_states if heater.id == selected_heater_id),
        None,
    )

    return BodyState(
        id=body.objnam,
        name=str(body.sname or body.objnam),
        body_type=_body_type(body),
        is_on=is_on,
        current_temperature=current_temperature,
        target_temperature=target_temperature,
        cooling_target_temperature=cooling_target if supports_cooling else None,
        heat_mode=heat_mode,
        heating_requested=heating_requested,
        cooling_requested=cooling_requested,
        heating_active=heating_active,
        cooling_active=cooling_active,
        available_heaters=tuple(heater_states),
        selected_heater_id=selected_heater_id,
        active_heat_source=selected_state.source if selected_state else None,
        selected_heat_mode=selected_heat_mode,
        available_heat_modes=tuple(available_heat_modes),
        min_temperature=minimum_temperature,
        max_temperature=maximum_temperature,
        temperature_unit=temperature_unit,
    )
