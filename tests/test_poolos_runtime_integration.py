from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.constraints import ConstraintDecision, ConstraintDisposition
from poolos.execution import ExecutionStatus
from poolos.kernel import PoolKernel
from poolos.planning import Plan, PlanStatus, PlanStep
from poolos.policies import PolicyEngine
from poolos.runtime import PoolRuntime
from poolos.runtime_context import RuntimeContext


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
    return Plan(
        plan_id="integration-plan",
        objective_id="integration-objective",
        created_at=now,
        horizon_start=now,
        horizon_end=now + timedelta(hours=1),
        status=PlanStatus.ACTIVE,
        steps=(
            PlanStep(
                step_id="integration-step",
                sequence=1,
                earliest_eligible=now,
                latest_eligible=now + timedelta(minutes=30),
                commands=(command,),
            ),
        ),
    )


def test_runtime_context_is_captured_and_read_only():
    runtime, _ = make_runtime()
    runtime.start()
    runtime.tick(execute=False)

    context = runtime.context()
    assert isinstance(context, RuntimeContext)
    assert context.cycle_number == 1
    assert context.runtime_status == "running"
    assert any(event.topic == "runtime.started" for event in context.events)


def test_end_to_end_cycle_exposes_structured_explanation():
    runtime, kernel = make_runtime()
    command = Command(target="pump.main", action=CommandAction.START)
    executor = RecordingExecutor([])
    runtime.execution.register_executor("pump.main", executor)
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()
    explanation = runtime.explain()

    assert cycle.execution_records[0].status is ExecutionStatus.SUCCEEDED
    assert executor.commands == [command]
    assert explanation is not None
    assert explanation.cycle_number == 1
    assert explanation.authority_allowed == 1
    assert explanation.submitted == 1
    assert explanation.execution_succeeded == 1
    assert explanation.as_dict()["execution"]["succeeded"] == 1


def test_constraint_modification_is_visible_in_explanation():
    runtime, kernel = make_runtime()

    @dataclass
    class GridCap:
        constraint_id: str = "grid_cap"
        priority: int = 1

        def evaluate(self, command, context):
            replacement = runtime.constraints.replace_command(command, value=1800)
            return ConstraintDecision.modify(
                self.constraint_id,
                command,
                replacement,
                context.evaluated_at,
                "grid outage cap",
            )

    runtime.constraints.register(GridCap())
    command = Command(target="pump.rpm", action=CommandAction.SET, value=3200)
    executor = RecordingExecutor([])
    runtime.execution.register_executor("pump.rpm", executor)
    runtime.activate_plan(make_plan(kernel.clock.now(), command))
    runtime.start()

    cycle = runtime.tick()
    explanation = runtime.explain()

    assert cycle.constraint_evaluations[0].disposition is ConstraintDisposition.MODIFY
    assert executor.commands[0].value == 1800
    assert explanation is not None
    assert explanation.constraints_modified == 1
    assert explanation.constraints_blocked == 0


def test_cycle_events_are_published_on_existing_kernel_bus():
    runtime, kernel = make_runtime()
    observed = []
    kernel.events.subscribe("*", observed.append)
    runtime.start()
    runtime.tick(execute=False)

    topics = [event.topic for event in observed]
    assert "runtime.cycle.started" in topics
    assert "runtime.cycle.completed" in topics
