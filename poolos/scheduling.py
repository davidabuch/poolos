"""Time-aware orchestration for immutable PoolOS plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .exceptions import (
    DuplicateScheduledPlanError,
    ScheduledPlanNotFoundError,
    ScheduledStepNotFoundError,
)
from .kernel import PoolKernel
from .planning import ConditionKind, FailureBehavior, Plan, PlanCondition, PlanStatus, PlanStep


class ScheduledPlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NEEDS_REPLAN = "needs_replan"


class ScheduledStepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_STEPS = frozenset({
    ScheduledStepStatus.COMPLETED,
    ScheduledStepStatus.SKIPPED,
    ScheduledStepStatus.FAILED,
    ScheduledStepStatus.EXPIRED,
    ScheduledStepStatus.CANCELLED,
})


@dataclass(frozen=True, slots=True)
class StepRuntime:
    step_id: str
    status: ScheduledStepStatus = ScheduledStepStatus.PENDING
    updated_at: Optional[datetime] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ScheduledPlan:
    plan_id: str
    status: ScheduledPlanStatus
    activated_at: datetime
    updated_at: datetime
    steps: Mapping[str, StepRuntime]
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.activated_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("scheduled plan timestamps must be timezone-aware")
        object.__setattr__(self, "steps", MappingProxyType(dict(self.steps)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status.value,
            "activated_at": self.activated_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "detail": self.detail,
            "steps": {key: value.to_dict() for key, value in self.steps.items()},
        }


@dataclass(frozen=True, slots=True)
class SchedulerEvaluation:
    plan_id: str
    evaluated_at: datetime
    plan_status: ScheduledPlanStatus
    ready_steps: tuple[PlanStep, ...]
    changed_steps: tuple[StepRuntime, ...]

    @property
    def commands(self) -> tuple[Any, ...]:
        return tuple(command for step in self.ready_steps for command in step.commands)


@dataclass(slots=True)
class Scheduler:
    _plans: dict[str, Plan] = field(default_factory=dict)
    _runtime: dict[str, ScheduledPlan] = field(default_factory=dict)

    def activate(self, plan: Plan, kernel: PoolKernel) -> ScheduledPlan:
        if plan.plan_id in self._plans:
            raise DuplicateScheduledPlanError(plan.plan_id)
        now = self._now(kernel)
        status = ScheduledPlanStatus.COMPLETED if plan.status is PlanStatus.COMPLETED or not plan.steps else ScheduledPlanStatus.ACTIVE
        runtime = ScheduledPlan(
            plan.plan_id,
            status,
            now,
            now,
            {step.step_id: StepRuntime(step.step_id, updated_at=now) for step in plan.steps},
        )
        self._plans[plan.plan_id] = plan
        self._runtime[plan.plan_id] = runtime
        return runtime

    def restore(self, plan: Plan, snapshot: Mapping[str, Any]) -> ScheduledPlan:
        if plan.plan_id in self._plans:
            raise DuplicateScheduledPlanError(plan.plan_id)
        if snapshot.get("plan_id") != plan.plan_id:
            raise ValueError("snapshot belongs to a different plan")
        raw_steps = snapshot.get("steps", {})
        if set(raw_steps) != {step.step_id for step in plan.steps}:
            raise ValueError("snapshot step IDs do not match the plan")
        steps = {
            step_id: StepRuntime(
                step_id,
                ScheduledStepStatus(data["status"]),
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
                data.get("detail"),
            )
            for step_id, data in raw_steps.items()
        }
        runtime = ScheduledPlan(
            plan.plan_id,
            ScheduledPlanStatus(snapshot["status"]),
            datetime.fromisoformat(snapshot["activated_at"]),
            datetime.fromisoformat(snapshot["updated_at"]),
            steps,
            snapshot.get("detail"),
        )
        self._plans[plan.plan_id] = plan
        self._runtime[plan.plan_id] = runtime
        return runtime

    def tick(self, plan_id: str, kernel: PoolKernel) -> SchedulerEvaluation:
        plan = self._plan(plan_id)
        runtime = self.get(plan_id)
        now = self._now(kernel)
        if runtime.status is not ScheduledPlanStatus.ACTIVE:
            return SchedulerEvaluation(plan_id, now, runtime.status, (), ())

        steps = dict(runtime.steps)
        changed: list[StepRuntime] = []
        ready: list[PlanStep] = []
        plan_status = runtime.status
        detail = runtime.detail

        for step in plan.steps:
            current = steps[step.step_id]
            if current.status in TERMINAL_STEPS:
                continue
            if any(self._condition_true(item, kernel, now) for item in step.cancellation_conditions):
                updated = StepRuntime(step.step_id, ScheduledStepStatus.CANCELLED, now, "cancellation condition satisfied")
                steps[step.step_id] = updated
                changed.append(updated)
                continue
            if step.completion_conditions and all(self._condition_true(item, kernel, now) for item in step.completion_conditions):
                status = (
                    ScheduledStepStatus.COMPLETED
                    if current.status is ScheduledStepStatus.SUBMITTED
                    else ScheduledStepStatus.SKIPPED
                )
                message = (
                    "completion condition satisfied"
                    if status is ScheduledStepStatus.COMPLETED
                    else "completion condition already satisfied"
                )
                updated = StepRuntime(step.step_id, status, now, message)
                steps[step.step_id] = updated
                changed.append(updated)
                continue
            if current.status is ScheduledStepStatus.SUBMITTED:
                continue
            if now > step.latest_eligible:
                updated = StepRuntime(step.step_id, ScheduledStepStatus.EXPIRED, now, "eligibility window expired")
                steps[step.step_id] = updated
                changed.append(updated)
                if step.failure_behavior is FailureBehavior.STOP_PLAN:
                    plan_status, detail = ScheduledPlanStatus.FAILED, f"step expired: {step.step_id}"
                    break
                if step.failure_behavior is FailureBehavior.REQUEST_REPLAN:
                    plan_status, detail = ScheduledPlanStatus.NEEDS_REPLAN, f"step expired: {step.step_id}"
                    break
                continue
            if now < step.earliest_eligible:
                continue
            if not self._dependencies_satisfied(step, plan, steps):
                continue
            if not all(self._condition_true(item, kernel, now) for item in step.preconditions):
                continue
            if current.status is not ScheduledStepStatus.READY:
                updated = StepRuntime(step.step_id, ScheduledStepStatus.READY, now)
                steps[step.step_id] = updated
                changed.append(updated)
                ready.append(step)

        if plan_status is ScheduledPlanStatus.ACTIVE and steps and all(item.status in TERMINAL_STEPS for item in steps.values()):
            if any(item.status is ScheduledStepStatus.FAILED for item in steps.values()):
                plan_status, detail = ScheduledPlanStatus.FAILED, "one or more plan steps failed"
            elif any(item.status is ScheduledStepStatus.EXPIRED for item in steps.values()):
                plan_status, detail = ScheduledPlanStatus.FAILED, "one or more plan steps expired"
            elif any(item.status is ScheduledStepStatus.CANCELLED for item in steps.values()):
                plan_status, detail = ScheduledPlanStatus.CANCELLED, "all remaining work was cancelled"
            else:
                plan_status, detail = ScheduledPlanStatus.COMPLETED, None

        self._runtime[plan_id] = ScheduledPlan(plan_id, plan_status, runtime.activated_at, now, steps, detail)
        return SchedulerEvaluation(plan_id, now, plan_status, tuple(ready), tuple(changed))

    def mark_submitted(self, plan_id: str, step_id: str, kernel: PoolKernel) -> StepRuntime:
        return self._transition(plan_id, step_id, kernel, {ScheduledStepStatus.READY}, ScheduledStepStatus.SUBMITTED)

    def mark_completed(self, plan_id: str, step_id: str, kernel: PoolKernel, *, detail: Optional[str] = None) -> StepRuntime:
        return self._transition(plan_id, step_id, kernel, {ScheduledStepStatus.READY, ScheduledStepStatus.SUBMITTED}, ScheduledStepStatus.COMPLETED, detail)

    def mark_failed(self, plan_id: str, step_id: str, kernel: PoolKernel, *, detail: str) -> StepRuntime:
        if not detail.strip():
            raise ValueError("failure detail must not be empty")
        updated = self._transition(plan_id, step_id, kernel, {ScheduledStepStatus.READY, ScheduledStepStatus.SUBMITTED}, ScheduledStepStatus.FAILED, detail, refresh_plan=False)
        plan = self._plan(plan_id)
        runtime = self.get(plan_id)
        behavior = self._step(plan, step_id).failure_behavior
        status, plan_detail = runtime.status, runtime.detail
        if behavior is FailureBehavior.STOP_PLAN:
            status, plan_detail = ScheduledPlanStatus.FAILED, f"step failed: {step_id}"
        elif behavior is FailureBehavior.REQUEST_REPLAN:
            status, plan_detail = ScheduledPlanStatus.NEEDS_REPLAN, f"step failed: {step_id}"
        self._runtime[plan_id] = ScheduledPlan(plan_id, status, runtime.activated_at, self._now(kernel), runtime.steps, plan_detail)
        return updated

    def cancel(self, plan_id: str, kernel: PoolKernel, *, reason: str) -> ScheduledPlan:
        if not reason.strip():
            raise ValueError("cancellation reason must not be empty")
        runtime = self.get(plan_id)
        now = self._now(kernel)
        steps = {
            key: value if value.status in TERMINAL_STEPS else StepRuntime(key, ScheduledStepStatus.CANCELLED, now, reason)
            for key, value in runtime.steps.items()
        }
        cancelled = ScheduledPlan(plan_id, ScheduledPlanStatus.CANCELLED, runtime.activated_at, now, steps, reason)
        self._runtime[plan_id] = cancelled
        return cancelled

    def get(self, plan_id: str) -> ScheduledPlan:
        try:
            return self._runtime[plan_id]
        except KeyError as exc:
            raise ScheduledPlanNotFoundError(plan_id) from exc

    def snapshot(self, plan_id: str) -> dict[str, Any]:
        return self.get(plan_id).to_dict()

    def plan(self, plan_id: str) -> Plan:
        """Return the immutable source plan for an active scheduler entry."""

        return self._plan(plan_id)

    def step(self, plan_id: str, step_id: str) -> PlanStep:
        """Return one immutable source step from a scheduled plan."""

        return self._step(self._plan(plan_id), step_id)

    def _transition(self, plan_id: str, step_id: str, kernel: PoolKernel, allowed: set[ScheduledStepStatus], target: ScheduledStepStatus, detail: Optional[str] = None, *, refresh_plan: bool = True) -> StepRuntime:
        runtime = self.get(plan_id)
        self._step(self._plan(plan_id), step_id)
        current = runtime.steps.get(step_id)
        if current is None:
            raise ScheduledStepNotFoundError(step_id)
        if current.status not in allowed:
            raise ValueError(f"invalid transition from {current.status.value} to {target.value}")
        now = self._now(kernel)
        updated = StepRuntime(step_id, target, now, detail)
        steps = dict(runtime.steps)
        steps[step_id] = updated
        status = ScheduledPlanStatus.COMPLETED if refresh_plan and steps and all(item.status in TERMINAL_STEPS for item in steps.values()) else runtime.status
        self._runtime[plan_id] = ScheduledPlan(plan_id, status, runtime.activated_at, now, steps, None if status is ScheduledPlanStatus.COMPLETED else runtime.detail)
        return updated

    @staticmethod
    def _condition_true(condition: PlanCondition, kernel: PoolKernel, now: datetime) -> bool:
        if condition.kind is ConditionKind.TIME_REACHED:
            if not isinstance(condition.expected, datetime):
                raise TypeError("TIME_REACHED expected value must be a datetime")
            if condition.expected.tzinfo is None:
                raise ValueError("TIME_REACHED expected datetime must be timezone-aware")
            return now >= condition.expected
        if condition.kind is ConditionKind.EQUIPMENT_AVAILABLE:
            state = kernel.state.get_equipment(condition.subject_id)
            return (state.available if state else False) is bool(condition.expected)
        state = kernel.state.get_body(condition.subject_id)
        if state is None:
            return False
        if condition.kind is ConditionKind.BODY_CIRCULATION_RUNNING:
            return state.circulation_running is bool(condition.expected)
        if condition.kind is ConditionKind.BODY_TEMPERATURE_AT_LEAST:
            return state.temperature.current >= float(condition.expected)
        if condition.kind is ConditionKind.BODY_TEMPERATURE_BELOW:
            return state.temperature.current < float(condition.expected)
        raise ValueError(f"unsupported condition kind: {condition.kind.value}")

    def _dependencies_satisfied(self, step: PlanStep, plan: Plan, runtime: Mapping[str, StepRuntime]) -> bool:
        for dependency_id in step.dependencies:
            state = runtime[dependency_id]
            if state.status in {ScheduledStepStatus.COMPLETED, ScheduledStepStatus.SKIPPED}:
                continue
            dependency = self._step(plan, dependency_id)
            if state.status is ScheduledStepStatus.FAILED and dependency.failure_behavior is FailureBehavior.CONTINUE:
                continue
            return False
        return True

    @staticmethod
    def _step(plan: Plan, step_id: str) -> PlanStep:
        for step in plan.steps:
            if step.step_id == step_id:
                return step
        raise ScheduledStepNotFoundError(step_id)

    def _plan(self, plan_id: str) -> Plan:
        try:
            return self._plans[plan_id]
        except KeyError as exc:
            raise ScheduledPlanNotFoundError(plan_id) from exc

    @staticmethod
    def _now(kernel: PoolKernel) -> datetime:
        now = kernel.clock.now()
        if now.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")
        return now
