"""Contract tests for the Epic 10.13F execution coordinator."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_coordinator import (
    CoordinationDisposition,
    CoordinationEventKind,
    ExecutionCoordinationSession,
    ExecutionCoordinator,
)
from poolos.execution_models import (
    ExecutionLifecycleStatus,
    ExecutionPlan,
    ExecutionStep,
)
from poolos.execution_state_machine import ExecutionStateMachine
from poolos.integration import SetPumpSpeed, StartPump


NOW = datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc)


def plan(
    *, status: ExecutionLifecycleStatus = ExecutionLifecycleStatus.AUTHORIZED
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-1",
        proposal_id="proposal-1",
        authorization_id="authorization-1",
        decision_id="decision-1",
        context_id="context-1",
        created_at=NOW,
        status=status,
        steps=(
            ExecutionStep(
                step_id="step-1",
                sequence=1,
                operation=StartPump(
                    equipment_id="main-pump",
                    operation_id="operation-1",
                ),
                expected_observations={"pump.main-pump.running": True},
            ),
            ExecutionStep(
                step_id="step-2",
                sequence=2,
                operation=SetPumpSpeed(
                    equipment_id="main-pump",
                    rpm=1800,
                    operation_id="operation-2",
                ),
                expected_observations={"pump.main-pump.speed_rpm": 1800},
            ),
        ),
    )


def admitted() -> tuple[
    ExecutionCoordinator, ExecutionPlan, ExecutionCoordinationSession
]:
    coordinator = ExecutionCoordinator()
    execution_plan = plan()
    result = coordinator.admit(
        execution_plan,
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert result.accepted
    return coordinator, execution_plan, result.session


def started() -> tuple[
    ExecutionCoordinator, ExecutionPlan, ExecutionCoordinationSession
]:
    coordinator, execution_plan, session = admitted()
    result = coordinator.start(
        execution_plan,
        session,
        occurred_at=NOW + timedelta(seconds=2),
    )
    assert result.accepted
    return coordinator, execution_plan, result.session


def test_admit_transitions_authorized_plan_to_planned() -> None:
    coordinator = ExecutionCoordinator()

    result = coordinator.admit(plan(), occurred_at=NOW + timedelta(seconds=1))

    assert result.disposition is CoordinationDisposition.ADVANCED
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.PLANNED
    assert result.session.current_step_sequence is None
    assert result.event is not None
    assert result.event.kind is CoordinationEventKind.PLAN_ADMITTED
    assert result.lifecycle_transition is not None
    assert result.lifecycle_transition.to_status is ExecutionLifecycleStatus.PLANNED


def test_pending_plan_is_not_admitted() -> None:
    coordinator = ExecutionCoordinator()

    result = coordinator.admit(
        plan(status=ExecutionLifecycleStatus.PENDING),
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert result.disposition is CoordinationDisposition.REJECTED
    assert result.rejection_reason == "plan_not_authorized"
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.PENDING


def test_start_transitions_to_executing_and_selects_only_first_step() -> None:
    coordinator, execution_plan, session = admitted()

    result = coordinator.start(
        execution_plan,
        session,
        occurred_at=NOW + timedelta(seconds=2),
    )

    assert result.disposition is CoordinationDisposition.READY
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.session.current_step_sequence == 1
    assert result.current_step is execution_plan.steps[0]
    assert result.event is not None
    assert result.event.kind is CoordinationEventKind.EXECUTION_STARTED


def test_current_step_is_read_only() -> None:
    coordinator, execution_plan, session = started()

    result = coordinator.current_step(execution_plan, session)

    assert result.disposition is CoordinationDisposition.READY
    assert result.current_step is execution_plan.steps[0]
    assert result.session is session
    assert result.event is None


def test_completion_signal_advances_exactly_one_step() -> None:
    coordinator, execution_plan, session = started()

    result = coordinator.acknowledge_step_completion(
        execution_plan,
        session,
        step_id="step-1",
        occurred_at=NOW + timedelta(seconds=3),
        reason="External execution component reported completion.",
    )

    assert result.disposition is CoordinationDisposition.READY
    assert result.current_step is execution_plan.steps[1]
    assert result.session.current_step_sequence == 2
    assert result.session.completed_step_ids == ("step-1",)
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.event is not None
    assert result.event.kind is CoordinationEventKind.STEP_COMPLETED


def test_final_completion_signal_stops_without_fabricating_delivery_state() -> None:
    coordinator, execution_plan, session = started()
    first = coordinator.acknowledge_step_completion(
        execution_plan,
        session,
        step_id="step-1",
        occurred_at=NOW + timedelta(seconds=3),
        reason="First step complete.",
    )

    result = coordinator.acknowledge_step_completion(
        execution_plan,
        first.session,
        step_id="step-2",
        occurred_at=NOW + timedelta(seconds=4),
        reason="Final step completion signal received.",
    )

    assert result.disposition is CoordinationDisposition.STOPPED
    assert result.session.stopped
    assert result.session.stop_reason == "plan_steps_exhausted"
    assert result.session.current_step_sequence is None
    assert result.session.completed_step_ids == ("step-1", "step-2")
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.event is not None
    assert result.event.kind is CoordinationEventKind.PLAN_STEPS_EXHAUSTED


def test_out_of_order_completion_is_rejected_without_mutation() -> None:
    coordinator, execution_plan, session = started()

    result = coordinator.acknowledge_step_completion(
        execution_plan,
        session,
        step_id="step-2",
        occurred_at=NOW + timedelta(seconds=3),
        reason="Incorrect completion order.",
    )

    assert result.disposition is CoordinationDisposition.REJECTED
    assert result.rejection_reason == "step_completion_out_of_order"
    assert result.session is session


def test_plan_session_mismatch_is_rejected() -> None:
    coordinator, _, session = started()
    other_plan = ExecutionPlan(
        plan_id="plan-2",
        proposal_id="proposal-2",
        authorization_id="authorization-2",
        decision_id="decision-2",
        context_id="context-2",
        created_at=NOW,
        steps=plan().steps,
    )

    result = coordinator.current_step(other_plan, session)

    assert result.disposition is CoordinationDisposition.REJECTED
    assert result.rejection_reason == "session_plan_mismatch"


def test_backdated_coordination_is_rejected() -> None:
    coordinator, execution_plan, session = started()

    result = coordinator.acknowledge_step_completion(
        execution_plan,
        session,
        step_id="step-1",
        occurred_at=NOW + timedelta(seconds=1),
        reason="Backdated signal.",
    )

    assert result.disposition is CoordinationDisposition.REJECTED
    assert result.rejection_reason == "coordination_time_precedes_current_state"


def test_stopped_session_cannot_advance() -> None:
    coordinator, execution_plan, session = started()
    first = coordinator.acknowledge_step_completion(
        execution_plan,
        session,
        step_id="step-1",
        occurred_at=NOW + timedelta(seconds=3),
        reason="First complete.",
    )
    stopped = coordinator.acknowledge_step_completion(
        execution_plan,
        first.session,
        step_id="step-2",
        occurred_at=NOW + timedelta(seconds=4),
        reason="Second complete.",
    )

    result = coordinator.acknowledge_step_completion(
        execution_plan,
        stopped.session,
        step_id="step-2",
        occurred_at=NOW + timedelta(seconds=5),
        reason="Unsafe duplicate signal.",
    )

    assert result.disposition is CoordinationDisposition.REJECTED
    assert result.rejection_reason == "session_already_stopped"


def test_coordination_event_identifier_is_deterministic() -> None:
    coordinator = ExecutionCoordinator()
    execution_plan = plan()

    first = coordinator.admit(
        execution_plan,
        occurred_at=NOW + timedelta(seconds=1),
        metadata={"source": "test"},
    )
    second = coordinator.admit(
        execution_plan,
        occurred_at=NOW + timedelta(seconds=1),
        metadata={"source": "test"},
    )

    assert first.event is not None
    assert second.event is not None
    assert first.event.event_id == second.event.event_id


def test_session_and_events_are_immutable() -> None:
    coordinator = ExecutionCoordinator()
    metadata = {"source": "test"}
    result = coordinator.admit(
        plan(),
        occurred_at=NOW + timedelta(seconds=1),
        metadata=metadata,
    )
    metadata["changed"] = "yes"

    assert result.event is not None
    assert dict(result.event.metadata) == {"source": "test"}
    with pytest.raises(FrozenInstanceError):
        result.session.stopped = True  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.event.metadata["new"] = "value"  # type: ignore[index]


def test_session_rejects_non_plan_completed_step() -> None:
    machine = ExecutionStateMachine()
    execution_plan = plan()
    lifecycle = machine.initialize(execution_plan)

    with pytest.raises(ValueError, match="completed step IDs"):
        ExecutionCoordinationSession(
            plan_id=execution_plan.plan_id,
            lifecycle=lifecycle,
            current_step_sequence=None,
            completed_step_ids=("",),
            stopped=False,
            stop_reason=None,
            initialized_at=NOW,
            updated_at=NOW,
        )


def test_coordinator_has_no_delivery_or_external_system_collaborator() -> None:
    coordinator = ExecutionCoordinator()

    assert not hasattr(coordinator, "gateway")
    assert not hasattr(coordinator, "endpoint")
    assert not hasattr(coordinator, "transport")
    assert not hasattr(coordinator, "home_assistant")
    assert not hasattr(coordinator, "pentair")
    assert not hasattr(coordinator, "verifier")
