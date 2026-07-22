"""Normalized public enums for the Buch IntelliCenter API."""

from __future__ import annotations

from enum import StrEnum


class AvailabilityState(StrEnum):
    """Availability of a controller-backed object."""

    AVAILABLE = "available"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class BodyKind(StrEnum):
    """Normalized IntelliCenter body type."""

    POOL = "pool"
    SPA = "spa"
    UNKNOWN = "unknown"


class BodyHVACMode(StrEnum):
    """Normalized configured HVAC mode for a body."""

    OFF = "off"
    HEAT = "heat"
    HEAT_COOL = "heat_cool"
    UNKNOWN = "unknown"


class BodyHVACAction(StrEnum):
    """Normalized current HVAC activity for a body."""

    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    UNKNOWN = "unknown"
