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
    START_STOP = "start_stop"
    RPM_CONTROL = "rpm_control"
    RPM_SENSING = "rpm_sensing"
    PRESSURE_SENSING = "pressure_sensing"
    VALVE_POSITIONING = "valve_positioning"
    FILTERING = "filtering"
    MAINTENANCE_TRACKING = "maintenance_tracking"
    HEALTH_ESTIMATION = "health_estimation"
    FAULT_REPORTING = "fault_reporting"
