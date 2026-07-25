"""Strongly typed capabilities exposed by PoolOS equipment."""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """A hardware-independent behavior an equipment item can provide."""

    CIRCULATION = "circulation"
    VARIABLE_SPEED = "variable_speed"
    HEATING = "heating"
    COOLING = "cooling"
    LIGHTING = "lighting"
    SANITIZATION = "sanitization"
    TEMPERATURE_SENSING = "temperature_sensing"
    FLOW_SENSING = "flow_sensing"
    POWER_MONITORING = "power_monitoring"
