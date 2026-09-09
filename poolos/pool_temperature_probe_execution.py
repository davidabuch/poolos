"""Typed in-memory execution evidence for Pool temperature acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PoolTemperatureProbeExecutionPhase(StrEnum):
    """Physical provenance state exposed to the command-free evaluator."""

    PREPARING = "preparing"
    ACQUIRING = "acquiring"


@dataclass(frozen=True, slots=True)
class PoolTemperatureProbeExecutionEvidence:
    """Positive, session-derived proof for one non-persistent probe epoch."""

    phase: PoolTemperatureProbeExecutionPhase
    execution_purpose_id: str
    execution_plan_id: str
    ownership_lease_id: str
    ownership_generation: int
    body_activation_owned: bool
    pump_setpoint_owned: bool
    acquisition_started_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("execution_purpose_id", "execution_plan_id", "ownership_lease_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.ownership_generation < 1:
            raise ValueError("probe ownership generation must be positive")
        phase = PoolTemperatureProbeExecutionPhase(self.phase)
        object.__setattr__(self, "phase", phase)
        if phase is PoolTemperatureProbeExecutionPhase.ACQUIRING:
            if (
                self.acquisition_started_at is None
                or not self.body_activation_owned
                or not self.pump_setpoint_owned
            ):
                raise ValueError(
                    "active acquisition requires start time, Pool body provenance, "
                    "and acquisition pump provenance"
                )
        elif self.acquisition_started_at is not None:
            raise ValueError("preparing probe cannot have an acquisition start")
        if self.acquisition_started_at is not None and (
            self.acquisition_started_at.tzinfo is None
            or self.acquisition_started_at.utcoffset() is None
        ):
            raise ValueError("acquisition_started_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PoolTemperatureProbeContinuityEvidence:
    """Current-frame proof that an owned acquisition may consume samples."""

    evaluated_at: datetime
    valid: bool
    blocker: str | None = None
    temperature_sample_usable: bool = True

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("probe continuity timestamp must be timezone-aware")
        if self.valid == bool(self.blocker):
            raise ValueError("probe continuity validity must match blocker")


__all__ = [
    "PoolTemperatureProbeContinuityEvidence",
    "PoolTemperatureProbeExecutionEvidence",
    "PoolTemperatureProbeExecutionPhase",
]
