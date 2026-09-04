"""Deterministic command-free cold-start pump priming policy.

This module decides whether a requested circulation start requires the
installation's priming phase. It performs no timing, scheduling, delivery,
Home Assistant calls, IntelliCenter calls, or equipment mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from .operating_baselines import PumpOperatingBaselines


class PumpPrimingDisposition(StrEnum):
    """Outcome of one cold-start priming evaluation."""

    REQUIRED = "required"
    NOT_REQUIRED_ALREADY_CIRCULATING = "not_required_already_circulating"
    NOT_REQUIRED_NO_START = "not_required_no_start"


@dataclass(frozen=True, slots=True)
class PumpPrimingDecision:
    """Immutable evidence describing whether priming is required."""

    disposition: PumpPrimingDisposition
    priming_required: bool
    priming_rpm: int | None
    minimum_duration: timedelta | None
    reason: str

    def __post_init__(self) -> None:
        if self.priming_required:
            if self.priming_rpm is None or self.priming_rpm <= 0:
                raise ValueError("required priming must define a positive RPM")
            if self.minimum_duration is None or self.minimum_duration <= timedelta(0):
                raise ValueError("required priming must define a positive duration")
        elif self.priming_rpm is not None or self.minimum_duration is not None:
            raise ValueError("non-required priming cannot define RPM or duration")

        if not self.reason.strip():
            raise ValueError("reason must not be empty")


@dataclass(frozen=True, slots=True)
class PumpPrimingPolicy:
    """Require priming only when circulation is starting from rest."""

    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    minimum_duration: timedelta = timedelta(seconds=60)

    def __post_init__(self) -> None:
        if self.minimum_duration <= timedelta(0):
            raise ValueError("minimum_duration must be positive")

    def evaluate(
        self,
        *,
        circulation_requested: bool,
        currently_circulating: bool,
    ) -> PumpPrimingDecision:
        """Return command-free priming evidence for one circulation request."""

        if not circulation_requested:
            return PumpPrimingDecision(
                disposition=PumpPrimingDisposition.NOT_REQUIRED_NO_START,
                priming_required=False,
                priming_rpm=None,
                minimum_duration=None,
                reason="No circulation start is requested.",
            )

        if currently_circulating:
            return PumpPrimingDecision(
                disposition=(
                    PumpPrimingDisposition.NOT_REQUIRED_ALREADY_CIRCULATING
                ),
                priming_required=False,
                priming_rpm=None,
                minimum_duration=None,
                reason="Circulation is already established; do not re-prime.",
            )

        return PumpPrimingDecision(
            disposition=PumpPrimingDisposition.REQUIRED,
            priming_required=True,
            priming_rpm=self.baselines.priming_rpm,
            minimum_duration=self.minimum_duration,
            reason="Cold circulation start requires pump priming.",
        )


__all__ = [
    "PumpPrimingDecision",
    "PumpPrimingDisposition",
    "PumpPrimingPolicy",
]
