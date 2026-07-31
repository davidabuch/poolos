"""Deterministic decision-equivalence and churn-control policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Optional

from .decision_intelligence import DecisionExplanation


class StabilityDisposition(str, Enum):
    """How a proposed decision relates to the currently active decision."""

    INITIAL = "initial"
    RETAIN_EQUIVALENT = "retain_equivalent"
    RETAIN_MINIMUM_LIFETIME = "retain_minimum_lifetime"
    RETAIN_CONFIDENCE_HYSTERESIS = "retain_confidence_hysteresis"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class DecisionStabilityPolicy:
    """Policy thresholds used to prevent unnecessary decision churn."""

    minimum_lifetime: timedelta = timedelta(0)
    confidence_hysteresis: float = 0.0

    def __post_init__(self) -> None:
        if self.minimum_lifetime < timedelta(0):
            raise ValueError("minimum_lifetime must not be negative")
        if not 0 <= self.confidence_hysteresis <= 1:
            raise ValueError("confidence_hysteresis must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DecisionStabilityResult:
    """Deterministic comparison between an active and proposed decision."""

    disposition: StabilityDisposition
    decision_changed: bool
    active_decision_id: str
    proposed_decision_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionStabilityEngine:
    """Determine whether a proposed decision should replace the active one."""

    policy: DecisionStabilityPolicy = DecisionStabilityPolicy()

    @staticmethod
    def equivalent(
        active: DecisionExplanation,
        proposed: DecisionExplanation,
    ) -> bool:
        """Return whether two decisions are operationally equivalent."""

        active_blockers = tuple(
            sorted(check.check_id for check in active.blocking_checks)
        )
        proposed_blockers = tuple(
            sorted(check.check_id for check in proposed.blocking_checks)
        )
        return (
            active.goal == proposed.goal
            and active.outcome is proposed.outcome
            and active.selected_alternative_id == proposed.selected_alternative_id
            and active_blockers == proposed_blockers
        )

    def evaluate(
        self,
        proposed: DecisionExplanation,
        active: Optional[DecisionExplanation] = None,
    ) -> DecisionStabilityResult:
        """Classify and accept or retain one proposed decision."""

        if active is None:
            return DecisionStabilityResult(
                disposition=StabilityDisposition.INITIAL,
                decision_changed=True,
                active_decision_id=proposed.decision_id,
                proposed_decision_id=proposed.decision_id,
                reason="No active decision exists",
            )
        if self.equivalent(active, proposed):
            return DecisionStabilityResult(
                disposition=StabilityDisposition.RETAIN_EQUIVALENT,
                decision_changed=False,
                active_decision_id=active.decision_id,
                proposed_decision_id=proposed.decision_id,
                reason="Proposed decision is operationally equivalent",
            )
        age = proposed.evaluated_at - active.evaluated_at
        if age < self.policy.minimum_lifetime:
            return DecisionStabilityResult(
                disposition=StabilityDisposition.RETAIN_MINIMUM_LIFETIME,
                decision_changed=False,
                active_decision_id=active.decision_id,
                proposed_decision_id=proposed.decision_id,
                reason="Active decision is within its minimum lifetime",
            )
        confidence_gain = proposed.confidence - active.confidence
        if confidence_gain < self.policy.confidence_hysteresis:
            return DecisionStabilityResult(
                disposition=StabilityDisposition.RETAIN_CONFIDENCE_HYSTERESIS,
                decision_changed=False,
                active_decision_id=active.decision_id,
                proposed_decision_id=proposed.decision_id,
                reason="Confidence change does not exceed hysteresis",
            )
        return DecisionStabilityResult(
            disposition=StabilityDisposition.SUPERSEDE,
            decision_changed=True,
            active_decision_id=proposed.decision_id,
            proposed_decision_id=proposed.decision_id,
            reason="Proposed decision is materially different",
        )
