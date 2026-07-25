from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.exceptions import DuplicateScheduledPlanError
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
from poolos.scheduling import ScheduledPlanStatus, ScheduledStepStatus, Scheduler
from poolos.state import EquipmentState

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def kernel_with_spa() -> PoolKernel:
    kernel = PoolKernel(clock=FixedClock(NOW))
    kernel.bodies.register(Body("spa", "Spa", BodyType.SPA))
    kernel.equipment.register(Equipment("pump", "Pump", EquipmentType.PUMP, frozenset({Capability.CIRCULATION}), body=BodyType.SPA))
    kernel.equipment.register(Equipment("heater", "Heater", EquipmentType.HEATER, frozenset({Capability.HEATING}), body=BodyType.SPA))
    kernel.update_body_state("spa", BodyState(BodyType.SPA, TemperatureState(90.0, 100.0, False), False, False))
    kernel.update_equipment_state("pump", EquipmentState(available=True))
    kernel.update_equipment_state("heater", EquipmentState(available=True))
    return kernel


def planned(kernel: PoolKernel) -> Plan:
    objective = PlanObjective(
        ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        "spa",
        100.0,
        NOW,
        NOW + timedelta(hours=3),
        maintain_until=NOW + timedelta(hours=5),
    )
    return build_default_planner(heating_rate_degrees_per_hour=5.0).create_plan(objective, kernel)


def test_scheduler_enforces_time_dependencies_and_conditions():
    kernel = kernel_with_spa()
    plan = planned(kernel)
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    assert scheduler.tick(plan.plan_id, kernel).ready_steps == ()

    kernel.clock.current = NOW + timedelta(hours=1)
    first = scheduler.tick(plan.plan_id, kernel)
    assert [step.sequence for step in first.ready_steps] == [1]
    scheduler.mark_submitted(plan.plan_id, plan.steps[0].step_id, kernel)

    kernel.update_body_state("spa", BodyState(BodyType.SPA, TemperatureState(90.0, 100.0, False), True, False))
    second = scheduler.tick(plan.plan_id, kernel)
    assert scheduler.get(plan.plan_id).steps[plan.steps[0].step_id].status is ScheduledStepStatus.COMPLETED
    assert [step.sequence for step in second.ready_steps] == [2]


def test_completion_condition_skips_already_satisfied_step():
    kernel = kernel_with_spa()
    plan = planned(kernel)
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    kernel.clock.current = plan.steps[0].earliest_eligible
    kernel.update_body_state("spa", BodyState(BodyType.SPA, TemperatureState(90.0, 100.0, False), True, False))
    result = scheduler.tick(plan.plan_id, kernel)
    assert scheduler.get(plan.plan_id).steps[plan.steps[0].step_id].status is ScheduledStepStatus.SKIPPED
    assert [step.sequence for step in result.ready_steps] == [2]


def test_expired_replan_step_requests_replanning():
    kernel = kernel_with_spa()
    plan = planned(kernel)
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    kernel.clock.current = plan.steps[0].latest_eligible + timedelta(seconds=1)
    result = scheduler.tick(plan.plan_id, kernel)
    assert result.plan_status is ScheduledPlanStatus.NEEDS_REPLAN
    assert scheduler.get(plan.plan_id).steps[plan.steps[0].step_id].status is ScheduledStepStatus.EXPIRED


def test_snapshot_round_trip_restores_progress():
    kernel = kernel_with_spa()
    plan = planned(kernel)
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    kernel.clock.current = plan.steps[0].earliest_eligible
    scheduler.tick(plan.plan_id, kernel)
    scheduler.mark_submitted(plan.plan_id, plan.steps[0].step_id, kernel)
    snapshot = scheduler.snapshot(plan.plan_id)

    restored = Scheduler()
    runtime = restored.restore(plan, snapshot)
    assert runtime.steps[plan.steps[0].step_id].status is ScheduledStepStatus.SUBMITTED
    assert restored.snapshot(plan.plan_id) == snapshot


def test_failure_behavior_controls_plan_status():
    from poolos.commands import Command, CommandAction

    kernel = kernel_with_spa()
    now = kernel.clock.now()
    step = PlanStep(
        1,
        now,
        now + timedelta(minutes=5),
        (Command("pump", CommandAction.START, issued_at=now),),
        failure_behavior=FailureBehavior.STOP_PLAN,
    )
    plan = Plan("objective", now, now, now + timedelta(minutes=5), PlanStatus.DRAFT, (step,))
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    scheduler.tick(plan.plan_id, kernel)
    scheduler.mark_failed(plan.plan_id, step.step_id, kernel, detail="adapter failed")
    assert scheduler.get(plan.plan_id).status is ScheduledPlanStatus.FAILED


def test_cancel_and_duplicate_activation_are_explicit():
    kernel = kernel_with_spa()
    plan = planned(kernel)
    scheduler = Scheduler()
    scheduler.activate(plan, kernel)
    with pytest.raises(DuplicateScheduledPlanError):
        scheduler.activate(plan, kernel)
    cancelled = scheduler.cancel(plan.plan_id, kernel, reason="user cancelled")
    assert cancelled.status is ScheduledPlanStatus.CANCELLED
    assert all(item.status is ScheduledStepStatus.CANCELLED for item in cancelled.steps.values())
