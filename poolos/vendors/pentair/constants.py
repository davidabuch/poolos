"""Stable Pentair vocabulary used by PoolOS.

These constants describe Pentair concepts, not wire-protocol values. Raw
protocol numbers and byte encodings belong in a future transport/protocol layer.
"""
from __future__ import annotations

from enum import Enum


class PentairControllerFamily(str, Enum):
    INTELLICENTER = "intellicenter"
    EASYTOUCH = "easytouch"
    INTELLITOUCH = "intellitouch"
    SUNTOUCH = "suntouch"
    UNKNOWN = "unknown"


class PentairObjectKind(str, Enum):
    SYSTEM = "system"
    BODY = "body"
    CIRCUIT = "circuit"
    CIRCUIT_GROUP = "circuit_group"
    FEATURE = "feature"
    PUMP = "pump"
    HEATER = "heater"
    VALVE = "valve"
    CHLORINATOR = "chlorinator"
    LIGHT = "light"
    SENSOR = "sensor"
    FILTER = "filter"
    UNKNOWN = "unknown"


class PentairBodyKind(str, Enum):
    POOL = "pool"
    SPA = "spa"
    BODY_3 = "body_3"
    BODY_4 = "body_4"
    UNKNOWN = "unknown"


class PentairCircuitKind(str, Enum):
    RELAY = "relay"
    FEATURE = "feature"
    GROUP = "group"
    BODY = "body"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


class PentairCircuitFunction(str, Enum):
    GENERIC = "generic"
    POOL = "pool"
    SPA = "spa"
    LIGHT = "light"
    CLEANER = "cleaner"
    WATER_FEATURE = "water_feature"
    SPILLWAY = "spillway"
    BLOWER = "blower"
    SLIDE = "slide"
    FREEZE_PROTECT = "freeze_protect"
    UNKNOWN = "unknown"


class PentairHeatMode(str, Enum):
    OFF = "off"
    HEATER = "heater"
    SOLAR = "solar"
    SOLAR_PREFERRED = "solar_preferred"
    HEAT_PUMP = "heat_pump"
    HEAT_PUMP_PREFERRED = "heat_pump_preferred"
    HYBRID = "hybrid"
    DONT_CHANGE = "dont_change"
    UNKNOWN = "unknown"


class PentairHeatSource(str, Enum):
    GAS = "gas"
    ELECTRIC = "electric"
    HEAT_PUMP = "heat_pump"
    SOLAR = "solar"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class PentairPumpControlMode(str, Enum):
    SINGLE_SPEED = "single_speed"
    TWO_SPEED = "two_speed"
    VARIABLE_SPEED = "variable_speed"
    VARIABLE_FLOW = "variable_flow"
    VARIABLE_SPEED_FLOW = "variable_speed_flow"
    UNKNOWN = "unknown"


class PentairPumpSetpointKind(str, Enum):
    RPM = "rpm"
    GPM = "gpm"
    RELAY = "relay"


class PentairValveRole(str, Enum):
    INTAKE = "intake"
    RETURN = "return"
    AUXILIARY = "auxiliary"
    SOLAR = "solar"
    UNKNOWN = "unknown"


class PentairTemperatureUnit(str, Enum):
    FAHRENHEIT = "fahrenheit"
    CELSIUS = "celsius"


class PentairFreezeProtection(str, Enum):
    DISABLED = "disabled"
    ELIGIBLE = "eligible"
    ACTIVE = "active"
    UNKNOWN = "unknown"
