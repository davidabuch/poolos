"""Centralized logical Pentair command definitions."""

from __future__ import annotations

from enum import StrEnum


class PentairCommandOperation(StrEnum):
    """Logical Pentair operations understood by future transports."""

    START_PUMP = "pump.start"
    STOP_PUMP = "pump.stop"
    SET_PUMP_SPEED = "pump.set_speed"
    SET_HYDRAULIC_ROUTE = "hydraulics.set_route"


class PentairCommandParameter(StrEnum):
    """Stable parameter names used by Pentair vendor commands."""

    RPM = "rpm"
    SUCTION_BODY_ID = "suction_body_id"
    SUCTION_BODY_KIND = "suction_body_kind"
    SUCTION_CIRCUIT_ID = "suction_circuit_id"
    RETURN_BODY_ID = "return_body_id"
    RETURN_BODY_KIND = "return_body_kind"
    RETURN_CIRCUIT_ID = "return_circuit_id"
    SHARED_EQUIPMENT_GROUP = "shared_equipment_group"
    INTAKE_VALVE_ID = "intake_valve_id"
    RETURN_VALVE_ID = "return_valve_id"


__all__ = ["PentairCommandOperation", "PentairCommandParameter"]
