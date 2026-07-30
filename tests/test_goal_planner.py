from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.goal_planner import (
    BodyReadyGoal,
    FeasibilityStatus,
    GoalPlanner,
)
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import PlanStatus
from poolos.planning_strategies import build_default_planner

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


def kernel(*, temperature: float = 90.0) -> PoolKernel:
    value = PoolKernel(clock=FixedClock(NOW))
    value.bodies.register(Body("spa", "Spa", BodyType.SPA))
    value.equipment.register(Equipment("pump", "Pump", EquipmentType.PUMP, frozenset({Capability.CIRCULATION}), body=BodyType.SPA))
    value.equipment.register(Equipment("heater", "Heater", EquipmentType.HEATER, frozenset({Capability.HEATING}), body=BodyType.SPA))
    value.update_body_state("spa", BodyState(BodyType.SPA, TemperatureState(temperature, 100.0, False), False, False))
    return value


def planner(*, rate: float = 5.0, buffer: timedelta = timedelta(minutes=15)) -> GoalPlanner:
    return GoalPlanner(build_default_planner(heating_rate_degrees_per_hour=rate), rate, buffer)


def goal(*, deadline_hours: float = 3.0, target: float = 100.0, earliest_start=None) -> BodyReadyGoal:
    return BodyReadyGoal("spa", target, NOW + timedelta(hours=deadline_hours), maintain_until=NOW + timedelta(hours=4), earliest_start=earliest_start, requested_by="user", correlation_id="session")


def test_feasible_goal_calculates_required_duration_and_recommended_start():
    assessment = planner().assess(goal(), kernel())
    assert assessment.status is FeasibilityStatus.FEASIBLE
    assert assessment.required_duration == timedelta(hours=2)
    assert assessment.available_duration == timedelta(hours=3)
    assert assessment.recommended_start == NOW + timedelta(hours=1)
    assert assessment.can_meet_deadline


def test_achieved_goal_is_recognized_without_heating():
    result = planner().create_plan(goal(), kernel(temperature=100.0))
    assert result.assessment.status is FeasibilityStatus.ACHIEVED
    assert result.plan.status is PlanStatus.COMPLETED
    assert result.plan.steps == ()


def test_infeasible_goal_is_reported_but_still_produces_traceable_plan():
    result = planner().create_plan(goal(deadline_hours=1), kernel())
    assert result.assessment.status is FeasibilityStatus.INFEASIBLE
    assert not result.assessment.can_meet_deadline
    assert result.objective.metadata["feasibility"] == "infeasible"
    assert result.plan.horizon_start == NOW


def test_goal_without_risk_buffer_is_at_risk():
    assessment = planner(buffer=timedelta(minutes=30)).assess(goal(deadline_hours=2.25), kernel())
    assert assessment.status is FeasibilityStatus.AT_RISK
    assert not assessment.can_meet_deadline


def test_earliest_start_reduces_available_window():
    assessment = planner().assess(goal(deadline_hours=3, earliest_start=NOW + timedelta(hours=2)), kernel())
    assert assessment.available_duration == timedelta(hours=1)
    assert assessment.status is FeasibilityStatus.INFEASIBLE


def test_goal_normalizes_into_existing_objective_and_plan():
    original = goal()
    result = planner().create_plan(original, kernel())
    assert result.objective.objective_id == original.goal_id
    assert result.objective.metadata["goal_id"] == original.goal_id
    assert result.objective.correlation_id == "session"
    assert result.plan.objective_id == original.goal_id
    assert [step.sequence for step in result.plan.steps] == [1, 2, 3]


def test_assessment_requires_future_deadline():
    past = BodyReadyGoal("spa", 100.0, NOW - timedelta(minutes=1))
    with pytest.raises(ValueError, match="future"):
        planner().assess(past, kernel())


def test_assessment_requires_body_runtime_state():
    value = kernel()
    value.state._bodies.clear()
    with pytest.raises(ValueError, match="runtime state"):
        planner().assess(goal(), value)


def test_goal_metadata_is_immutable_and_preserved():
    metadata = {"source": "dashboard"}
    original = BodyReadyGoal("spa", 100.0, NOW + timedelta(hours=3), metadata=metadata)
    metadata["source"] = "changed"
    result = planner().create_plan(original, kernel())
    assert original.metadata["source"] == "dashboard"
    assert result.objective.metadata["source"] == "dashboard"


def test_goal_and_planner_reject_invalid_configuration():
    with pytest.raises(ValueError, match="target_temperature"):
        BodyReadyGoal("spa", 120.0, NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="positive"):
        GoalPlanner(build_default_planner(), 0)
    with pytest.raises(ValueError, match="risk_buffer"):
        GoalPlanner(build_default_planner(), 5, timedelta(minutes=-1))
