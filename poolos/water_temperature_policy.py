"""Demand-driven trusted pool-water temperature acquisition policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math

from .operating_baselines import PumpOperatingBaselines


@dataclass(frozen=True, slots=True)
class WaterTemperaturePolicy:
    trusted_after_circulation: timedelta = timedelta(minutes=30)
    minimum_probe_duration: timedelta = timedelta(minutes=2)
    stability_window: timedelta = timedelta(minutes=1)
    maximum_probe_duration: timedelta = timedelta(minutes=5)
    maximum_smooth_rate_f_per_minute: float = 2.0
    collector_actionable_f: float = 90.0
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()


@dataclass(frozen=True, slots=True)
class TemperatureSample:
    observed_at: datetime
    temperature_f: float

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("sample observed_at must be timezone-aware")
        if not math.isfinite(self.temperature_f):
            raise ValueError("sample temperature must be finite")


class WaterTemperatureDisposition(str, Enum):
    TRUSTED = "trusted"
    REUSED = "reused"
    NOT_REQUIRED = "not_required"
    PROBE_REQUIRED = "probe_required"
    PROBING = "probing"
    ACQUISITION_FAILED = "acquisition_failed"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, slots=True)
class WaterTemperatureAssessment:
    evaluated_at: datetime
    disposition: WaterTemperatureDisposition
    trusted_temperature_f: float | None
    trusted_at: datetime | None
    recommended_pump_rpm: int | None
    reason_code: str
    authority: str = "none"
    command_delivery_enabled: bool = False


class WaterTemperatureTracker:
    """Retain only proven bulk-water evidence and bounded probe state."""

    def __init__(self, policy: WaterTemperaturePolicy = WaterTemperaturePolicy()) -> None:
        self._policy = policy
        self._trusted_temperature_f: float | None = None
        self._trusted_at: datetime | None = None
        self._last_evaluated_at: datetime | None = None

    def _result(
        self,
        at: datetime,
        disposition: WaterTemperatureDisposition,
        reason: str,
        rpm: int | None = None,
    ) -> WaterTemperatureAssessment:
        return WaterTemperatureAssessment(
            at,
            disposition,
            self._trusted_temperature_f,
            self._trusted_at,
            rpm,
            reason,
        )

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
        observed_temperature_f: float | None,
        pool_circulating: bool,
        probe_active: bool,
        probe_started_at: datetime | None,
        samples: tuple[TemperatureSample, ...] = (),
        collector_temperature_f: float | None,
        thermal_decision_requested: bool,
    ) -> WaterTemperatureAssessment:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self._last_evaluated_at is not None and evaluated_at < self._last_evaluated_at:
            raise ValueError("temperature evaluations must be chronological")
        self._last_evaluated_at = evaluated_at

        if pool_circulating and not probe_active and observed_temperature_f is not None:
            self._trusted_temperature_f = observed_temperature_f
            self._trusted_at = evaluated_at
            return self._result(evaluated_at, WaterTemperatureDisposition.TRUSTED, "existing_circulation")

        if probe_active:
            if probe_started_at is None:
                return self._result(evaluated_at, WaterTemperatureDisposition.UNTRUSTED, "probe_start_missing")
            elapsed = evaluated_at - probe_started_at
            if elapsed >= self._policy.maximum_probe_duration:
                return self._result(evaluated_at, WaterTemperatureDisposition.ACQUISITION_FAILED, "probe_maximum_exceeded")
            if elapsed < self._policy.minimum_probe_duration:
                return self._result(evaluated_at, WaterTemperatureDisposition.PROBING, "probe_minimum_duration", self._policy.baselines.temperature_probe_rpm)
            stable = _stable_window(samples, evaluated_at=evaluated_at, policy=self._policy)
            if stable is not None:
                self._trusted_temperature_f = stable
                self._trusted_at = evaluated_at
                return self._result(evaluated_at, WaterTemperatureDisposition.TRUSTED, "probe_settled")
            return self._result(evaluated_at, WaterTemperatureDisposition.PROBING, "probe_not_settled", self._policy.baselines.temperature_probe_rpm)

        if self._trusted_at is not None and evaluated_at - self._trusted_at <= self._policy.trusted_after_circulation:
            return self._result(evaluated_at, WaterTemperatureDisposition.REUSED, "trusted_temperature_within_reuse_window")

        actionable = (
            thermal_decision_requested
            and collector_temperature_f is not None
            and collector_temperature_f >= self._policy.collector_actionable_f
        )
        if actionable:
            return self._result(evaluated_at, WaterTemperatureDisposition.PROBE_REQUIRED, "thermal_decision_requires_trusted_water", self._policy.baselines.temperature_probe_rpm)
        return self._result(evaluated_at, WaterTemperatureDisposition.NOT_REQUIRED, "no_actionable_thermal_decision")


def _stable_window(
    samples: tuple[TemperatureSample, ...],
    *,
    evaluated_at: datetime,
    policy: WaterTemperaturePolicy,
) -> float | None:
    ordered = tuple(sorted(samples, key=lambda item: item.observed_at))
    cutoff = evaluated_at - policy.stability_window
    window = tuple(item for item in ordered if cutoff <= item.observed_at <= evaluated_at)
    if len(window) < 2 or window[-1].observed_at - window[0].observed_at < policy.stability_window:
        return None
    directions: list[int] = []
    for first, second in zip(window, window[1:]):
        elapsed_minutes = (second.observed_at - first.observed_at).total_seconds() / 60
        if elapsed_minutes <= 0:
            return None
        delta = second.temperature_f - first.temperature_f
        if abs(delta) / elapsed_minutes > policy.maximum_smooth_rate_f_per_minute:
            return None
        if delta != 0:
            directions.append(1 if delta > 0 else -1)
    if any(first != second for first, second in zip(directions, directions[1:])):
        return None
    return window[-1].temperature_f
