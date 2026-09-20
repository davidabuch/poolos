"""Bounded Pool circulation hold after native Solar delivery stops.

This policy does not own equipment and does not decide Solar eligibility.
It classifies one native Solar-active -> off transition as either:
- a temporary interruption worth holding Pool circulation at ordinary RPM, or
- an established sustained-decline episode that should fall through to the
  existing circulation-successor/shutdown policy.

The hold is deliberately bounded and fail-closed.  It never creates Solar
ownership and never bypasses normal Solar re-entry criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import math


class SolarRecoveryDisposition(StrEnum):
    INACTIVE = "inactive"
    HOLD = "hold"
    END_OF_DAY = "end_of_day"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SolarRecoveryPolicy:
    recovery_hold: timedelta = timedelta(minutes=10)
    trend_window: timedelta = timedelta(minutes=30)
    minimum_trend_span: timedelta = timedelta(minutes=20)
    end_of_day_drop_f: float = 8.0
    end_of_day_declining_fraction: float = 0.75
    end_of_day_collector_ceiling_f: float = 95.0
    sample_limit: int = 96

    def __post_init__(self) -> None:
        if self.recovery_hold <= timedelta(0):
            raise ValueError("recovery_hold must be positive")
        if self.trend_window <= timedelta(0):
            raise ValueError("trend_window must be positive")
        if self.minimum_trend_span <= timedelta(0):
            raise ValueError("minimum_trend_span must be positive")
        if self.minimum_trend_span > self.trend_window:
            raise ValueError("minimum_trend_span cannot exceed trend_window")
        for name in (
            "end_of_day_drop_f",
            "end_of_day_declining_fraction",
            "end_of_day_collector_ceiling_f",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.end_of_day_drop_f <= 0:
            raise ValueError("end_of_day_drop_f must be positive")
        if not 0.5 <= self.end_of_day_declining_fraction <= 1.0:
            raise ValueError("end_of_day_declining_fraction must be between 0.5 and 1")
        if self.sample_limit < 4:
            raise ValueError("sample_limit must be at least four")


@dataclass(frozen=True, slots=True)
class SolarRecoveryAssessment:
    disposition: SolarRecoveryDisposition
    evaluated_at: datetime
    hold_until: datetime | None
    reason_code: str
    trend_span_seconds: int
    trend_drop_f: float | None
    declining_fraction: float | None

    @property
    def hold_active(self) -> bool:
        return self.disposition is SolarRecoveryDisposition.HOLD


@dataclass(slots=True)
class SolarRecoveryTracker:
    policy: SolarRecoveryPolicy = SolarRecoveryPolicy()
    _samples: list[tuple[datetime, float]] = field(default_factory=list, init=False)
    _previous_solar_active: bool | None = field(default=None, init=False)
    _hold_until: datetime | None = field(default=None, init=False)
    _last_evaluated_at: datetime | None = field(default=None, init=False)

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
        collector_temperature_f: float | None,
        solar_active: bool | None,
        pool_active: bool | None,
        pool_heating_demand: bool | None,
    ) -> SolarRecoveryAssessment:
        _require_aware(evaluated_at)
        if (
            self._last_evaluated_at is not None
            and evaluated_at < self._last_evaluated_at
        ):
            raise ValueError("solar recovery observations must be chronological")
        self._last_evaluated_at = evaluated_at
        self._append_sample(evaluated_at, collector_temperature_f)

        transition_off = (
            self._previous_solar_active is True and solar_active is False
        )
        self._previous_solar_active = solar_active

        if solar_active is True:
            self._hold_until = None
            return self._assessment(
                SolarRecoveryDisposition.INACTIVE,
                evaluated_at,
                "solar_delivery_active",
            )
        if pool_active is not True or pool_heating_demand is not True:
            self._hold_until = None
            return self._assessment(
                SolarRecoveryDisposition.INACTIVE,
                evaluated_at,
                "recovery_not_applicable",
            )

        if transition_off:
            trend = self._trend(evaluated_at)
            if self._is_sustained_end_of_day_decline(
                collector_temperature_f,
                trend,
            ):
                self._hold_until = None
                return self._assessment(
                    SolarRecoveryDisposition.END_OF_DAY,
                    evaluated_at,
                    "solar_native_off_sustained_decline",
                    trend=trend,
                )
            self._hold_until = evaluated_at + self.policy.recovery_hold
            return self._assessment(
                SolarRecoveryDisposition.HOLD,
                evaluated_at,
                "solar_native_off_recovery_hold_started",
                trend=trend,
            )

        if self._hold_until is not None:
            if evaluated_at < self._hold_until:
                return self._assessment(
                    SolarRecoveryDisposition.HOLD,
                    evaluated_at,
                    "solar_recovery_hold_active",
                )
            self._hold_until = None
            return self._assessment(
                SolarRecoveryDisposition.EXPIRED,
                evaluated_at,
                "solar_recovery_hold_expired",
            )

        return self._assessment(
            SolarRecoveryDisposition.INACTIVE,
            evaluated_at,
            "no_solar_recovery_hold",
        )

    def reset(self) -> None:
        self._samples.clear()
        self._previous_solar_active = None
        self._hold_until = None
        self._last_evaluated_at = None

    def _append_sample(
        self,
        evaluated_at: datetime,
        collector_temperature_f: float | None,
    ) -> None:
        if collector_temperature_f is not None and math.isfinite(
            collector_temperature_f
        ):
            self._samples.append((evaluated_at, float(collector_temperature_f)))
        cutoff = evaluated_at - self.policy.trend_window
        self._samples[:] = [
            sample for sample in self._samples if sample[0] >= cutoff
        ][-self.policy.sample_limit :]

    def _trend(
        self,
        evaluated_at: datetime,
    ) -> tuple[timedelta, float, float] | None:
        cutoff = evaluated_at - self.policy.trend_window
        samples = [sample for sample in self._samples if sample[0] >= cutoff]
        if len(samples) < 3:
            return None
        span = samples[-1][0] - samples[0][0]
        if span <= timedelta(0):
            return None
        net_drop = samples[0][1] - samples[-1][1]
        comparisons = [
            later[1] <= earlier[1]
            for earlier, later in zip(samples, samples[1:], strict=False)
        ]
        declining_fraction = sum(comparisons) / len(comparisons)
        return span, net_drop, declining_fraction

    def _is_sustained_end_of_day_decline(
        self,
        collector_temperature_f: float | None,
        trend: tuple[timedelta, float, float] | None,
    ) -> bool:
        if collector_temperature_f is None or trend is None:
            return False
        span, net_drop, declining_fraction = trend
        return (
            span >= self.policy.minimum_trend_span
            and net_drop >= self.policy.end_of_day_drop_f
            and declining_fraction >= self.policy.end_of_day_declining_fraction
            and collector_temperature_f
            <= self.policy.end_of_day_collector_ceiling_f
        )

    def _assessment(
        self,
        disposition: SolarRecoveryDisposition,
        evaluated_at: datetime,
        reason_code: str,
        *,
        trend: tuple[timedelta, float, float] | None = None,
    ) -> SolarRecoveryAssessment:
        span = timedelta(0)
        drop: float | None = None
        fraction: float | None = None
        if trend is not None:
            span, drop, fraction = trend
        return SolarRecoveryAssessment(
            disposition=disposition,
            evaluated_at=evaluated_at,
            hold_until=self._hold_until,
            reason_code=reason_code,
            trend_span_seconds=int(span.total_seconds()),
            trend_drop_f=drop,
            declining_fraction=fraction,
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("solar recovery timestamp must be timezone-aware")


__all__ = [
    "SolarRecoveryAssessment",
    "SolarRecoveryDisposition",
    "SolarRecoveryPolicy",
    "SolarRecoveryTracker",
]
