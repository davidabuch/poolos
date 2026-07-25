"""Core immutable PoolOS domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .enums import BodyType


@dataclass(frozen=True, slots=True)
class TemperatureState:
    """Represents the current temperature state of a body of water."""

    current: float
    target: Optional[float]
    heating: bool


@dataclass(frozen=True, slots=True)
class BodyState:
    """Represents the complete state of a pool or spa."""

    body: BodyType
    temperature: TemperatureState
    circulation_running: bool
    sanitizer_enabled: bool