"""Canonical, immutable operations emitted by PoolOS execution layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


class ThermalBody(StrEnum):
    """Bodies commissioned for bounded thermal-source selection."""

    POOL = "pool"
    HOT_TUB = "hot_tub"


class PhysicalHeatMode(StrEnum):
    """Explicit physical heat-source selections understood by hardware."""

    OFF = "off"
    SOLAR = "solar"
    GAS = "gas"


def _require_identifier(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class PoolOperation:
    """Base class for transport- and vendor-independent PoolOS operations."""

    equipment_id: str
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    operation_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        _require_identifier(self.equipment_id, "equipment_id")
        _require_identifier(self.operation_id, "operation_id")
        if self.correlation_id is not None:
            _require_identifier(self.correlation_id, "correlation_id")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class SetPumpSpeed(PoolOperation):
    """Request a variable-speed pump setpoint in revolutions per minute."""

    rpm: int

    def __post_init__(self) -> None:
        super(SetPumpSpeed, self).__post_init__()
        if self.rpm <= 0:
            raise ValueError("rpm must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class StartPump(PoolOperation):
    """Request that a pump begin operating."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StopPump(PoolOperation):
    """Request that a pump stop operating."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SetHydraulicRoute(PoolOperation):
    """Request a route from one hydraulic body to another.

    ``equipment_id`` identifies the hydraulic system or shared-equipment group
    receiving the route request. Body identifiers refer to entries in the
    translation context equipment inventory.
    """

    suction_body_id: str
    return_body_id: str

    def __post_init__(self) -> None:
        super(SetHydraulicRoute, self).__post_init__()
        _require_identifier(self.suction_body_id, "suction_body_id")
        _require_identifier(self.return_body_id, "return_body_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class SetHeatMode(PoolOperation):
    """Request one commissioned physical heat source for one commissioned body."""

    mode: PhysicalHeatMode

    def __post_init__(self) -> None:
        super(SetHeatMode, self).__post_init__()
        try:
            body = ThermalBody(self.equipment_id)
        except ValueError as exc:
            raise ValueError("unsupported thermal body") from exc
        try:
            mode = PhysicalHeatMode(self.mode)
        except ValueError as exc:
            raise ValueError("unsupported physical heat mode") from exc
        object.__setattr__(self, "equipment_id", body.value)
        object.__setattr__(self, "mode", mode)
