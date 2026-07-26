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
    FLOW_CONTROL = "flow_control"
    BRIGHTNESS_CONTROL = "brightness_control"
    COLOR_CONTROL = "color_control"
    EFFECT_CONTROL = "effect_control"
    VALVE_STOP = "valve_stop"
    TARGET_TEMPERATURE_CONTROL = "target_temperature_control"
    OUTPUT_CONTROL = "output_control"
    SALT_SENSING = "salt_sensing"
    COVER_POSITIONING = "cover_positioning"
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
