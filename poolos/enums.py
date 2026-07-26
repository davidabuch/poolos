"""Enumerations shared by the PoolOS domain.

This module contains hardware-independent vocabulary used by PoolOS policies,
planning, execution, and advisory components. It must not import Home Assistant,
Pentair, or any other hardware-specific implementation.
"""

from __future__ import annotations

from enum import Enum, IntEnum


class BodyType(str, Enum):
    """A controllable body of water."""

    POOL = "pool"
    SPA = "spa"


class EquipmentType(str, Enum):
    """Hardware-independent equipment categories recognized by PoolOS."""

    PUMP = "pump"
    HEATER = "heater"
    CHLORINATOR = "chlorinator"
    LIGHT = "light"
    VALVE = "valve"
    BLOWER = "blower"
    WATER_FEATURE = "water_feature"
    CLEANER = "cleaner"
    SENSOR = "sensor"
    FILTER = "filter"
    COVER = "cover"


class HeatingSource(str, Enum):
    """Heating technologies that may be available to a water body."""

    GAS = "gas"
    SOLAR = "solar"
    HEAT_PUMP = "heat_pump"
    HYBRID = "hybrid"


class PolicyPriority(IntEnum):
    """Priority used when resolving competing policy requests.

    Higher numeric values take precedence over lower values.
    """

    BACKGROUND = 100
    OPTIMIZATION = 250
    USER_REQUEST = 500
    SAFETY = 1_000
    EMERGENCY = 2_000


class CommandPriority(IntEnum):
    """Priority used when ordering commands in the execution queue.

    Higher numeric values are executed before lower values when commands are
    otherwise eligible to run.
    """

    LOW = 100
    NORMAL = 250
    HIGH = 500
    CRITICAL = 1_000


class RecommendationSeverity(IntEnum):
    """Severity assigned to an Advisor recommendation."""

    INFORMATIONAL = 10
    NOTICE = 20
    WARNING = 30
    CRITICAL = 40