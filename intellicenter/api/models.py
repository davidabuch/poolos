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


class PumpType(StrEnum):
    """Normalized IntelliCenter pump capability."""

    VARIABLE_SPEED = "variable_speed"
    VARIABLE_FLOW = "variable_flow"
    VARIABLE_SPEED_FLOW = "variable_speed_flow"
    UNKNOWN = "unknown"


class PumpMode(StrEnum):
    """Normalized per-circuit pump control mode."""

    RPM = "rpm"
    GPM = "gpm"
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
class CircuitState:
    """Immutable snapshot of one IntelliCenter circuit."""

    id: str
    name: str
    is_on: bool
    subtype: str | None
    use: str | None
    feature: bool
    freeze_protected: bool
    egg_timer_minutes: int | None


@dataclass(frozen=True, slots=True)
class PumpCircuitState:
    """Immutable snapshot of one pump program assigned to a circuit."""

    id: str
    pump_id: str
    circuit_id: str
    circuit_name: str | None
    mode: PumpMode
    rpm_setpoint: float | None
    flow_setpoint_gpm: float | None


@dataclass(frozen=True, slots=True)
class PumpState:
    """Immutable snapshot of one IntelliCenter pump."""

    id: str
    name: str
    pump_type: PumpType
    is_running: bool
    power_watts: float | None
    rpm: float | None
    flow_gpm: float | None
    minimum_rpm: float | None
    maximum_rpm: float | None
    minimum_flow_gpm: float | None
    maximum_flow_gpm: float | None
    circuits: tuple[PumpCircuitState, ...]


@dataclass(frozen=True, slots=True)
class IntelliCenterSnapshot:
    """Immutable system-level read-model snapshot."""

    api_version: int
    connected: bool
    panel_name: str | None
    software_version: str | None
    temperature_unit: UnitOfTemperature
    bodies: tuple[BodyState, ...]
    circuits: tuple[CircuitState, ...]
    pumps: tuple[PumpState, ...]
