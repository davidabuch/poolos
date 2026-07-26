from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.events import PoolEvent
from poolos.exceptions import RuntimeLifecycleError
from poolos.execution import ExecutionStatus
from poolos.kernel import PoolKernel
from poolos.planning import Plan, PlanStatus, PlanStep
from poolos.policies import PolicyEngine
from poolos.runtime import PoolRuntime, RuntimeStatus


@dataclass
class RecordingExecutor:
    commands: list

    def execute(self, command):
        self.commands.append(command)
        return {"ok": True}


def make_runtime():
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    kernel = PoolKernel(clock=FixedClock(now))
    runtime = PoolRuntime(kernel=kernel, policies=PolicyEngine())
    return runtime, kernel


def make_plan(now, command):
    step = PlanStep(
        step_id="step-1",
        sequence=1,
        earliest_eligible=now,
        latest_eligible=now + timedelta(hours=1),
        commands=(command,),
    )
    return Plan(
        plan_id="plan-1",
        objective_id="objective-1",
        created_at=now,
        horizon_start=now,
        horizon_end=now + timedelta(hours=2),
        status=PlanStatus.ACTIVE,
        steps=(step,),
    )


def test_runtime_lifecycle_and_event_pump():
    runtime, _ = make_runtime()
    runtime.start()
    assert runtime.status is RuntimeStatus.RUNNING
    assert runtime.pending_events()[0].topic == "runtime.started"

    cycle = runtime.tick(execute=False)
    assert cycle.cycle_number == 1
    assert [event.topic for event in cycle.events] == ["runtime.started"]

    runtime.pause()
    assert runtime.status is RuntimeStatus.PAUSED
    with pytest.raises(RuntimeLifecycleError):
        runtime.tick()
    runtime.resume()
    runtime.stop()
    assert runtime.status is RuntimeStatus.STOPPED


def test_runtime_executes_ready_plan_step_and_marks_complete():
    runtime, kernel = make_runtime()
    command = Command(target="pump", action=CommandAction.START)
    executor = RecordingExecutor([])
    runtime.execution.register_executor("pump", executor)
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()

    assert [record.status for record in cycle.submission_records] == [ExecutionStatus.QUEUED]
    assert [record.status for record in cycle.execution_records] == [ExecutionStatus.SUCCEEDED]
    assert executor.commands == [command]
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "completed"


def test_runtime_dry_run_leaves_command_pending_and_step_submitted():
    runtime, kernel = make_runtime()
    command = Command(target="pump", action=CommandAction.START)
    runtime.execution.register_executor("pump", RecordingExecutor([]))
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick(execute=False)

    assert cycle.execution_records == ()
    assert runtime.execution.pending() == (command,)
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "submitted"


def test_missing_executor_is_audited_without_faulting_runtime():
    runtime, kernel = make_runtime()
    command = Command(target="missing", action=CommandAction.START)
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()

    assert cycle.execution_records[0].status is ExecutionStatus.REJECTED
    assert runtime.status is RuntimeStatus.RUNNING
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "failed"


def test_runtime_close_unsubscribes_from_event_bus():
    runtime, kernel = make_runtime()
    runtime.start()
    runtime.close()
    count = len(runtime.pending_events())
    kernel.events.publish(
        PoolEvent(
            topic="external.test",
            occurred_at=kernel.clock.now(),
            source="test",
        )
    )
    assert len(runtime.pending_events()) == count


def test_invalid_lifecycle_transitions_are_rejected():
    runtime, _ = make_runtime()
    with pytest.raises(RuntimeLifecycleError):
        runtime.pause()
    with pytest.raises(RuntimeLifecycleError):
        runtime.resume()
    runtime.start()
    with pytest.raises(RuntimeLifecycleError):
        runtime.start()


def test_dry_run_command_completes_step_when_executed_on_later_cycle():
    runtime, kernel = make_runtime()
    command = Command(target="pump", action=CommandAction.START)
    runtime.execution.register_executor("pump", RecordingExecutor([]))
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    runtime.tick(execute=False)
    second = runtime.tick(execute=True)

    assert second.execution_records[0].status is ExecutionStatus.SUCCEEDED
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "completed"



def test_runtime_applies_authority_before_execution():
    """Scoped manual ownership suppresses competing runtime commands."""
    from poolos.authority import ControlSource, ControlSourceType

    runtime, kernel = make_runtime()
    runtime.authority.register_source(
        ControlSource("pentair_panel", ControlSourceType.LOCAL_PANEL)
    )
    runtime.authority.acquire_override(
        source_id="pentair_panel", scope="pump.main", duration=timedelta(minutes=30)
    )
    command = Command(target="pump.main", action=CommandAction.START)
    runtime.execution.register_executor("pump.main", RecordingExecutor([]))
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()

    assert len(cycle.authority_decisions) == 1
    assert not cycle.authority_decisions[0].allowed
    assert cycle.submission_records == ()
    assert cycle.execution_records == ()
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "ready"


def test_runtime_applies_constraints_after_authority_and_before_execution():
    from poolos.constraints import ConstraintDecision, ConstraintDisposition

    @dataclass
    class CapConstraint:
        constraint_id: str = "cap"
        priority: int = 10

        def evaluate(self, command, context):
            replacement = runtime.constraints.replace_command(command, value=1800)
            return ConstraintDecision.modify(
                self.constraint_id,
                command,
                replacement,
                context.evaluated_at,
                "energy cap",
            )

    runtime, kernel = make_runtime()
    runtime.constraints.register(CapConstraint())
    command = Command(target="pump.rpm", action=CommandAction.SET, value=3200)
    executor = RecordingExecutor([])
    runtime.execution.register_executor("pump.rpm", executor)
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()

    assert cycle.constraint_evaluations[0].disposition is ConstraintDisposition.MODIFY
    assert executor.commands[0].value == 1800
    assert executor.commands[0].command_id == command.command_id
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "completed"


def test_runtime_keeps_step_ready_when_constraint_defers_command():
    from poolos.constraints import ConstraintDecision, ConstraintDisposition

    @dataclass
    class WaitForPrime:
        constraint_id: str = "wait_for_prime"
        priority: int = 10

        def evaluate(self, command, context):
            return ConstraintDecision.defer(
                self.constraint_id,
                command,
                context.evaluated_at,
                "not primed",
            )

    runtime, kernel = make_runtime()
    runtime.constraints.register(WaitForPrime())
    command = Command(target="heater", action=CommandAction.START)
    runtime.execution.register_executor("heater", RecordingExecutor([]))
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()

    assert cycle.constraint_evaluations[0].disposition is ConstraintDisposition.DEFER
    assert cycle.submission_records == ()
    assert cycle.execution_records == ()
    assert runtime.scheduler.get("plan-1").steps["step-1"].status.value == "ready"


def test_runtime_tracks_success_and_resubmits_reconciliation_retry():
    from poolos.reconciliation import VerificationObservation, VerificationPolicy

    runtime, kernel = make_runtime()
    command = Command(target="pump", action=CommandAction.START)
    executor = RecordingExecutor([])
    runtime.execution.register_executor("pump", executor)
    runtime.reconciliation.register_verifier(
        "pump",
        lambda observed_kernel, requested: VerificationObservation(False, detail="not running"),
        policy=VerificationPolicy(retry_delay=timedelta(0), max_attempts=2),
    )
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    first = runtime.tick()
    assert len(runtime.reconciliation.pending()) == 1
    assert first.reconciliation_evaluation.records == ()

    second = runtime.tick()
    assert second.reconciliation_evaluation.records[0].disposition.value == "retry"
    assert len(second.submission_records) == 1
    assert second.submission_records[0].command.metadata["retry_of"] == command.command_id
    assert len(executor.commands) == 2


def test_runtime_records_stable_reconciliation_on_following_cycle():
    from poolos.reconciliation import VerificationObservation

    runtime, kernel = make_runtime()
    command = Command(target="pump", action=CommandAction.START)
    runtime.execution.register_executor("pump", RecordingExecutor([]))
    runtime.reconciliation.register_verifier(
        "pump", lambda observed_kernel, requested: VerificationObservation(True, actual="on")
    )
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()
    runtime.tick()

    second = runtime.tick()
    assert second.reconciliation_evaluation.records[0].disposition.value == "stable"
    assert runtime.reconciliation.pending() == ()
