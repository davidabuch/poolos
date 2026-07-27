"""Architecture contract tests for PoolOS planning models.

These tests intentionally protect the public behavior of PlanObjective, PlanStep,
Plan, and the current Command-based planner boundary before Milestone 10.4
changes that boundary. They should change only when an architecture decision
explicitly changes the contract.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.enums import BodyType, CommandPriority, EquipmentType
from poolos.equipment import Equipment
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import (
    FailureBehavior,
    ObjectiveType,
    Plan,
    PlanObjective,
    PlanStatus,
    PlanStep,
)
from poolos.planning_strategies import build_default_planner


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def make_kernel(*, temperature: float = 90.0) -> PoolKernel:
    """Return the smallest normalized runtime needed by the deadline planner."""

    kernel = PoolKernel(clock=FixedClock(NOW))
    kernel.bodies.register(Body("spa", "Spa", BodyType.SPA))
    kernel.equipment.register(
        Equipment(
            "pump",
            "Filter Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            body=BodyType.SPA,
        )
    )
    kernel.equipment.register(
        Equipment(
            "heater",
            "Gas Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            body=BodyType.SPA,
        )
    )
    kernel.update_body_state(
        "spa",
        BodyState(
            body=BodyType.SPA,
            temperature=TemperatureState(temperature, 100.0, False),
            circulation_running=False,
            sanitizer_enabled=False,
        ),
    )
    return kernel


def make_objective() -> PlanObjective:
    """Return a deterministic objective suitable for contract assertions."""

    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        maintain_until=NOW + timedelta(hours=5),
        priority=CommandPriority.HIGH,
        requested_by="contract-test",
        correlation_id="session-1",
        metadata={"source": "test"},
        objective_id="objective-1",
    )


def test_planning_models_are_immutable_snapshots():
    objective = make_objective()
    plan = build_default_planner().create_plan(objective, make_kernel())

    with pytest.raises(FrozenInstanceError):
        objective.target_temperature = 101.0

    with pytest.raises(FrozenInstanceError):
        plan.status = PlanStatus.ACTIVE

    with pytest.raises(FrozenInstanceError):
        plan.steps[0].sequence = 99

    with pytest.raises(TypeError):
        objective.metadata["source"] = "changed"

    with pytest.raises(TypeError):
        plan.steps[0].commands[0].metadata["objective_id"] = "changed"


def test_plan_step_contract_is_ordered_dependent_and_command_based():
    plan = build_default_planner(heating_rate_degrees_per_hour=5.0).create_plan(
        make_objective(),
        make_kernel(),
    )

    assert isinstance(plan.steps, tuple)
    assert [step.sequence for step in plan.steps] == [1, 2, 3]
    assert all(isinstance(step.commands, tuple) for step in plan.steps)
    assert all(
        isinstance(command, Command)
        for step in plan.steps
        for command in step.commands
    )
    assert plan.steps[1].dependencies == (plan.steps[0].step_id,)
    assert plan.steps[2].dependencies == (plan.steps[1].step_id,)
    assert plan.steps[0].failure_behavior is FailureBehavior.REQUEST_REPLAN
    assert plan.steps[2].failure_behavior is FailureBehavior.CONTINUE


def test_planner_preserves_objective_context_on_every_proposed_command():
    objective = make_objective()
    plan = build_default_planner().create_plan(objective, make_kernel())

    for step in plan.steps:
        for command in step.commands:
            assert command.priority is objective.priority
            assert command.requested_by == objective.requested_by
            assert command.correlation_id == objective.correlation_id
            assert command.issued_at == NOW
            assert command.metadata["objective_id"] == objective.objective_id
            assert command.metadata["body_id"] == objective.body_id
            assert command.metadata["target_temperature"] == 100.0
            assert command.metadata["plan_revision"] == 1


def test_plan_serialization_is_plain_stable_data_at_the_boundary():
    objective = make_objective()
    plan = build_default_planner().create_plan(objective, make_kernel())
    data = plan.to_dict()

    assert data["objective_id"] == objective.objective_id
    assert data["status"] == "draft"
    assert data["revision"] == 1
    assert isinstance(data["steps"], list)
    assert data["steps"][0]["commands"][0]["action"] == "start"
    assert data["steps"][0]["commands"][0]["issued_at"] == NOW.isoformat()
    assert data["steps"][0]["dependencies"] == []
    assert data["steps"][1]["dependencies"] == [plan.steps[0].step_id]
    assert isinstance(data["assumptions"], list)
    assert isinstance(data["constraints"], list)
    assert isinstance(data["rationale"], list)


def test_plan_rejects_unknown_dependencies():
    command = Command(
        target="pump",
        action=CommandAction.START,
        issued_at=NOW,
    )
    step = PlanStep(
        sequence=1,
        earliest_eligible=NOW,
        latest_eligible=NOW + timedelta(minutes=5),
        commands=(command,),
        dependencies=("missing-step",),
        step_id="step-1",
    )

    with pytest.raises(ValueError, match="unknown step dependencies"):
        Plan(
            objective_id="objective-1",
            created_at=NOW,
            horizon_start=NOW,
            horizon_end=NOW + timedelta(hours=1),
            status=PlanStatus.DRAFT,
            steps=(step,),
            plan_id="plan-1",
        )


def test_planning_proposes_work_but_does_not_mutate_runtime_state():
    kernel = make_kernel()
    before = kernel.state.get_body("spa")

    plan = build_default_planner().create_plan(make_objective(), kernel)

    after = kernel.state.get_body("spa")
    assert plan.status is PlanStatus.DRAFT
    assert before == after
    assert after is not None
    assert after.circulation_running is False
    assert after.temperature.current == 90.0
