"""Canonical provider-independent forecast models for PoolOS planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional


class ForecastFreshness(str, Enum):
    """Age classification for a forecast snapshot."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"


class ForecastConfidence(str, Enum):
    """Normalized provider-confidence classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ForecastFreshnessPolicy:
    """Explicit age thresholds used to assess forecast usability."""

    fresh_for: timedelta = timedelta(hours=1)
    aging_for: timedelta = timedelta(hours=3)
    stale_for: timedelta = timedelta(hours=6)

    def __post_init__(self) -> None:
        if self.fresh_for < timedelta(0):
            raise ValueError("fresh_for must not be negative")
        if self.aging_for < self.fresh_for:
            raise ValueError("aging_for must be greater than or equal to fresh_for")
        if self.stale_for < self.aging_for:
            raise ValueError("stale_for must be greater than or equal to aging_for")

    def classify(self, issued_at: datetime, now: datetime) -> ForecastFreshness:
        """Classify the snapshot age at a timezone-aware instant."""

        if issued_at.tzinfo is None or now.tzinfo is None:
            raise ValueError("forecast freshness times must be timezone-aware")
        age = now - issued_at
        if age < timedelta(0):
            raise ValueError("forecast issued_at must not be in the future")
        if age <= self.fresh_for:
            return ForecastFreshness.FRESH
        if age <= self.aging_for:
            return ForecastFreshness.AGING
        if age <= self.stale_for:
            return ForecastFreshness.STALE
        return ForecastFreshness.EXPIRED


@dataclass(frozen=True, slots=True)
class ForecastSnapshot:
    """Canonical environmental forecast consumed by planning intelligence."""

    provider: str
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    ambient_temperature_f: Optional[float] = None
    overnight_low_temperature_f: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    cloud_cover_percent: Optional[float] = None
    solar_production_kw: Optional[float] = None
    provider_confidence: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be blank")
        for value in (self.issued_at, self.valid_from, self.valid_until):
            if value.tzinfo is None:
                raise ValueError("forecast timestamps must be timezone-aware")
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.wind_speed_mph is not None and self.wind_speed_mph < 0:
            raise ValueError("wind_speed_mph must not be negative")
        if self.cloud_cover_percent is not None and not 0 <= self.cloud_cover_percent <= 100:
            raise ValueError("cloud_cover_percent must be between 0 and 100")
        if self.solar_production_kw is not None and self.solar_production_kw < 0:
            raise ValueError("solar_production_kw must not be negative")
        if self.provider_confidence is not None and not 0 <= self.provider_confidence <= 1:
            raise ValueError("provider_confidence must be between 0 and 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def confidence(self) -> ForecastConfidence:
        """Normalize a provider score to PoolOS confidence categories."""

        if self.provider_confidence is None:
            return ForecastConfidence.UNKNOWN
        if self.provider_confidence >= 0.8:
            return ForecastConfidence.HIGH
        if self.provider_confidence >= 0.5:
            return ForecastConfidence.MEDIUM
        return ForecastConfidence.LOW

    def freshness(
        self,
        now: datetime,
        policy: ForecastFreshnessPolicy = ForecastFreshnessPolicy(),
    ) -> ForecastFreshness:
        """Return the snapshot's age classification."""

        return policy.classify(self.issued_at, now)

    def covers(self, instant: datetime) -> bool:
        """Return whether the snapshot's validity window contains an instant."""

        if instant.tzinfo is None:
            raise ValueError("forecast coverage instant must be timezone-aware")
        return self.valid_from <= instant <= self.valid_until

    def to_dict(self) -> dict[str, Any]:
        """Produce a stable serialization-friendly representation."""

        return {
            "ambient_temperature_f": self.ambient_temperature_f,
            "cloud_cover_percent": self.cloud_cover_percent,
            "confidence": self.confidence.value,
            "issued_at": self.issued_at.isoformat(),
            "metadata": dict(sorted(self.metadata.items())),
            "overnight_low_temperature_f": self.overnight_low_temperature_f,
            "provider": self.provider,
            "provider_confidence": self.provider_confidence,
            "solar_production_kw": self.solar_production_kw,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "wind_speed_mph": self.wind_speed_mph,
        }
