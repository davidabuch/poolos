"""Immutable public data models for the Buch IntelliCenter API."""

from __future__ import annotations

from dataclasses import dataclass

from .enums import (
    AvailabilityState,
    BodyHVACAction,
    BodyHVACMode,
    BodyKind,
)


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    """Snapshot of IntelliCenter controller status."""

    connected: bool
    property_name: str | None
    software_version: str | None


@dataclass(frozen=True, slots=True)
class BodyCapabilities:
    """Operations and features supported by a body."""

    can_enable: bool
    can_set_heating_temperature: bool
    can_set_cooling_temperature: bool
    can_select_heater: bool
    can_select_operation_mode: bool
    supports_heating: bool
    supports_cooling: bool


@dataclass(frozen=True, slots=True)
class BodyState:
    """Normalized snapshot of a pool or spa body."""

    id: str
    name: str
    kind: BodyKind
    availability: AvailabilityState
    enabled: bool | None
    current_temperature: float | None
    heating_setpoint: float | None
    cooling_setpoint: float | None
    hvac_mode: BodyHVACMode
    hvac_action: BodyHVACAction
    selected_heater_id: str | None
    heater_ids: tuple[str, ...]
    operation_mode: str | None
    available_operation_modes: tuple[str, ...]
    capabilities: BodyCapabilities
