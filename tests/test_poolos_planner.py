from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.commands import CommandAction
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.exceptions import (
    DuplicatePlanningStrategyError,
    PlanNotFoundError,
    PlanningStrategyNotFoundError,
)
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import (
    ConditionKind,
    ObjectiveType,
    PlanCondition,
    PlanObjective,
    PlanStatus,
    Planner,
)
from poolos.planning_strategies import (
    PrepareBodyByDeadlineStrategy,
    build_default_planner,
)


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def kernel_with_spa(*, temperature: float = 90.0) -> PoolKernel:
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


def objective(*, objective_id: str = "objective-1") -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        maintain_until=NOW + timedelta(hours=5),
        requested_by="user",
        correlation_id="session-1",
        objective_id=objective_id,
    )


def test_prepare_body_plan_sequences_circulation_heat_and_stop():
    planner = build_default_planner(heating_rate_degrees_per_hour=5.0)
    plan = planner.create_plan(objective(), kernel_with_spa())

    assert plan.status is PlanStatus.DRAFT
    assert plan.revision == 1
    assert [step.sequence for step in plan.steps] == [1, 2, 3]
    assert plan.steps[0].commands[0].target == "pump"
    assert plan.steps[0].commands[0].action is CommandAction.START
    assert plan.steps[1].dependencies == (plan.steps[0].step_id,)
    assert plan.steps[1].commands[0].target == "heater"
    assert plan.steps[1].commands[0].value == 100.0
    assert plan.steps[2].commands[0].action is CommandAction.STOP
    assert plan.steps[2].earliest_eligible == NOW + timedelta(hours=5)
    assert plan.horizon_start == NOW + timedelta(hours=1)


def test_plan_is_completed_without_commands_when_target_already_met():
    plan = build_default_planner().create_plan(objective(), kernel_with_spa(temperature=100.0))
    assert plan.status is PlanStatus.COMPLETED
    assert plan.steps == ()
    assert plan.estimated_completion == NOW


def test_replan_supersedes_previous_revision_and_keeps_history():
    planner = build_default_planner()
    obj = objective()
    first = planner.create_plan(obj, kernel_with_spa())
    second = planner.replan(
        obj,
        kernel_with_spa(temperature=95.0),
        previous_plan_id=first.plan_id,
        reason="Heating progressed faster than expected.",
    )

    assert planner.get_plan(first.plan_id).status is PlanStatus.SUPERSEDED
    assert second.revision == 2
    assert second.supersedes_plan_id == first.plan_id
    assert second.replan_reason == "Heating progressed faster than expected."
    assert planner.latest_for(obj.objective_id) == second
    assert len(planner.history_for(obj.objective_id)) == 2


def test_plans_and_conditions_are_serializable_to_plain_data():
    obj = objective()
    plan = build_default_planner().create_plan(obj, kernel_with_spa())
    data = plan.to_dict()
    condition = PlanCondition(ConditionKind.TIME_REACHED, "spa", NOW)

    assert data["objective_id"] == obj.objective_id
    assert data["steps"][0]["commands"][0]["action"] == "start"
    assert condition.to_dict()["expected"] == NOW.isoformat()
    assert obj.to_dict()["deadline"] == obj.deadline.isoformat()


def test_objective_rejects_invalid_time_window_and_temperature():
    with pytest.raises(ValueError, match="deadline"):
        PlanObjective(
            ObjectiveType.PREPARE_BODY_BY_DEADLINE,
            "spa",
            100.0,
            NOW,
            NOW,
        )
    with pytest.raises(ValueError, match="target_temperature"):
        PlanObjective(
            ObjectiveType.PREPARE_BODY_BY_DEADLINE,
            "spa",
            120.0,
            NOW,
            NOW + timedelta(hours=1),
        )


def test_strategy_requires_runtime_state_and_required_capabilities():
    kernel = PoolKernel(clock=FixedClock(NOW))
    kernel.bodies.register(Body("spa", "Spa", BodyType.SPA))
    with pytest.raises(ValueError, match="runtime state"):
        build_default_planner().create_plan(objective(), kernel)

    kernel.update_body_state(
        "spa",
        BodyState(
            BodyType.SPA,
            TemperatureState(90.0, 100.0, False),
            False,
            False,
        ),
    )
    with pytest.raises(ValueError, match="heater"):
        build_default_planner().create_plan(objective(), kernel)


def test_planner_registration_and_lookup_errors_are_explicit():
    planner = Planner()
    strategy = PrepareBodyByDeadlineStrategy()
    planner.register_strategy(strategy)
    with pytest.raises(DuplicatePlanningStrategyError):
        planner.register_strategy(strategy)
    with pytest.raises(PlanNotFoundError):
        planner.get_plan("missing")

    empty = Planner()
    with pytest.raises(PlanningStrategyNotFoundError):
        empty.create_plan(objective(), kernel_with_spa())


def test_replan_validates_reason_and_objective_ownership():
    planner = build_default_planner()
    first_obj = objective(objective_id="one")
    first = planner.create_plan(first_obj, kernel_with_spa())
    with pytest.raises(ValueError, match="reason"):
        planner.replan(
            first_obj,
            kernel_with_spa(),
            previous_plan_id=first.plan_id,
            reason=" ",
        )
    with pytest.raises(ValueError, match="different objective"):
        planner.replan(
            objective(objective_id="two"),
            kernel_with_spa(),
            previous_plan_id=first.plan_id,
            reason="Changed request",
        )
