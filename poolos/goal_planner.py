"""Goal-oriented planning facade for future PoolOS states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from .enums import CommandPriority
from .kernel import PoolKernel
from .planning import ObjectiveType, Plan, PlanObjective, Planner


class GoalType(str, Enum):
    """Future-state goals supported by the first goal-planning facade."""

    BODY_READY_BY = "body_ready_by"


class FeasibilityStatus(str, Enum):
    """Planner assessment of whether a goal can meet its deadline."""

    ACHIEVED = "achieved"
    FEASIBLE = "feasible"
    AT_RISK = "at_risk"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True, slots=True)
class BodyReadyGoal:
    """Request that a pool body reach a temperature by a future deadline."""

    body_id: str
    target_temperature: float
    deadline: datetime
    maintain_until: Optional[datetime] = None
    earliest_start: Optional[datetime] = None
    priority: CommandPriority = CommandPriority.NORMAL
    requested_by: str = "poolos"
    correlation_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    goal_id: str = field(default_factory=lambda: str(uuid4()))
    goal_type: GoalType = GoalType.BODY_READY_BY

    def __post_init__(self) -> None:
        if not self.goal_id.strip() or not self.body_id.strip():
            raise ValueError("goal_id and body_id must not be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by must not be empty")
        if self.deadline.tzinfo is None:
            raise ValueError("goal deadline must be timezone-aware")
        if self.earliest_start is not None and self.earliest_start.tzinfo is None:
            raise ValueError("goal earliest_start must be timezone-aware")
        if self.maintain_until is not None:
            if self.maintain_until.tzinfo is None:
                raise ValueError("goal maintain_until must be timezone-aware")
            if self.maintain_until < self.deadline:
                raise ValueError("maintain_until must not precede deadline")
        if not 40.0 <= self.target_temperature <= 110.0:
            raise ValueError("target_temperature must be between 40 and 110")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class GoalAssessment:
    """Deterministic feasibility calculation for one goal."""

    status: FeasibilityStatus
    current_temperature: float
    target_temperature: float
    temperature_delta: float
    required_duration: timedelta
    available_duration: timedelta
    recommended_start: datetime
    estimated_completion: datetime
    reasons: tuple[str, ...]

    @property
    def can_meet_deadline(self) -> bool:
        return self.status in (FeasibilityStatus.ACHIEVED, FeasibilityStatus.FEASIBLE)


@dataclass(frozen=True, slots=True)
class GoalPlanResult:
    """Traceable result linking a user goal, assessment, objective, and plan."""

    goal: BodyReadyGoal
    assessment: GoalAssessment
    objective: PlanObjective
    plan: Plan


@dataclass(frozen=True, slots=True)
class GoalPlanner:
    """Normalize future-state goals into the existing immutable Planner."""

    planner: Planner
    heating_rate_degrees_per_hour: float = 8.0
    risk_buffer: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.heating_rate_degrees_per_hour <= 0:
            raise ValueError("heating_rate_degrees_per_hour must be positive")
        if self.risk_buffer < timedelta(0):
            raise ValueError("risk_buffer must not be negative")

    def assess(self, goal: BodyReadyGoal, kernel: PoolKernel) -> GoalAssessment:
        now = kernel.clock.now()
        if now.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")
        if goal.deadline <= now:
            raise ValueError("goal deadline must be in the future")

        kernel.bodies.get(goal.body_id)
        body_state = kernel.state.get_body(goal.body_id)
        if body_state is None:
            raise ValueError(f"no runtime state available for body: {goal.body_id}")

        current = body_state.temperature.current
        delta = max(0.0, goal.target_temperature - current)
        required = timedelta(hours=delta / self.heating_rate_degrees_per_hour)
        earliest = max(now, goal.earliest_start or now)
        available = max(timedelta(0), goal.deadline - earliest)
        recommended_start = max(earliest, goal.deadline - required)
        estimated_completion = earliest + required

        if delta == 0:
            status = FeasibilityStatus.ACHIEVED
            reasons = ("Current temperature already satisfies the requested goal.",)
        elif required > available:
            status = FeasibilityStatus.INFEASIBLE
            reasons = (
                "Estimated heating duration exceeds the available planning window.",
            )
        elif required + self.risk_buffer > available:
            status = FeasibilityStatus.AT_RISK
            reasons = (
                "The goal is mathematically reachable but lacks the configured risk buffer.",
            )
        else:
            status = FeasibilityStatus.FEASIBLE
            reasons = ("Estimated heating duration fits within the planning window.",)

        return GoalAssessment(
            status=status,
            current_temperature=current,
            target_temperature=goal.target_temperature,
            temperature_delta=delta,
            required_duration=required,
            available_duration=available,
            recommended_start=recommended_start,
            estimated_completion=estimated_completion,
            reasons=reasons,
        )

    def create_plan(self, goal: BodyReadyGoal, kernel: PoolKernel) -> GoalPlanResult:
        assessment = self.assess(goal, kernel)
        now = kernel.clock.now()
        earliest = max(now, goal.earliest_start or now)
        objective = PlanObjective(
            objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
            body_id=goal.body_id,
            target_temperature=goal.target_temperature,
            earliest_start=earliest,
            deadline=goal.deadline,
            maintain_until=goal.maintain_until,
            priority=goal.priority,
            requested_by=goal.requested_by,
            correlation_id=goal.correlation_id,
            metadata={
                **dict(goal.metadata),
                "goal_id": goal.goal_id,
                "goal_type": goal.goal_type.value,
                "feasibility": assessment.status.value,
            },
            objective_id=goal.goal_id,
        )
        plan = self.planner.create_plan(objective, kernel)
        return GoalPlanResult(goal, assessment, objective, plan)
