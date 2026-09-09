"""Explicit command-free Spa bulk-water temperature trust boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math


class SpaTemperatureDisposition(StrEnum):
    TRUSTED = "trusted"
    INACTIVE_BODY_UNTRUSTED = "inactive_body_untrusted"
    EVIDENCE_UNUSABLE = "evidence_unusable"


@dataclass(frozen=True, slots=True)
class SpaTemperatureEvidence:
    """Positive trusted evidence supplied by a future commissioned acquisition."""

    evaluated_at: datetime
    disposition: SpaTemperatureDisposition
    trusted_temperature_f: float | None = None
    trusted_at: datetime | None = None
    acquisition_generation: int | None = None

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Spa temperature evaluated_at must be timezone-aware")
        if self.trusted_at is not None and (
            self.trusted_at.tzinfo is None or self.trusted_at.utcoffset() is None
        ):
            raise ValueError("Spa temperature trusted_at must be timezone-aware")
        if self.disposition is SpaTemperatureDisposition.TRUSTED:
            if self.trusted_temperature_f is None or self.trusted_at is None:
                raise ValueError("trusted Spa temperature requires value and timestamp")
            if not math.isfinite(self.trusted_temperature_f):
                raise ValueError("trusted Spa temperature must be finite")
            if self.trusted_at > self.evaluated_at:
                raise ValueError("trusted Spa temperature cannot come from the future")
        elif self.trusted_temperature_f is not None or self.trusted_at is not None:
            raise ValueError("untrusted Spa temperature cannot carry trusted evidence")


def current_spa_temperature_evidence(
    *,
    evaluated_at: datetime,
    spa_active: bool | None,
    pool_active: bool | None,
    pump_rpm: int | None,
    observed_temperature_f: float | None,
    temperature_observed_at: datetime | None,
    observation_usable: bool,
) -> SpaTemperatureEvidence:
    """Trust current Spa water only during proven exclusive live circulation."""

    if not observation_usable:
        disposition = SpaTemperatureDisposition.EVIDENCE_UNUSABLE
    elif (
        spa_active is not True
        or pool_active is not False
        or pump_rpm is None
        or pump_rpm <= 0
    ):
        disposition = SpaTemperatureDisposition.INACTIVE_BODY_UNTRUSTED
    else:
        if (
            observed_temperature_f is None
            or temperature_observed_at is None
            or temperature_observed_at > evaluated_at
        ):
            return SpaTemperatureEvidence(
                evaluated_at=evaluated_at,
                disposition=SpaTemperatureDisposition.EVIDENCE_UNUSABLE,
            )
        return SpaTemperatureEvidence(
            evaluated_at=evaluated_at,
            disposition=SpaTemperatureDisposition.TRUSTED,
            trusted_temperature_f=observed_temperature_f,
            trusted_at=temperature_observed_at,
        )
    return SpaTemperatureEvidence(
        evaluated_at=evaluated_at,
        disposition=disposition,
    )


__all__ = [
    "SpaTemperatureDisposition",
    "SpaTemperatureEvidence",
    "current_spa_temperature_evidence",
]
