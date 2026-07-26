"""PoolOS runtime lifecycle and deterministic control loop.

Milestone 9.1 intentionally limits itself to runtime coordination. Authority,
constraints, reconciliation, and learned operational memory are layered onto
this control loop in later Runtime milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .authority import AuthorityDecision, ControlAuthority
from .constraints import ConstraintEngine, ConstraintEvaluation
from .events import PoolEvent
from .event_bus import RuntimeEventPublisher, RuntimeEventTopic
from .exceptions import RuntimeLifecycleError
from .execution import ExecutionEngine, ExecutionRecord, ExecutionStatus
from .kernel import PoolKernel
from .planning import Plan
from .reconciliation import ReconciliationEngine, ReconciliationEvaluation
from .runtime_memory import RuntimeMemory
from .runtime_context import RuntimeContext
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
class RuntimeExplanation:
    """Structured explanation of the most recently completed runtime cycle."""

    cycle_number: int
    status: RuntimeStatus
    authority_allowed: int
    authority_blocked: int
    constraints_modified: int
    constraints_blocked: int
    submitted: int
    executed: int
    execution_succeeded: int
    execution_failed: int
    reconciliation_records: int
    reconciliation_retries: int
    active_plan_ids: tuple[str, ...]
    learned_cycle_seconds: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "status": self.status.value,
            "authority": {
                "allowed": self.authority_allowed,
                "blocked": self.authority_blocked,
            },
            "constraints": {
                "modified": self.constraints_modified,
                "blocked": self.constraints_blocked,
            },
            "execution": {
                "submitted": self.submitted,
                "executed": self.executed,
                "succeeded": self.execution_succeeded,
                "failed": self.execution_failed,
            },
            "reconciliation": {
                "records": self.reconciliation_records,
                "retries": self.reconciliation_retries,
            },
            "active_plan_ids": self.active_plan_ids,
            "memory": {"learned_cycle_seconds": self.learned_cycle_seconds},
        }


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
    authority_decisions: tuple[AuthorityDecision, ...] = ()
    constraint_evaluations: tuple[ConstraintEvaluation, ...] = ()
    reconciliation_evaluation: ReconciliationEvaluation = field(
        default_factory=lambda: ReconciliationEvaluation((), ())
    )

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

    Authority and constraints are resolved before submission. Reconciliation
    and learned operational memory remain later Runtime milestones.
    """

    kernel: PoolKernel
    scheduler: Scheduler = field(default_factory=Scheduler)
    policies: PolicyEngine = field(default_factory=PolicyEngine)
    execution: ExecutionEngine = field(default_factory=ExecutionEngine)
    authority: ControlAuthority = field(default_factory=ControlAuthority)
    constraints: ConstraintEngine = field(default_factory=ConstraintEngine)
    reconciliation: ReconciliationEngine = field(default_factory=ReconciliationEngine)
    memory: RuntimeMemory = field(default_factory=RuntimeMemory)
    status: RuntimeStatus = RuntimeStatus.STOPPED
    _active_plan_ids: list[str] = field(default_factory=list)
    _event_queue: list[PoolEvent] = field(default_factory=list)
    _cycles: list[RuntimeCycle] = field(default_factory=list)
    _cycle_number: int = 0
    _command_owners: dict[str, tuple[str, str]] = field(default_factory=dict)
    _unsubscribe: Optional[Callable[[], None]] = field(default=None, init=False, repr=False)
    _event_publisher: RuntimeEventPublisher = field(init=False, repr=False)
    _last_context: Optional[RuntimeContext] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Runtime and execution audit records must share the same clock.
        self.execution.clock = self.kernel.clock
        self.authority.clock = self.kernel.clock
        self.authority.events = self.kernel.events
        self.constraints.events = self.kernel.events
        self.memory.clock = self.kernel.clock
        self.reconciliation.clock = self.kernel.clock
        self.reconciliation.events = self.kernel.events
        self.reconciliation.memory = self.memory
        self._event_publisher = RuntimeEventPublisher(self.kernel.events)
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
        next_cycle = self._cycle_number + 1
        events = self._drain_events()
        self._event_publisher.publish(
            RuntimeEventTopic.CYCLE_STARTED,
            started_at,
            payload={"cycle_number": next_cycle},
        )
        self._last_context = RuntimeContext(
            cycle_number=next_cycle,
            observed_at=started_at,
            runtime_status=self.status.value,
            active_plan_ids=tuple(self._active_plan_ids),
            pending_execution_count=len(self.execution.pending()),
            pending_reconciliation_count=len(self.reconciliation.pending()),
            events=events,
        )
        evaluations: list[SchedulerEvaluation] = []

        try:
            reconciliation_evaluation = self.reconciliation.evaluate(self.kernel)
            for plan_id in tuple(self._active_plan_ids):
                evaluation = self.scheduler.tick(plan_id, self.kernel)
                evaluations.append(evaluation)
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
            commands.extend(reconciliation_evaluation.retry_commands)

            authority_decisions = tuple(self.authority.resolve(command) for command in commands)
            authorized_commands = tuple(
                decision.command for decision in authority_decisions if decision.allowed
            )
            constraint_evaluations = tuple(
                self.constraints.evaluate(command, self.kernel)
                for command in authorized_commands
            )
            executable_commands = tuple(
                evaluation.effective_command
                for evaluation in constraint_evaluations
                if evaluation.executable and evaluation.effective_command is not None
            )
            submissions = tuple(
                self.execution.submit(command) for command in executable_commands
            )
            self._update_submitted_steps(evaluations, submissions)

            executions: tuple[ExecutionRecord, ...] = ()
            if execute:
                executions = self.execution.drain(limit=execution_limit)
                self._update_completed_steps(executions)
                for record in executions:
                    self._remember_execution(record)
                    self.reconciliation.track(record)

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
                authority_decisions=authority_decisions,
                constraint_evaluations=constraint_evaluations,
                reconciliation_evaluation=reconciliation_evaluation,
            )
            self._cycles.append(cycle)
            self.memory.observe(
                "runtime.cycle_seconds",
                max(0.0, (cycle.completed_at - cycle.started_at).total_seconds()),
                observed_at=cycle.completed_at,
            )
            self._event_publisher.publish(
                RuntimeEventTopic.CYCLE_COMPLETED,
                cycle.completed_at,
                payload={
                    "cycle_number": cycle.cycle_number,
                    "events": len(events),
                    "submitted": len(submissions),
                    "executed": len(executions),
                    "constraint_blocked": sum(
                        1 for item in constraint_evaluations if not item.executable
                    ),
                    "reconciliation_records": len(reconciliation_evaluation.records),
                    "reconciliation_retries": len(reconciliation_evaluation.retry_commands),
                },
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

    def context(self) -> Optional[RuntimeContext]:
        """Return the immutable context captured at the latest cycle start."""

        return self._last_context

    def explain(self) -> Optional[RuntimeExplanation]:
        """Explain the latest completed cycle without changing runtime state."""

        if not self._cycles:
            return None
        cycle = self._cycles[-1]
        modified = sum(
            1 for item in cycle.constraint_evaluations
            if item.disposition.value == "modify"
        )
        blocked = sum(
            1 for item in cycle.constraint_evaluations if not item.executable
        )
        succeeded = sum(
            1 for item in cycle.execution_records
            if item.status is ExecutionStatus.SUCCEEDED
        )
        return RuntimeExplanation(
            cycle_number=cycle.cycle_number,
            status=self.status,
            authority_allowed=sum(1 for item in cycle.authority_decisions if item.allowed),
            authority_blocked=sum(1 for item in cycle.authority_decisions if not item.allowed),
            constraints_modified=modified,
            constraints_blocked=blocked,
            submitted=len(cycle.submission_records),
            executed=len(cycle.execution_records),
            execution_succeeded=succeeded,
            execution_failed=len(cycle.execution_records) - succeeded,
            reconciliation_records=len(cycle.reconciliation_evaluation.records),
            reconciliation_retries=len(cycle.reconciliation_evaluation.retry_commands),
            active_plan_ids=tuple(self._active_plan_ids),
            learned_cycle_seconds=self.memory.predict("runtime.cycle_seconds"),
        )

    def _update_submitted_steps(
        self,
        evaluations: list[SchedulerEvaluation],
        submissions: tuple[ExecutionRecord, ...],
    ) -> None:
        by_id = {record.command.command_id: record for record in submissions}
        for evaluation in evaluations:
            for step in evaluation.ready_steps:
                records = [
                    by_id[command.command_id]
                    for command in step.commands
                    if command.command_id in by_id
                ]
                if len(records) != len(step.commands):
                    continue
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


    def _remember_execution(self, record: ExecutionRecord) -> None:
        observed_at = record.recorded_at
        latency = max(0.0, (record.recorded_at - record.command.issued_at).total_seconds())
        prefix = f"execution.{record.command.target}"
        self.memory.observe(
            f"{prefix}.latency_seconds",
            latency,
            observed_at=observed_at,
            tags={"status": record.status.value},
        )
        self.memory.observe(
            f"{prefix}.success",
            1.0 if record.status is ExecutionStatus.SUCCEEDED else 0.0,
            observed_at=observed_at,
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
