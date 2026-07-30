from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.energy_optimization import (
    EnergyCostOptimizer,
    EnergySource,
    EnergyStrategy,
    OptimizationStatus,
    TariffWindow,
)
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.goal_planner import BodyReadyGoal, GoalPlanner
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning_strategies import build_default_planner

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
DEADLINE = NOW + timedelta(hours=4)


def strategy(strategy_id, start, *, source=EnergySource.GRID, grid=1.0, solar=0.0, battery=0.0):
    return EnergyStrategy(strategy_id, source, 5.0, start, start + timedelta(hours=2), grid, solar, battery)


def optimizer():
    return EnergyCostOptimizer((
        TariffWindow(NOW, NOW + timedelta(hours=2), 0.40, "peak"),
        TariffWindow(NOW + timedelta(hours=2), NOW + timedelta(hours=6), 0.15, "off_peak"),
    ), solar_value_per_kwh=0.05, battery_degradation_per_kwh=0.08)


def kernel():
    value = PoolKernel(clock=FixedClock(NOW))
    value.bodies.register(Body("spa", "Spa", BodyType.SPA))
    value.equipment.register(Equipment("pump", "Pump", EquipmentType.PUMP, frozenset({Capability.CIRCULATION}), body=BodyType.SPA))
    value.equipment.register(Equipment("heater", "Heater", EquipmentType.HEATER, frozenset({Capability.HEATING}), body=BodyType.SPA))
    value.update_body_state("spa", BodyState(BodyType.SPA, TemperatureState(90.0, 100.0, False), False, False))
    return value


def test_selects_least_cost_feasible_grid_strategy():
    peak = strategy("peak", NOW)
    off_peak = strategy("off_peak", NOW + timedelta(hours=2))
    result = optimizer().optimize((peak, off_peak), earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert result.status is OptimizationStatus.OPTIMIZED
    assert result.selected.strategy.strategy_id == "off_peak"
    assert result.selected.estimated_cost == pytest.approx(1.5)


def test_solar_strategy_can_beat_grid_strategy():
    grid = strategy("grid", NOW)
    solar = strategy("solar", NOW, source=EnergySource.SOLAR, grid=0.0, solar=1.0)
    result = optimizer().optimize((grid, solar), earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert result.selected.strategy.strategy_id == "solar"
    assert result.selected.estimated_cost == pytest.approx(0.5)


def test_battery_degradation_is_included_in_cost():
    battery = strategy("battery", NOW, source=EnergySource.BATTERY, grid=0.0, battery=1.0)
    evaluation = optimizer().evaluate(battery, earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert evaluation.estimated_cost == pytest.approx(0.8)


def test_candidate_after_deadline_is_infeasible():
    late = strategy("late", NOW + timedelta(hours=3))
    evaluation = optimizer().evaluate(late, earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert not evaluation.feasible
    assert "after the goal deadline" in evaluation.reasons[0]


def test_candidate_without_covering_tariff_is_infeasible():
    uncovered = strategy("uncovered", NOW + timedelta(hours=6))
    evaluation = optimizer().evaluate(uncovered, earliest_start=NOW, deadline=NOW + timedelta(hours=10), required_duration=timedelta(hours=2))
    assert not evaluation.feasible
    assert any("No tariff" in reason for reason in evaluation.reasons)


def test_short_candidate_is_infeasible():
    short = EnergyStrategy("short", EnergySource.GRID, 5.0, NOW, NOW + timedelta(hours=1))
    evaluation = optimizer().evaluate(short, earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert not evaluation.feasible


def test_no_feasible_candidate_returns_best_effort():
    late = strategy("late", NOW + timedelta(hours=3))
    result = optimizer().optimize((late,), earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert result.status is OptimizationStatus.BEST_EFFORT
    assert result.selected.strategy.strategy_id == "late"


def test_empty_candidates_return_no_candidate():
    result = optimizer().optimize((), earliest_start=NOW, deadline=DEADLINE, required_duration=timedelta(hours=2))
    assert result.status is OptimizationStatus.NO_CANDIDATE
    assert result.selected is None


def test_optimized_goal_plan_preserves_single_planner_path():
    goal = BodyReadyGoal("spa", 100.0, DEADLINE, metadata={"source": "dashboard"})
    goal_planner = GoalPlanner(build_default_planner(heating_rate_degrees_per_hour=5.0), 5.0)
    off_peak = strategy("off_peak", NOW + timedelta(hours=2))
    result = optimizer().create_optimized_plan(goal, kernel(), goal_planner, (off_peak,))
    assert result.optimized_goal.metadata["energy_strategy_id"] == "off_peak"
    assert result.optimized_goal.metadata["source"] == "dashboard"
    assert result.goal_plan.objective.objective_id == goal.goal_id
    assert result.goal_plan.objective.metadata["optimization_status"] == "optimized"


def test_invalid_energy_configuration_is_rejected():
    with pytest.raises(ValueError, match="sum to 1"):
        strategy("bad", NOW, grid=0.5, solar=0.2)
    with pytest.raises(ValueError, match="price_per_kwh"):
        TariffWindow(NOW, DEADLINE, -0.1)
    with pytest.raises(ValueError, match="solar_value"):
        EnergyCostOptimizer((), solar_value_per_kwh=-0.1)
