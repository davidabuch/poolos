"""Canonical observation model for PoolOS.

This module owns the single observation type used across PoolOS.  The legacy
``poolos.domain.Observation`` name remains a compatibility alias to
``PoolObservation`` during migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


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
class PoolObservation:
    """A measured or derived value with provenance and confidence.

    This is the canonical PoolOS observation model.  Milestone 10.5B will
    evolve it with operational timestamps, source classification, quality,
    freshness evaluation, and storage semantics.
    """

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


# Temporary source-compatibility name.  It is intentionally an alias, not a
# subclass, so old and new imports identify the exact same runtime type.
Observation = PoolObservation


__all__ = [
    "ConfidenceBand",
    "Evidence",
    "Observation",
    "PoolObservation",
    "TruthLevel",
]
