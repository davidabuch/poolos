"""Canonical PoolOS domain model.

The domain model describes physical pool installations independently of any
vendor adapter.  It intentionally separates physical topology, user-visible
features, and information quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, FrozenSet, Mapping, Optional


class TruthLevel(str, Enum):
    """How a value became known to PoolOS."""

    MEASURED = "measured"
    CALCULATED = "calculated"
    LEARNED = "learned"
    PREDICTED = "predicted"


class ConfidenceBand(str, Enum):
    """Human-readable confidence classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One explainable fact supporting a derived observation."""

    description: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("evidence description must not be empty")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("evidence weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Observation:
    """A measured or derived value with provenance and confidence."""

    name: str
    value: Any
    unit: Optional[str]
    truth_level: TruthLevel
    confidence: float = 1.0
    source: Optional[str] = None
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("observation name must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    @property
    def confidence_band(self) -> ConfidenceBand:
        if self.confidence >= 0.8:
            return ConfidenceBand.HIGH
        if self.confidence >= 0.5:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def explain(self) -> dict[str, Any]:
        """Return a stable, UI-friendly explanation payload."""

        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "truth_level": self.truth_level.value,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band.value,
            "source": self.source,
            "evidence": [item.description for item in self.evidence],
        }


class ResourceType(str, Enum):
    ELECTRICITY = "electricity"
    GAS = "gas"
    WATER = "water"
    TIME = "time"


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    resource_type: ResourceType
    external_source: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("resource id must not be empty")


@dataclass(frozen=True, slots=True)
class HydraulicRoute:
    """A logical or detailed water-routing configuration."""

    id: str
    name: str
    suction_body_ids: FrozenSet[str] = field(default_factory=frozenset)
    return_body_ids: FrozenSet[str] = field(default_factory=frozenset)
    required_equipment_ids: FrozenSet[str] = field(default_factory=frozenset)
    required_valve_positions: Mapping[str, str] = field(default_factory=dict)
    minimum_flow_gpm: Optional[float] = None
    minimum_pump_rpm: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("route id and name must not be empty")
        if self.minimum_flow_gpm is not None and self.minimum_flow_gpm < 0:
            raise ValueError("minimum flow must not be negative")
        if self.minimum_pump_rpm is not None and self.minimum_pump_rpm < 0:
            raise ValueError("minimum pump rpm must not be negative")
        object.__setattr__(self, "required_valve_positions", dict(self.required_valve_positions))


@dataclass(frozen=True, slots=True)
class Feature:
    """A user-visible pool function implemented by equipment and routes."""

    id: str
    name: str
    route_id: Optional[str] = None
    required_equipment_ids: FrozenSet[str] = field(default_factory=frozenset)
    minimum_pump_rpm: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("feature id and name must not be empty")


@dataclass(frozen=True, slots=True)
class PoolSystem:
    """One hydraulic system, potentially serving multiple bodies."""

    id: str
    name: str
    body_ids: FrozenSet[str] = field(default_factory=frozenset)
    equipment_ids: FrozenSet[str] = field(default_factory=frozenset)
    route_ids: FrozenSet[str] = field(default_factory=frozenset)
    feature_ids: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("system id and name must not be empty")


@dataclass(frozen=True, slots=True)
class Installation:
    """A property containing one or more independent pool systems."""

    id: str
    name: str
    systems: tuple[PoolSystem, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("installation id and name must not be empty")
        if not self.systems:
            raise ValueError("installation must contain at least one pool system")
        ids = [system.id for system in self.systems]
        if len(ids) != len(set(ids)):
            raise ValueError("pool system ids must be unique within an installation")

    def get_system(self, system_id: str) -> PoolSystem:
        for system in self.systems:
            if system.id == system_id:
                return system
        raise KeyError(system_id)
