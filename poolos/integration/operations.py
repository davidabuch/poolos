"""Canonical, immutable operations emitted by PoolOS execution layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


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
class SetHeatMode(PoolOperation):
    """Request a hardware-independent heat mode for a body or heater."""

    mode: str

    def __post_init__(self) -> None:
        super(SetHeatMode, self).__post_init__()
        _require_identifier(self.mode, "mode")
