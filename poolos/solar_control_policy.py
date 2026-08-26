"""Deterministic command-free solar-heating eligibility policy for PoolOS.

This module evaluates whether observed pool conditions support a
MAXIMIZE_SOLAR operational intent.

It performs no command generation, Home Assistant I/O, execution planning,
or equipment actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math


class SolarEligibilityDisposition(str, Enum):
    """Current result of solar-heating eligibility evaluation."""

    BLOCKED = "blocked"
    QUALIFYING = "qualifying"
    ELIGIBLE = "eligible"


@dataclass(frozen=True, slots=True)
class SolarEligibilityPolicy:
    """Installation-specific solar eligibility thresholds."""

    activation_differential_f: float = 7.0
    deactivation_differential_f: float = 7.0
    activation_hold: timedelta = timedelta(minutes=10)

    def __post_init__(self) -> None:
        if not math.isfinite(self.activation_differential_f):
            raise ValueError("activation_differential_f must be finite")
        if not math.isfinite(self.deactivation_differential_f):
            raise ValueError("deactivation_differential_f must be finite")
        if self.activation_hold < timedelta(0):
            raise ValueError("activation_hold must not be negative")


@dataclass(frozen=True, slots=True)
class SolarEligibilityInput:
    """One normalized observation used for solar eligibility."""

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
    """Read-only result of one solar eligibility evaluation."""

    evaluated_at: datetime
    disposition: SolarEligibilityDisposition
    eligible: bool
    differential_f: float | None
    qualifying_since: datetime | None
    qualifying_seconds: float
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "disposition": self.disposition.value,
            "eligible": self.eligible,
            "differential_f": self.differential_f,
            "qualifying_since": (
                None
                if self.qualifying_since is None
                else self.qualifying_since.isoformat()
            ),
            "qualifying_seconds": self.qualifying_seconds,
            "rationale": list(self.rationale),
            "authority": "none",
            "command_delivery_enabled": False,
        }


class SolarEligibilityTracker:
    """Track deterministic 7 F / 10 minute solar eligibility.

    Starting solar requires the activation differential to remain satisfied
    continuously for the configured hold period.

    Once solar is already active, the activation hold is not re-applied.
    Solar remains thermally eligible while the deactivation differential is
    satisfied and the other eligibility conditions remain true.

    Pump RPM is deliberately not an input to this policy.
    """

    def __init__(
        self,
        policy: SolarEligibilityPolicy = SolarEligibilityPolicy(),
    ) -> None:
        self._policy = policy
        self._qualifying_since: datetime | None = None
        self._last_evaluated_at: datetime | None = None

    @property
    def policy(self) -> SolarEligibilityPolicy:
        return self._policy

    @property
    def qualifying_since(self) -> datetime | None:
        return self._qualifying_since

    def reset(self) -> None:
        """Clear temporal qualification state."""

        self._qualifying_since = None
        self._last_evaluated_at = None

    def _blocked(
        self,
        observation: SolarEligibilityInput,
        *,
        differential_f: float | None,
        reason: str,
    ) -> SolarEligibilityAssessment:
        self._qualifying_since = None
        return SolarEligibilityAssessment(
            evaluated_at=observation.evaluated_at,
            disposition=SolarEligibilityDisposition.BLOCKED,
            eligible=False,
            differential_f=differential_f,
            qualifying_since=None,
            qualifying_seconds=0.0,
            rationale=(reason,),
        )

    def evaluate(
        self,
        observation: SolarEligibilityInput,
    ) -> SolarEligibilityAssessment:
        """Evaluate one observation without creating or delivering commands."""

        if (
            self._last_evaluated_at is not None
            and observation.evaluated_at < self._last_evaluated_at
        ):
            raise ValueError("solar eligibility observations must be chronological")

        self._last_evaluated_at = observation.evaluated_at

        water = observation.water_temperature_f
        collector = observation.collector_temperature_f
        target = observation.target_temperature_f

        if water is None or collector is None or target is None:
            return self._blocked(
                observation,
                differential_f=None,
                reason="Required solar eligibility temperature telemetry is unavailable.",
            )

        differential = collector - water

        if not observation.pool_active:
            return self._blocked(
                observation,
                differential_f=differential,
                reason="Pool circulation is not active.",
            )

        if observation.spa_active:
            return self._blocked(
                observation,
                differential_f=differential,
                reason="Spa operation suppresses pool solar-heating eligibility.",
            )

        if water >= target:
            return self._blocked(
                observation,
                differential_f=differential,
                reason=(
                    f"Pool temperature {water:.1f} F has reached "
                    f"the {target:.1f} F target."
                ),
            )

        if observation.solar_active:
            self._qualifying_since = None

            if differential < self._policy.deactivation_differential_f:
                return SolarEligibilityAssessment(
                    evaluated_at=observation.evaluated_at,
                    disposition=SolarEligibilityDisposition.BLOCKED,
                    eligible=False,
                    differential_f=differential,
                    qualifying_since=None,
                    qualifying_seconds=0.0,
                    rationale=(
                        f"Solar is active but collector differential "
                        f"{differential:.1f} F is below the "
                        f"{self._policy.deactivation_differential_f:.1f} F "
                        "thermal hold threshold.",
                    ),
                )

            return SolarEligibilityAssessment(
                evaluated_at=observation.evaluated_at,
                disposition=SolarEligibilityDisposition.ELIGIBLE,
                eligible=True,
                differential_f=differential,
                qualifying_since=None,
                qualifying_seconds=0.0,
                rationale=(
                    "Solar is already active and all thermal eligibility "
                    "conditions remain satisfied.",
                ),
            )

        if differential < self._policy.activation_differential_f:
            return self._blocked(
                observation,
                differential_f=differential,
                reason=(
                    f"Collector differential {differential:.1f} F is below "
                    f"the {self._policy.activation_differential_f:.1f} F "
                    "solar activation threshold."
                ),
            )

        if self._qualifying_since is None:
            self._qualifying_since = observation.evaluated_at

        qualifying_seconds = max(
            0.0,
            (observation.evaluated_at - self._qualifying_since).total_seconds(),
        )
        required_seconds = self._policy.activation_hold.total_seconds()

        if qualifying_seconds < required_seconds:
            return SolarEligibilityAssessment(
                evaluated_at=observation.evaluated_at,
                disposition=SolarEligibilityDisposition.QUALIFYING,
                eligible=False,
                differential_f=differential,
                qualifying_since=self._qualifying_since,
                qualifying_seconds=qualifying_seconds,
                rationale=(
                    f"Collector differential is at least "
                    f"{self._policy.activation_differential_f:.1f} F; "
                    f"qualification has persisted for "
                    f"{qualifying_seconds:.0f} of {required_seconds:.0f} seconds.",
                ),
            )

        return SolarEligibilityAssessment(
            evaluated_at=observation.evaluated_at,
            disposition=SolarEligibilityDisposition.ELIGIBLE,
            eligible=True,
            differential_f=differential,
            qualifying_since=self._qualifying_since,
            qualifying_seconds=qualifying_seconds,
            rationale=(
                f"Collector differential has remained at least "
                f"{self._policy.activation_differential_f:.1f} F for the "
                "required solar activation hold period.",
            ),
        )
