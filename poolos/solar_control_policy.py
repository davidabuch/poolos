"""Deterministic command-free physical pool-solar eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math


class SolarEligibilityDisposition(str, Enum):
    BLOCKED = "blocked"
    ELIGIBLE = "eligible"


@dataclass(frozen=True, slots=True)
class SolarEligibilityPolicy:
    """Initial physical thresholds; values remain configurable policy."""

    activation_differential_f: float = 7.0
    deactivation_differential_f: float = 7.0
    minimum_collector_temperature_f: float = 90.0
    deactivation_hold: timedelta = timedelta(minutes=10)
    target_satisfaction_hold: timedelta = timedelta(minutes=10)

    def __post_init__(self) -> None:
        for name in (
            "activation_differential_f",
            "deactivation_differential_f",
            "minimum_collector_temperature_f",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        for name in (
            "deactivation_hold",
            "target_satisfaction_hold",
        ):
            if getattr(self, name) < timedelta(0):
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class SolarEligibilityInput:
    evaluated_at: datetime
    pool_active: bool
    spa_active: bool
    solar_active: bool
    water_temperature_f: float | None
    collector_temperature_f: float | None
    target_temperature_f: float | None

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        for name in (
            "water_temperature_f",
            "collector_temperature_f",
            "target_temperature_f",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")


@dataclass(frozen=True, slots=True)
class SolarEligibilityAssessment:
    evaluated_at: datetime
    disposition: SolarEligibilityDisposition
    eligible: bool
    differential_f: float | None
    rationale: tuple[str, ...]
    reason_code: str = ""
    differential_below_since: datetime | None = None
    target_satisfied_since: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "disposition": self.disposition.value,
            "eligible": self.eligible,
            "differential_f": self.differential_f,
            "differential_below_since": _iso(self.differential_below_since),
            "target_satisfied_since": _iso(self.target_satisfied_since),
            "reason_code": self.reason_code,
            "rationale": list(self.rationale),
            "authority": "none",
            "command_delivery_enabled": False,
        }


class SolarEligibilityTracker:
    """Apply immediate activation and independent ten-minute shutdown debounce."""

    def __init__(self, policy: SolarEligibilityPolicy = SolarEligibilityPolicy()) -> None:
        self._policy = policy
        self._differential_below_since: datetime | None = None
        self._target_satisfied_since: datetime | None = None
        self._last_evaluated_at: datetime | None = None

    @property
    def policy(self) -> SolarEligibilityPolicy:
        return self._policy

    def reset(self) -> None:
        self._differential_below_since = None
        self._target_satisfied_since = None
        self._last_evaluated_at = None

    def _result(
        self,
        observation: SolarEligibilityInput,
        *,
        disposition: SolarEligibilityDisposition,
        differential: float | None,
        reason_code: str,
        rationale: str,
    ) -> SolarEligibilityAssessment:
        return SolarEligibilityAssessment(
            evaluated_at=observation.evaluated_at,
            disposition=disposition,
            eligible=disposition is SolarEligibilityDisposition.ELIGIBLE,
            differential_f=differential,
            rationale=(rationale,),
            reason_code=reason_code,
            differential_below_since=self._differential_below_since,
            target_satisfied_since=self._target_satisfied_since,
        )

    def _block(
        self,
        observation: SolarEligibilityInput,
        *,
        differential: float | None,
        reason_code: str,
        rationale: str,
    ) -> SolarEligibilityAssessment:
        self._differential_below_since = None
        self._target_satisfied_since = None
        return self._result(
            observation,
            disposition=SolarEligibilityDisposition.BLOCKED,
            differential=differential,
            reason_code=reason_code,
            rationale=rationale,
        )

    def evaluate(self, observation: SolarEligibilityInput) -> SolarEligibilityAssessment:
        if self._last_evaluated_at is not None and observation.evaluated_at < self._last_evaluated_at:
            raise ValueError("solar eligibility observations must be chronological")
        self._last_evaluated_at = observation.evaluated_at

        water = observation.water_temperature_f
        collector = observation.collector_temperature_f
        target = observation.target_temperature_f
        if water is None or collector is None or target is None:
            return self._block(observation, differential=None, reason_code="required_temperature_unavailable", rationale="Required trusted solar temperature evidence is unavailable.")
        differential = collector - water
        if not observation.pool_active:
            return self._block(observation, differential=differential, reason_code="pool_circulation_inactive", rationale="Pool circulation is not active.")
        if observation.spa_active:
            return self._block(observation, differential=differential, reason_code="spa_priority", rationale="Active spa operation suppresses pool solar.")
        if collector < self._policy.minimum_collector_temperature_f:
            return self._block(observation, differential=differential, reason_code="collector_below_minimum", rationale="Collector temperature is below the configured minimum.")

        if not observation.solar_active:
            self._differential_below_since = None
            self._target_satisfied_since = None
            if water >= target:
                return self._block(observation, differential=differential, reason_code="target_satisfied", rationale="Pool target is already satisfied.")
            if differential < self._policy.activation_differential_f:
                return self._block(observation, differential=differential, reason_code="activation_differential_insufficient", rationale="Collector differential is below the activation threshold.")
            return self._result(observation, disposition=SolarEligibilityDisposition.ELIGIBLE, differential=differential, reason_code="physically_eligible", rationale="Physical solar eligibility is satisfied immediately.")

        if differential < self._policy.deactivation_differential_f:
            if self._differential_below_since is None:
                self._differential_below_since = observation.evaluated_at
        else:
            self._differential_below_since = None
        if water >= target:
            if self._target_satisfied_since is None:
                self._target_satisfied_since = observation.evaluated_at
        else:
            self._target_satisfied_since = None

        if self._differential_below_since is not None and observation.evaluated_at - self._differential_below_since >= self._policy.deactivation_hold:
            return self._block(observation, differential=differential, reason_code="differential_low_sustained", rationale="Collector differential stayed below threshold for the shutdown hold.")
        if self._target_satisfied_since is not None and observation.evaluated_at - self._target_satisfied_since >= self._policy.target_satisfaction_hold:
            return self._block(observation, differential=differential, reason_code="target_satisfied_sustained", rationale="Pool target stayed satisfied for the shutdown hold.")
        return self._result(observation, disposition=SolarEligibilityDisposition.ELIGIBLE, differential=differential, reason_code="active_shutdown_debounce", rationale="Active solar remains eligible while shutdown conditions debounce.")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
