"""Canonical typed observation model for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ..clock import Clock


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


class ObservationSourceKind(str, Enum):
    """Canonical provenance categories for PoolOS observations."""

    LIVE = "live"
    SIMULATED = "simulated"
    DERIVED = "derived"


class ObservationQuality(str, Enum):
    """Intrinsic usability of an observation, independent of confidence."""

    UNKNOWN = "unknown"
    GOOD = "good"
    DEGRADED = "degraded"
    SUSPECT = "suspect"
    INVALID = "invalid"


class ObservationFreshness(str, Enum):
    """Dynamic freshness result evaluated against a runtime clock."""

    UNKNOWN = "unknown"
    FRESH = "fresh"
    STALE = "stale"
    FUTURE = "future"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Maximum accepted age and clock-skew tolerance for observations."""

    max_age: timedelta
    future_tolerance: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.max_age < timedelta(0):
            raise ValueError("max_age must not be negative")
        if self.future_tolerance < timedelta(0):
            raise ValueError("future_tolerance must not be negative")


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


@dataclass(frozen=True, slots=True, init=False)
class PoolObservation:
    """One typed PoolOS observation with provenance and temporal semantics.

    ``observation_id`` is the canonical identity. ``name`` and ``source`` are
    accepted as constructor aliases for compatibility with the pre-10.5B API.
    Freshness is never stored; it is evaluated dynamically from ``observed_at``
    using an injected runtime clock.
    """

    observation_id: str
    value: Any
    unit: str | None
    truth_level: TruthLevel
    observed_at: datetime | None
    source_kind: ObservationSourceKind
    source_id: str | None
    quality: ObservationQuality
    confidence: float
    evidence: tuple[Evidence, ...]

    def __init__(
        self,
        observation_id: str | None = None,
        value: Any = None,
        unit: str | None = None,
        truth_level: TruthLevel = TruthLevel.MEASURED,
        *,
        observed_at: datetime | None = None,
        source_kind: ObservationSourceKind = ObservationSourceKind.DERIVED,
        source_id: str | None = None,
        quality: ObservationQuality = ObservationQuality.UNKNOWN,
        confidence: float = 1.0,
        evidence: tuple[Evidence, ...] = (),
        name: str | None = None,
        source: str | None = None,
    ) -> None:
        resolved_id = _resolve_compatibility_value(
            canonical=observation_id,
            compatibility=name,
            canonical_name="observation_id",
            compatibility_name="name",
        )
        resolved_source = _resolve_compatibility_value(
            canonical=source_id,
            compatibility=source,
            canonical_name="source_id",
            compatibility_name="source",
            required=False,
        )

        object.__setattr__(self, "observation_id", resolved_id)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "truth_level", TruthLevel(truth_level))
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_kind", ObservationSourceKind(source_kind))
        object.__setattr__(self, "source_id", resolved_source)
        object.__setattr__(self, "quality", ObservationQuality(quality))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence", tuple(evidence))
        self._validate()

    def _validate(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id must not be empty")
        if self.source_id is not None and not self.source_id.strip():
            raise ValueError("source_id must not be empty when provided")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    @property
    def name(self) -> str:
        """Compatibility alias for ``observation_id``."""

        return self.observation_id

    @property
    def source(self) -> str | None:
        """Compatibility alias for ``source_id``."""

        return self.source_id

    @property
    def confidence_band(self) -> ConfidenceBand:
        if self.confidence >= 0.8:
            return ConfidenceBand.HIGH
        if self.confidence >= 0.5:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def freshness(
        self,
        *,
        clock: Clock,
        policy: FreshnessPolicy,
    ) -> ObservationFreshness:
        """Evaluate freshness from the observation timestamp and runtime clock."""

        if self.observed_at is None:
            return ObservationFreshness.UNKNOWN

        now = clock.now()
        if now.tzinfo is None:
            raise ValueError("runtime clock must return a timezone-aware datetime")

        age = now - self.observed_at
        if age < -policy.future_tolerance:
            return ObservationFreshness.FUTURE
        if age > policy.max_age:
            return ObservationFreshness.STALE
        return ObservationFreshness.FRESH

    def explain(self) -> dict[str, Any]:
        """Return a stable, UI-friendly explanation payload."""

        return {
            "observation_id": self.observation_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "truth_level": self.truth_level.value,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source_kind": self.source_kind.value,
            "source_id": self.source_id,
            "source": self.source,
            "quality": self.quality.value,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band.value,
            "evidence": [item.description for item in self.evidence],
        }


def _resolve_compatibility_value(
    *,
    canonical: str | None,
    compatibility: str | None,
    canonical_name: str,
    compatibility_name: str,
    required: bool = True,
) -> str | None:
    if canonical is not None and compatibility is not None and canonical != compatibility:
        raise ValueError(
            f"{canonical_name} and compatibility alias {compatibility_name} must match"
        )
    value = canonical if canonical is not None else compatibility
    if required and value is None:
        raise TypeError(f"missing required argument: {canonical_name!r}")
    return value


Observation = PoolObservation


__all__ = [
    "ConfidenceBand",
    "Evidence",
    "FreshnessPolicy",
    "Observation",
    "ObservationFreshness",
    "ObservationQuality",
    "ObservationSourceKind",
    "PoolObservation",
    "TruthLevel",
]
