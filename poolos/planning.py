"""Immutable planning models and the PoolOS planner service."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol
from uuid import uuid4

from .commands import Command
from .enums import CommandPriority
from .exceptions import (
    DuplicatePlanningStrategyError,
    PlanNotFoundError,
    PlanningStrategyNotFoundError,
)
from .kernel import PoolKernel


class ObjectiveType(str, Enum):
    """Objectives supported by the first PoolOS planner."""

    PREPARE_BODY_BY_DEADLINE = "prepare_body_by_deadline"


class PlanStatus(str, Enum):
    """Lifecycle state of a plan snapshot."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class FailureBehavior(str, Enum):
    """How orchestration should respond when a plan step fails."""

    STOP_PLAN = "stop_plan"
    CONTINUE = "continue"
    REQUEST_REPLAN = "request_replan"


class ConditionKind(str, Enum):
    """Serializable predicates evaluated against normalized PoolOS facts."""

    BODY_TEMPERATURE_AT_LEAST = "body_temperature_at_least"
    BODY_TEMPERATURE_BELOW = "body_temperature_below"
    BODY_CIRCULATION_RUNNING = "body_circulation_running"
    EQUIPMENT_AVAILABLE = "equipment_available"
    TIME_REACHED = "time_reached"


@dataclass(frozen=True, slots=True)
class PlanCondition:
    """A typed, serializable condition embedded in a plan step."""

    kind: ConditionKind
    subject_id: str
    expected: Any = True

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("condition subject_id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        expected = self.expected
        if isinstance(expected, datetime):
            expected = expected.isoformat()
        return {
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "expected": expected,
        }


@dataclass(frozen=True, slots=True)
class PlanObjective:
    """Normalized user or system intent supplied to the Planner."""

    objective_type: ObjectiveType
    body_id: str
    target_temperature: float
    earliest_start: datetime
    deadline: datetime
    maintain_until: Optional[datetime] = None
    priority: CommandPriority = CommandPriority.NORMAL
    requested_by: str = "poolos"
    correlation_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    objective_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.objective_id.strip():
            raise ValueError("objective_id must not be empty")
        if not self.body_id.strip():
            raise ValueError("body_id must not be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by must not be empty")
        if self.earliest_start.tzinfo is None or self.deadline.tzinfo is None:
            raise ValueError("objective times must be timezone-aware")
        if self.deadline <= self.earliest_start:
            raise ValueError("deadline must be after earliest_start")
        if self.maintain_until is not None:
            if self.maintain_until.tzinfo is None:
                raise ValueError("maintain_until must be timezone-aware")
            if self.maintain_until < self.deadline:
                raise ValueError("maintain_until must not precede deadline")
        if not 40.0 <= self.target_temperature <= 110.0:
            raise ValueError("target_temperature must be between 40 and 110")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "objective_type": self.objective_type.value,
            "body_id": self.body_id,
            "target_temperature": self.target_temperature,
            "earliest_start": self.earliest_start.isoformat(),
            "deadline": self.deadline.isoformat(),
            "maintain_until": (
                self.maintain_until.isoformat() if self.maintain_until else None
            ),
            "priority": int(self.priority),
            "requested_by": self.requested_by,
            "correlation_id": self.correlation_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One ordered, non-executing unit of intended work."""

    sequence: int
    earliest_eligible: datetime
    latest_eligible: datetime
    commands: tuple[Command, ...]
    dependencies: tuple[str, ...] = ()
    preconditions: tuple[PlanCondition, ...] = ()
    completion_conditions: tuple[PlanCondition, ...] = ()
    cancellation_conditions: tuple[PlanCondition, ...] = ()
    failure_behavior: FailureBehavior = FailureBehavior.REQUEST_REPLAN
    rationale: str = ""
    step_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be empty")
        if self.sequence < 1:
            raise ValueError("step sequence must be at least 1")
        if self.earliest_eligible.tzinfo is None or self.latest_eligible.tzinfo is None:
            raise ValueError("plan step times must be timezone-aware")
        if self.latest_eligible < self.earliest_eligible:
            raise ValueError("latest_eligible must not precede earliest_eligible")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("step dependencies must be unique")
        if self.step_id in self.dependencies:
            raise ValueError("a step cannot depend on itself")
        if not self.commands:
            raise ValueError("a plan step must propose at least one command")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence": self.sequence,
            "earliest_eligible": self.earliest_eligible.isoformat(),
            "latest_eligible": self.latest_eligible.isoformat(),
            "dependencies": list(self.dependencies),
            "commands": [
                {
                    "command_id": command.command_id,
                    "target": command.target,
                    "action": command.action.value,
                    "value": command.value,
                    "priority": int(command.priority),
                    "requested_by": command.requested_by,
                    "correlation_id": command.correlation_id,
                    "metadata": dict(command.metadata),
                    "issued_at": command.issued_at.isoformat(),
                }
                for command in self.commands
            ],
            "preconditions": [condition.to_dict() for condition in self.preconditions],
            "completion_conditions": [
                condition.to_dict() for condition in self.completion_conditions
            ],
            "cancellation_conditions": [
                condition.to_dict() for condition in self.cancellation_conditions
            ],
            "failure_behavior": self.failure_behavior.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """One immutable planner solution for an objective revision."""

    objective_id: str
    created_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    status: PlanStatus
    steps: tuple[PlanStep, ...]
    revision: int = 1
    supersedes_plan_id: Optional[str] = None
    estimated_completion: Optional[datetime] = None
    assumptions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()
    replan_reason: Optional[str] = None
    plan_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.plan_id.strip() or not self.objective_id.strip():
            raise ValueError("plan_id and objective_id must not be empty")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.horizon_start.tzinfo is None or self.horizon_end.tzinfo is None:
            raise ValueError("plan horizon times must be timezone-aware")
        if self.horizon_end < self.horizon_start:
            raise ValueError("horizon_end must not precede horizon_start")
        if self.revision < 1:
            raise ValueError("revision must be at least 1")
        sequences = [step.sequence for step in self.steps]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("plan step sequences must be unique and ordered")
        step_ids = {step.step_id for step in self.steps}
        for step in self.steps:
            missing = set(step.dependencies) - step_ids
            if missing:
                raise ValueError(f"unknown step dependencies: {sorted(missing)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "objective_id": self.objective_id,
            "created_at": self.created_at.isoformat(),
            "horizon_start": self.horizon_start.isoformat(),
            "horizon_end": self.horizon_end.isoformat(),
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "revision": self.revision,
            "supersedes_plan_id": self.supersedes_plan_id,
            "estimated_completion": (
                self.estimated_completion.isoformat()
                if self.estimated_completion
                else None
            ),
            "assumptions": list(self.assumptions),
            "constraints": list(self.constraints),
            "rationale": list(self.rationale),
            "replan_reason": self.replan_reason,
        }


class PlanningStrategy(Protocol):
    """Contract implemented by hardware-independent planning strategies."""

    @property
    def objective_type(self) -> ObjectiveType:
        ...

    def build(
        self,
        objective: PlanObjective,
        kernel: PoolKernel,
        *,
        revision: int,
        supersedes_plan_id: Optional[str] = None,
        replan_reason: Optional[str] = None,
    ) -> Plan:
        ...


@dataclass(slots=True)
class Planner:
    """Select strategies, create immutable plans, and retain revision history."""

    _strategies: dict[ObjectiveType, PlanningStrategy] = field(default_factory=dict)
    _plans: dict[str, Plan] = field(default_factory=dict)
    _objective_history: dict[str, list[str]] = field(default_factory=dict)

    def register_strategy(self, strategy: PlanningStrategy) -> None:
        if strategy.objective_type in self._strategies:
            raise DuplicatePlanningStrategyError(strategy.objective_type.value)
        self._strategies[strategy.objective_type] = strategy

    def create_plan(self, objective: PlanObjective, kernel: PoolKernel) -> Plan:
        strategy = self._strategy_for(objective.objective_type)
        plan = strategy.build(objective, kernel, revision=1)
        self._store(plan)
        return plan

    def replan(
        self,
        objective: PlanObjective,
        kernel: PoolKernel,
        *,
        previous_plan_id: str,
        reason: str,
    ) -> Plan:
        if not reason.strip():
            raise ValueError("replan reason must not be empty")
        previous = self.get_plan(previous_plan_id)
        if previous.objective_id != objective.objective_id:
            raise ValueError("previous plan belongs to a different objective")
        if previous.status in (PlanStatus.CANCELLED, PlanStatus.COMPLETED):
            raise ValueError(f"cannot replan a {previous.status.value} plan")

        self._plans[previous.plan_id] = replace(previous, status=PlanStatus.SUPERSEDED)
        strategy = self._strategy_for(objective.objective_type)
        replacement = strategy.build(
            objective,
            kernel,
            revision=previous.revision + 1,
            supersedes_plan_id=previous.plan_id,
            replan_reason=reason,
        )
        self._store(replacement)
        return replacement

    def get_plan(self, plan_id: str) -> Plan:
        try:
            return self._plans[plan_id]
        except KeyError as exc:
            raise PlanNotFoundError(plan_id) from exc

    def history_for(self, objective_id: str) -> tuple[Plan, ...]:
        return tuple(
            self._plans[plan_id]
            for plan_id in self._objective_history.get(objective_id, ())
        )

    def latest_for(self, objective_id: str) -> Optional[Plan]:
        history = self._objective_history.get(objective_id)
        return self._plans[history[-1]] if history else None

    def _strategy_for(self, objective_type: ObjectiveType) -> PlanningStrategy:
        try:
            return self._strategies[objective_type]
        except KeyError as exc:
            raise PlanningStrategyNotFoundError(objective_type.value) from exc

    def _store(self, plan: Plan) -> None:
        self._plans[plan.plan_id] = plan
        self._objective_history.setdefault(plan.objective_id, []).append(plan.plan_id)
