"""Tests for the canonical per-step execution lifecycle."""

from datetime import datetime, timedelta, timezone

from poolos.execution_step_state_machine import (
    ExecutionStepStateMachine,
    ExecutionStepStatus,
)

NOW = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)


def lifecycle():
    return ExecutionStepStateMachine().initialize(
        plan_id="plan-1", step_id="step-1", initialized_at=NOW
    )


def transition(machine, current, status, offset=0):
    return machine.transition(
        current,
        to_status=status,
        occurred_at=NOW + timedelta(seconds=offset),
        reason=f"move to {status.value}",
        actor="test",
    )


def test_successful_step_lifecycle() -> None:
    machine = ExecutionStepStateMachine()
    current = lifecycle()
    for index, status in enumerate(
        (
            ExecutionStepStatus.DELIVERING,
            ExecutionStepStatus.DELIVERED,
            ExecutionStepStatus.VERIFYING,
            ExecutionStepStatus.VERIFIED,
        ),
        start=1,
    ):
        result = transition(machine, current, status, index)
        assert result.applied
        current = result.lifecycle

    assert current.terminal
    assert current.status is ExecutionStepStatus.VERIFIED
    assert len(current.transitions) == 4


def test_plan_and_step_identity_are_preserved() -> None:
    current = lifecycle()

    assert current.plan_id == "plan-1"
    assert current.step_id == "step-1"


def test_illegal_skip_to_verified_is_rejected_without_mutation() -> None:
    machine = ExecutionStepStateMachine()
    current = lifecycle()

    result = transition(machine, current, ExecutionStepStatus.VERIFIED)

    assert not result.applied
    assert result.lifecycle is current
    assert result.rejection_reason == "illegal_step_transition:pending->verified"


def test_terminal_step_cannot_resume() -> None:
    machine = ExecutionStepStateMachine()
    current = lifecycle()
    current = transition(machine, current, ExecutionStepStatus.DELIVERING).lifecycle
    current = transition(machine, current, ExecutionStepStatus.FAILED).lifecycle

    result = transition(machine, current, ExecutionStepStatus.DELIVERING)

    assert not result.applied
    assert result.rejection_reason == "terminal_step_cannot_transition"


def test_backdated_transition_is_rejected() -> None:
    machine = ExecutionStepStateMachine()
    current = lifecycle()
    current = transition(
        machine, current, ExecutionStepStatus.DELIVERING, offset=2
    ).lifecycle

    result = transition(machine, current, ExecutionStepStatus.DELIVERED, offset=1)

    assert not result.applied
    assert result.rejection_reason == "transition_time_precedes_step_state"


def test_transition_ids_are_deterministic() -> None:
    machine = ExecutionStepStateMachine()

    first = transition(machine, lifecycle(), ExecutionStepStatus.DELIVERING)
    second = transition(machine, lifecycle(), ExecutionStepStatus.DELIVERING)

    assert first.transition is not None
    assert second.transition is not None
    assert first.transition.transition_id == second.transition.transition_id


def test_delivery_failure_and_timeout_are_terminal() -> None:
    machine = ExecutionStepStateMachine()
    for status in (ExecutionStepStatus.FAILED, ExecutionStepStatus.TIMED_OUT):
        current = transition(
            machine, lifecycle(), ExecutionStepStatus.DELIVERING
        ).lifecycle
        result = transition(machine, current, status)
        assert result.applied
        assert result.lifecycle.terminal
