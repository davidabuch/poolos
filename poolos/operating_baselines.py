"""Installation pump baselines used by command-free operating policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .operational_intent import IntentCriterion


@dataclass(frozen=True, slots=True)
class PumpOperatingBaselines:
    """Known-good installation values; these are not claimed to be optimal."""

    temperature_probe_rpm: int = 1500
    grid_outage_rpm: int = 1500
    filtration_rpm: int = 2600
    priming_rpm: int = 3000
    solar_heating_rpm: int = 2900
    spillway_rpm: int = 2900
    gas_heating_rpm: int = 3000

    def __post_init__(self) -> None:
        for name in (
            "temperature_probe_rpm",
            "grid_outage_rpm",
            "filtration_rpm",
            "priming_rpm",
            "solar_heating_rpm",
            "spillway_rpm",
            "gas_heating_rpm",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


class PumpTransitionOrigin(str, Enum):
    AUTONOMOUS = "autonomous"
    USER = "user"
    SAFETY = "safety"


@dataclass(frozen=True, slots=True)
class PumpAntiChatterPolicy:
    minimum_on: timedelta = timedelta(minutes=1)
    minimum_off: timedelta = timedelta(minutes=1)

    def permits(
        self,
        *,
        evaluated_at: datetime,
        currently_on: bool,
        requested_on: bool,
        last_transition_at: datetime | None,
        origin: PumpTransitionOrigin,
    ) -> bool:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if origin in {PumpTransitionOrigin.USER, PumpTransitionOrigin.SAFETY}:
            return True
        if requested_on == currently_on or last_transition_at is None:
            return True
        if last_transition_at.tzinfo is None or last_transition_at.utcoffset() is None:
            raise ValueError("last_transition_at must be timezone-aware")
        elapsed = evaluated_at - last_transition_at
        required = self.minimum_on if currently_on else self.minimum_off
        return elapsed >= required


def pump_baseline_criterion(*, rpm: int, operating_mode: str) -> IntentCriterion:
    """Express one baseline through the existing optimizer constraint contract."""

    return IntentCriterion(
        code="minimum_pump_rpm",
        description="Known-good installation pump baseline for this operating mode",
        parameters={"rpm": rpm, "operating_mode": operating_mode},
    )


def command_disabled_criterion() -> IntentCriterion:
    """Preserve explicit recommendation-only authority on generated intents."""

    return IntentCriterion(
        code="command_authority_disabled",
        description="Policy evidence grants no command or equipment authority",
        parameters={"enabled": True},
    )
