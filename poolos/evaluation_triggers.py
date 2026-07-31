"""Typed and deterministic coalescing of PoolOS evaluation triggers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from .evaluation_context import EvaluationTrigger


class TriggerUrgency(IntEnum):
    """Relative urgency used when several evaluation requests are pending."""

    ROUTINE = 10
    NORMAL = 20
    HIGH = 30
    IMMEDIATE = 40


_TRIGGER_PRECEDENCE = {
    EvaluationTrigger.RESTART_RECOVERY: 90,
    EvaluationTrigger.MANUAL: 80,
    EvaluationTrigger.EXTERNAL_EVENT: 70,
    EvaluationTrigger.POLICY_CHANGED: 60,
    EvaluationTrigger.GOAL_CHANGED: 50,
    EvaluationTrigger.OBSERVATION_CHANGED: 40,
    EvaluationTrigger.FORECAST_CHANGED: 30,
    EvaluationTrigger.DECISION_EXPIRED: 20,
    EvaluationTrigger.EXPECTED_CHANGE_REACHED: 10,
    EvaluationTrigger.SCHEDULED: 0,
}


@dataclass(frozen=True, slots=True)
class EvaluationTriggerRequest:
    """One request to run the supervisory decision orchestrator."""

    trigger: EvaluationTrigger
    requested_at: datetime
    urgency: TriggerUrgency = TriggerUrgency.NORMAL
    source: str = "poolos"
    reason: str = "evaluation requested"

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("trigger source must not be empty")
        if not self.reason.strip():
            raise ValueError("trigger reason must not be empty")


@dataclass(frozen=True, slots=True)
class CoalescedEvaluationTrigger:
    """Deterministic result of combining pending evaluation requests."""

    primary: EvaluationTriggerRequest
    requests: tuple[EvaluationTriggerRequest, ...]

    @property
    def trigger(self) -> EvaluationTrigger:
        return self.primary.trigger

    @property
    def urgency(self) -> TriggerUrgency:
        return self.primary.urgency

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(request.reason for request in self.requests)


@dataclass(frozen=True, slots=True)
class EvaluationTriggerCoalescer:
    """Combine pending requests into one deterministic evaluation trigger."""

    def coalesce(
        self,
        requests: tuple[EvaluationTriggerRequest, ...],
    ) -> CoalescedEvaluationTrigger:
        if not requests:
            raise ValueError("at least one trigger request is required")
        ordered = tuple(
            sorted(
                requests,
                key=lambda request: (
                    -int(request.urgency),
                    -_TRIGGER_PRECEDENCE[request.trigger],
                    request.requested_at,
                    request.source,
                    request.reason,
                ),
            )
        )
        return CoalescedEvaluationTrigger(primary=ordered[0], requests=ordered)
