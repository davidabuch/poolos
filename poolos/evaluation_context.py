"""Immutable factual snapshot for one PoolOS decision evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .planning import PlanObjective


class EvaluationTrigger(str, Enum):
    """Reason a supervisory decision evaluation started."""

    MANUAL = "manual"
    OBSERVATION_CHANGED = "observation_changed"
    FORECAST_CHANGED = "forecast_changed"
    POLICY_CHANGED = "policy_changed"
    GOAL_CHANGED = "goal_changed"
    DECISION_EXPIRED = "decision_expired"
    EXPECTED_CHANGE_REACHED = "expected_change_reached"
    RESTART_RECOVERY = "restart_recovery"
    SCHEDULED = "scheduled"
    EXTERNAL_EVENT = "external_event"


class EvaluationRuntimeMode(str, Enum):
    """Safety mode in which the evaluation is performed."""

    SIMULATION = "simulation"
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class DecisionEvaluationContext:
    """One immutable, replay-oriented snapshot supplied to orchestration."""

    context_id: str
    evaluated_at: datetime
    trigger: EvaluationTrigger
    runtime_mode: EvaluationRuntimeMode
    goals: tuple[PlanObjective, ...]
    observation: Mapping[str, Any] = field(default_factory=dict)
    forecast: Mapping[str, Any] = field(default_factory=dict)
    active_policy_ids: tuple[str, ...] = ()
    freshness: Mapping[str, str] = field(default_factory=dict)
    previous_decision_id: Optional[str] = None
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        goal_ids = tuple(goal.objective_id for goal in self.goals)
        if len(goal_ids) != len(set(goal_ids)):
            raise ValueError("goal objective IDs must be unique")
        if any(not value.strip() for value in self.active_policy_ids):
            raise ValueError("active policy IDs must not be empty")
        if len(self.active_policy_ids) != len(set(self.active_policy_ids)):
            raise ValueError("active policy IDs must be unique")
        if any(not value.strip() for value in self.blockers):
            raise ValueError("context blockers must not be empty")
        if self.previous_decision_id is not None and not self.previous_decision_id.strip():
            raise ValueError("previous_decision_id must not be empty when supplied")
        object.__setattr__(self, "observation", MappingProxyType(dict(self.observation)))
        object.__setattr__(self, "forecast", MappingProxyType(dict(self.forecast)))
        object.__setattr__(self, "freshness", MappingProxyType(dict(self.freshness)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def planning_allowed(self) -> bool:
        """Return whether this context permits planning."""

        return not self.blockers

    def goal(self, objective_id: str) -> PlanObjective:
        """Return a goal by stable objective ID."""

        for goal in self.goals:
            if goal.objective_id == objective_id:
                return goal
        raise KeyError(f"unknown objective_id: {objective_id}")
