"""PoolOS runtime lifecycle and deterministic control loop.

Milestone 9.1 intentionally limits itself to runtime coordination. Authority,
constraints, reconciliation, and learned operational memory are layered onto
this control loop in later Runtime milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from .events import PoolEvent
from .exceptions import RuntimeLifecycleError
from .execution import ExecutionEngine, ExecutionRecord, ExecutionStatus
from .kernel import PoolKernel
from .planning import Plan
from .policies import PolicyEngine, PolicyEvaluation
from .scheduling import (
    ScheduledPlanStatus,
    Scheduler,
    SchedulerEvaluation,
    ScheduledStepStatus,
)


class RuntimeStatus(str, Enum):
    """Lifecycle states for the permanent PoolOS process."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    FAULTED = "faulted"


@dataclass(frozen=True, slots=True)
class RuntimeCycle:
    """Immutable audit result from one deterministic runtime cycle."""

    cycle_number: int
    started_at: datetime
    completed_at: datetime
    events: tuple[PoolEvent, ...]
    scheduler_evaluations: tuple[SchedulerEvaluation, ...]
    policy_evaluation: PolicyEvaluation
    submission_records: tuple[ExecutionRecord, ...]
    execution_records: tuple[ExecutionRecord, ...]

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("runtime cycle timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("runtime cycle cannot complete before it starts")


@dataclass(slots=True)
class PoolRuntime:
    """Coordinate the PoolOS control loop without owning hardware logic.

    A cycle performs five deterministic phases:

    1. Drain events observed since the prior cycle.
    2. Evaluate each active scheduled plan.
    3. Evaluate registered policies against the kernel state.
    4. Submit resulting commands through the sole Execution Engine path.
    5. Optionally drain the execution queue and update scheduler progress.

    This class deliberately does not yet decide control authority, apply hard
    safety constraints, or reconcile desired and actual state. Those concerns
    are added by Milestones 9.2 through 9.4 without changing this lifecycle.
    """

    kernel: PoolKernel
    scheduler: Scheduler = field(default_factory=Scheduler)
    policies: PolicyEngine = field(default_factory=PolicyEngine)
    execution: ExecutionEngine = field(default_factory=ExecutionEngine)
    status: RuntimeStatus = RuntimeStatus.STOPPED
    _active_plan_ids: list[str] = field(default_factory=list)
    _event_queue: list[PoolEvent] = field(default_factory=list)
    _cycles: list[RuntimeCycle] = field(default_factory=list)
    _cycle_number: int = 0
    _command_owners: dict[str, tuple[str, str]] = field(default_factory=dict)
    _unsubscribe: Optional[Callable[[], None]] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Runtime and execution audit records must share the same clock.
        self.execution.clock = self.kernel.clock
        self._unsubscribe = self.kernel.events.subscribe("*", self._event_queue.append)

    def start(self) -> None:
        """Start a stopped runtime."""

        if self.status is not RuntimeStatus.STOPPED:
            raise RuntimeLifecycleError(
                f"cannot start runtime while {self.status.value}"
            )
        self.status = RuntimeStatus.RUNNING
        self._publish_lifecycle("runtime.started")

    def pause(self) -> None:
        """Pause control cycles while retaining plans and queued events."""

        if self.status is not RuntimeStatus.RUNNING:
            raise RuntimeLifecycleError(
                f"cannot pause runtime while {self.status.value}"
            )
        self.status = RuntimeStatus.PAUSED
        self._publish_lifecycle("runtime.paused")

    def resume(self) -> None:
        """Resume a paused runtime."""

        if self.status is not RuntimeStatus.PAUSED:
            raise RuntimeLifecycleError(
                f"cannot resume runtime while {self.status.value}"
            )
        self.status = RuntimeStatus.RUNNING
        self._publish_lifecycle("runtime.resumed")

    def stop(self) -> None:
        """Stop the runtime without discarding scheduler state."""

        if self.status is RuntimeStatus.STOPPED:
            return
        self.status = RuntimeStatus.STOPPED
        self._publish_lifecycle("runtime.stopped")

    def close(self) -> None:
        """Stop and detach the runtime from the kernel event bus."""

        self.stop()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def activate_plan(self, plan: Plan) -> None:
        """Activate a planner result for evaluation by future cycles."""

        self.scheduler.activate(plan, self.kernel)
        self._active_plan_ids.append(plan.plan_id)
        self.kernel.events.publish(
            PoolEvent(
                topic="runtime.plan.activated",
                occurred_at=self._now(),
                source=plan.plan_id,
                payload={"revision": plan.revision},
            )
        )

    def tick(self, *, execute: bool = True, execution_limit: Optional[int] = None) -> RuntimeCycle:
        """Run one complete control cycle.

        ``execute=False`` is useful for dry runs and host applications that
        want to submit commands now but drain the execution queue elsewhere.
        """

        if self.status is not RuntimeStatus.RUNNING:
            raise RuntimeLifecycleError(
                f"cannot tick runtime while {self.status.value}"
            )
        if execution_limit is not None and execution_limit < 0:
            raise ValueError("execution_limit must be zero or greater")

        started_at = self._now()
        events = self._drain_events()
        evaluations: list[SchedulerEvaluation] = []

        try:
            for plan_id in tuple(self._active_plan_ids):
                evaluation = self.scheduler.tick(plan_id, self.kernel)
                evaluations.append(evaluation)
                plan = self.scheduler.plan(plan_id)
                for step in evaluation.ready_steps:
                    for command in step.commands:
                        self._command_owners[command.command_id] = (plan_id, step.step_id)

                if evaluation.plan_status is not ScheduledPlanStatus.ACTIVE:
                    self._active_plan_ids.remove(plan_id)

            policy_evaluation = self.policies.evaluate(self.kernel)

            commands = [
                command
                for evaluation in evaluations
                for command in evaluation.commands
            ]
            commands.extend(policy_evaluation.commands)

            submissions = tuple(self.execution.submit(command) for command in commands)
            self._update_submitted_steps(evaluations, submissions)

            executions: tuple[ExecutionRecord, ...] = ()
            if execute:
                executions = self.execution.drain(limit=execution_limit)
                self._update_completed_steps(executions)

            self._cycle_number += 1
            cycle = RuntimeCycle(
                cycle_number=self._cycle_number,
                started_at=started_at,
                completed_at=self._now(),
                events=events,
                scheduler_evaluations=tuple(evaluations),
                policy_evaluation=policy_evaluation,
                submission_records=submissions,
                execution_records=executions,
            )
            self._cycles.append(cycle)
            self.kernel.events.publish(
                PoolEvent(
                    topic="runtime.cycle.completed",
                    occurred_at=cycle.completed_at,
                    source="pool_runtime",
                    payload={
                        "cycle_number": cycle.cycle_number,
                        "events": len(events),
                        "submitted": len(submissions),
                        "executed": len(executions),
                    },
                )
            )
            return cycle
        except Exception as exc:
            self.status = RuntimeStatus.FAULTED
            self.kernel.events.publish(
                PoolEvent(
                    topic="runtime.faulted",
                    occurred_at=self._now(),
                    source="pool_runtime",
                    payload={"error": str(exc) or exc.__class__.__name__},
                )
            )
            raise

    def cycles(self) -> tuple[RuntimeCycle, ...]:
        """Return the immutable cycle history."""

        return tuple(self._cycles)

    def pending_events(self) -> tuple[PoolEvent, ...]:
        """Return events waiting for the next cycle."""

        return tuple(self._event_queue)

    def active_plan_ids(self) -> tuple[str, ...]:
        """Return plans currently evaluated by the runtime."""

        return tuple(self._active_plan_ids)

    def _update_submitted_steps(
        self,
        evaluations: list[SchedulerEvaluation],
        submissions: tuple[ExecutionRecord, ...],
    ) -> None:
        by_id = {record.command.command_id: record for record in submissions}
        for evaluation in evaluations:
            for step in evaluation.ready_steps:
                records = [by_id[command.command_id] for command in step.commands]
                if all(record.status is ExecutionStatus.QUEUED for record in records):
                    self.scheduler.mark_submitted(
                        evaluation.plan_id, step.step_id, self.kernel
                    )
                else:
                    for record in records:
                        self._command_owners.pop(record.command.command_id, None)
                    details = "; ".join(
                        record.detail or record.status.value for record in records
                    )
                    self.scheduler.mark_failed(
                        evaluation.plan_id,
                        step.step_id,
                        self.kernel,
                        detail=details,
                    )

    def _update_completed_steps(
        self,
        executions: tuple[ExecutionRecord, ...],
    ) -> None:
        grouped: dict[tuple[str, str], list[ExecutionRecord]] = {}
        for record in executions:
            owner = self._command_owners.pop(record.command.command_id, None)
            if owner is not None:
                grouped.setdefault(owner, []).append(record)

        for (plan_id, step_id), records in grouped.items():
            if any(record.status is not ExecutionStatus.SUCCEEDED for record in records):
                detail = "; ".join(
                    record.detail or record.status.value for record in records
                )
                self.scheduler.mark_failed(
                    plan_id, step_id, self.kernel, detail=detail
                )
                continue

            step = self.scheduler.step(plan_id, step_id)
            if not step.completion_conditions:
                current = self.scheduler.get(plan_id).steps[step_id]
                if current.status is ScheduledStepStatus.SUBMITTED:
                    self.scheduler.mark_completed(
                        plan_id,
                        step_id,
                        self.kernel,
                        detail="all commands executed successfully",
                    )

    def _drain_events(self) -> tuple[PoolEvent, ...]:
        events = tuple(self._event_queue)
        self._event_queue.clear()
        return events

    def _publish_lifecycle(self, topic: str) -> None:
        self.kernel.events.publish(
            PoolEvent(
                topic=topic,
                occurred_at=self._now(),
                source="pool_runtime",
                payload={"status": self.status.value},
            )
        )

    def _now(self) -> datetime:
        now = self.kernel.clock.now()
        if now.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")
        return now
