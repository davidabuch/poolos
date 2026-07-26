"""Lightweight operational memory for PoolOS.

Runtime memory records bounded, installation-specific observations and exposes
simple predictions. It never creates or executes commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil
from statistics import fmean, median
from typing import Iterable, Optional

from .clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class MemorySample:
    metric: str
    value: float
    observed_at: datetime
    tags: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric must not be empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("memory sample timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MemorySummary:
    metric: str
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    percentile_95: float
    latest: float


@dataclass(slots=True)
class RuntimeMemory:
    """Bounded rolling metrics store with deterministic prediction helpers."""

    clock: Clock = field(default_factory=SystemClock)
    retention_per_metric: int = 200
    _samples: dict[str, list[MemorySample]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retention_per_metric < 1:
            raise ValueError("retention_per_metric must be at least one")

    def observe(
        self,
        metric: str,
        value: float,
        *,
        observed_at: Optional[datetime] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> MemorySample:
        """Record one numeric observation and enforce bounded retention."""

        timestamp = observed_at or self.clock.now()
        sample = MemorySample(
            metric=metric,
            value=float(value),
            observed_at=timestamp,
            tags=tuple(sorted((tags or {}).items())),
        )
        bucket = self._samples.setdefault(metric, [])
        bucket.append(sample)
        if len(bucket) > self.retention_per_metric:
            del bucket[: len(bucket) - self.retention_per_metric]
        return sample

    def samples(self, metric: str) -> tuple[MemorySample, ...]:
        return tuple(self._samples.get(metric, ()))

    def metrics(self) -> tuple[str, ...]:
        return tuple(sorted(self._samples))

    def summary(self, metric: str) -> Optional[MemorySummary]:
        samples = self._samples.get(metric)
        if not samples:
            return None
        values = sorted(sample.value for sample in samples)
        index = max(0, ceil(0.95 * len(values)) - 1)
        return MemorySummary(
            metric=metric,
            count=len(values),
            minimum=values[0],
            maximum=values[-1],
            mean=fmean(values),
            median=median(values),
            percentile_95=values[index],
            latest=samples[-1].value,
        )

    def predict(self, metric: str, *, default: Optional[float] = None) -> Optional[float]:
        """Return the rolling mean, or ``default`` when no history exists."""

        summary = self.summary(metric)
        return summary.mean if summary is not None else default

    def recommended_delay(
        self,
        metric: str,
        default: timedelta,
        *,
        safety_factor: float = 1.25,
        minimum_samples: int = 3,
    ) -> timedelta:
        """Suggest a conservative delay based on the observed 95th percentile."""

        if safety_factor <= 0:
            raise ValueError("safety_factor must be positive")
        summary = self.summary(metric)
        if summary is None or summary.count < minimum_samples:
            return default
        seconds = max(0.0, summary.percentile_95 * safety_factor)
        return timedelta(seconds=seconds)

    def snapshot(self) -> dict[str, tuple[MemorySample, ...]]:
        """Return a serializable-boundary snapshot for persistence adapters."""

        return {metric: tuple(samples) for metric, samples in self._samples.items()}

    def restore(self, samples: Iterable[MemorySample]) -> None:
        """Restore samples through the normal retention path."""

        for sample in sorted(samples, key=lambda item: item.observed_at):
            self.observe(
                sample.metric,
                sample.value,
                observed_at=sample.observed_at,
                tags=dict(sample.tags),
            )
