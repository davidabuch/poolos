"""Stable read-model types for the Buch IntelliCenter integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from homeassistant.const import UnitOfTemperature

API_VERSION = 1


class BodyType(StrEnum):
    """Normalized IntelliCenter body type."""

    POOL = "pool"
    SPA = "spa"
    UNKNOWN = "unknown"


class HeatMode(StrEnum):
    """Normalized body heating/cooling mode."""

    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    HEAT_COOL = "heat_cool"
    UNKNOWN = "unknown"


class HeatSource(StrEnum):
    """Normalized heat-source type."""

    GAS = "gas"
    ELECTRIC = "electric"
    HEAT_PUMP = "heat_pump"
    SOLAR = "solar"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HeaterState:
    """Immutable snapshot of one heater available to a body."""

    id: str
    name: str
    source: HeatSource
    subtype: str | None


@dataclass(frozen=True, slots=True)
class BodyState:
    """Immutable snapshot of one Pool/Spa body."""

    id: str
    name: str
    body_type: BodyType
    is_on: bool
    current_temperature: float | None
    target_temperature: float | None
    cooling_target_temperature: float | None
    heat_mode: HeatMode
    heating_requested: bool
    cooling_requested: bool
    heating_active: bool
    cooling_active: bool
    available_heaters: tuple[HeaterState, ...]
    selected_heater_id: str | None
    active_heat_source: HeatSource | None
    min_temperature: float
    max_temperature: float
    temperature_unit: UnitOfTemperature


@dataclass(frozen=True, slots=True)
class IntelliCenterSnapshot:
    """Immutable system-level read-model snapshot."""

    api_version: int
    connected: bool
    panel_name: str | None
    software_version: str | None
    temperature_unit: UnitOfTemperature
    bodies: tuple[BodyState, ...]
