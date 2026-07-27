"""Centralized logical Pentair command definitions.

These values describe vendor operations, not HTTP routes, payloads, protocol
bytes, or Home Assistant service calls. A later transport maps them to a
specific delivery mechanism.
"""

from __future__ import annotations

from enum import StrEnum


class PentairCommandOperation(StrEnum):
    """Logical Pentair operations understood by future transports."""

    START_PUMP = "pump.start"
    STOP_PUMP = "pump.stop"
    SET_PUMP_SPEED = "pump.set_speed"


class PentairCommandParameter(StrEnum):
    """Stable parameter names used by Pentair vendor commands."""

    RPM = "rpm"


__all__ = ["PentairCommandOperation", "PentairCommandParameter"]
