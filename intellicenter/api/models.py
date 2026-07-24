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


class BodyHeatMode(StrEnum):
    """Normalized user-selectable heating strategy for a Pool/Spa body."""

    OFF = "off"
    GAS = "gas"
    SOLAR = "solar"
    SOLAR_PREFERRED = "solar_preferred"
    ELECTRIC = "electric"
    HEAT_PUMP = "heat_pump"
    HYBRID = "hybrid"
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


class ChemistryType(StrEnum):
    """Normalized IntelliCenter chemistry-controller type."""

    INTELLICHEM = "intellichem"
    INTELLICHLOR = "intellichlor"
    UNKNOWN = "unknown"


class TemperatureSensorType(StrEnum):
    """Normalized physical IntelliCenter temperature-probe type."""

    AIR = "air"
    WATER = "water"
    SOLAR = "solar"
    UNKNOWN = "unknown"


class SystemMode(StrEnum):
    """Normalized IntelliCenter controller operating mode."""

    AUTO = "auto"
    SERVICE = "service"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class PumpMode(StrEnum):
    """Normalized per-circuit pump control mode."""

    RPM = "rpm"
    GPM = "gpm"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TemperatureSensorState:
    """Immutable snapshot of one physical IntelliCenter temperature probe."""

    id: str
    name: str
    sensor_type: TemperatureSensorType
    subtype: str | None
    temperature: float | None


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
    selected_heat_mode: BodyHeatMode
    available_heat_modes: tuple[BodyHeatMode, ...]
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
class ChemistryState:
    """Immutable snapshot of one IntelliChem or IntelliChlor controller."""

    id: str
    name: str
    chemistry_type: ChemistryType
    subtype: str | None
    body_ids: tuple[str, ...]
    body_names: tuple[str, ...]
    ph: float | None
    orp_mv: float | None
    water_quality: float | str | None
    ph_setpoint: float | None
    orp_setpoint_mv: int | None
    alkalinity_ppm: int | None
    calcium_hardness_ppm: int | None
    cyanuric_acid_ppm: int | None
    ph_tank_level: int | None
    orp_tank_level: int | None
    ph_dosing_volume_ml: float | None
    orp_dosing_volume_ml: float | None
    ph_high_alarm: bool
    ph_low_alarm: bool
    orp_high_alarm: bool
    orp_low_alarm: bool
    salt_ppm: int | None
    primary_output_percent: int | None
    secondary_output_percent: int | None
    superchlorinate: bool


@dataclass(frozen=True, slots=True)
class CoverState:
    """Immutable snapshot of one IntelliCenter external cover."""

    id: str
    name: str
    subtype: str | None
    is_closed: bool | None
    status_is_on: bool | None
    normal_is_on: bool | None


@dataclass(frozen=True, slots=True)
class SystemState:
    """Immutable snapshot of controller-wide IntelliCenter state."""

    id: str
    name: str
    operating_mode: SystemMode
    raw_operating_mode: str | None
    controller_mode: str | None
    vacation_mode: bool
    firmware_version: str | None


@dataclass(frozen=True, slots=True)
class IntelliCenterSnapshot:
    """Immutable system-level read-model snapshot."""

    api_version: int
    connected: bool
    panel_name: str | None
    software_version: str | None
    temperature_unit: UnitOfTemperature
    temperature_sensors: tuple[TemperatureSensorState, ...]
    bodies: tuple[BodyState, ...]
    circuits: tuple[CircuitState, ...]
    pumps: tuple[PumpState, ...]
    chemistries: tuple[ChemistryState, ...]
    covers: tuple[CoverState, ...]
    system: SystemState | None
