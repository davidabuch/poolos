"""Contract tests for the Epic 10.13E execution state machine."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_models import (
    ExecutionLifecycleStatus,
    ExecutionPlan,
    ExecutionStep,
)
from poolos.execution_state_machine import (
    ExecutionLifecycle,
    ExecutionStateMachine,
    ExecutionStateTransition,
    TransitionDisposition,
)
from poolos.integration import StartPump


NOW = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)


def plan() -> ExecutionPlan:
    operation = StartPump(equipment_id="main-pump", operation_id="op-1")
    return ExecutionPlan(
        plan_id="plan-1",
        proposal_id="proposal-1",
        authorization_id="authorization-1",
        decision_id="decision-1",
        context_id="context-1",
        created_at=NOW,
        steps=(
            ExecutionStep(
                step_id="step-1",
                sequence=1,
                operation=operation,
                expected_observations={"pump.main-pump.running": True},
            ),
        ),
    )


def apply(
    machine: ExecutionStateMachine,
    lifecycle: ExecutionLifecycle,
    status: ExecutionLifecycleStatus,
    offset: int,
):
    result = machine.transition(
        lifecycle,
        to_status=status,
        occurred_at=NOW + timedelta(seconds=offset),
        reason=f"Move to {status.value}.",
    )
    assert result.applied
    return result.lifecycle


def test_initialize_uses_plan_identity_without_side_effects() -> None:
    machine = ExecutionStateMachine()

    lifecycle = machine.initialize(plan())

    assert lifecycle.initial_status is ExecutionLifecycleStatus.AUTHORIZED
    assert lifecycle.status is ExecutionLifecycleStatus.AUTHORIZED
    assert lifecycle.initialized_at == NOW
    assert lifecycle.updated_at == NOW
    assert lifecycle.transitions == ()
    assert dict(lifecycle.metadata) == {
        "proposal_id": "proposal-1",
        "authorization_id": "authorization-1",
        "decision_id": "decision-1",
        "context_id": "context-1",
    }


def test_happy_path_requires_every_explicit_lifecycle_stage() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())

    statuses = (
        ExecutionLifecycleStatus.PLANNED,
        ExecutionLifecycleStatus.EXECUTING,
        ExecutionLifecycleStatus.DELIVERING,
        ExecutionLifecycleStatus.DELIVERED,
        ExecutionLifecycleStatus.VERIFYING,
        ExecutionLifecycleStatus.VERIFIED,
        ExecutionLifecycleStatus.COMPLETED,
    )
    for offset, status in enumerate(statuses, start=1):
        lifecycle = apply(machine, lifecycle, status, offset)

    assert lifecycle.status is ExecutionLifecycleStatus.COMPLETED
    assert lifecycle.terminal
    assert tuple(t.to_status for t in lifecycle.transitions) == statuses


def test_delivery_can_complete_without_verification_stage() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    for offset, status in enumerate(
        (
            ExecutionLifecycleStatus.PLANNED,
            ExecutionLifecycleStatus.EXECUTING,
            ExecutionLifecycleStatus.DELIVERING,
            ExecutionLifecycleStatus.DELIVERED,
            ExecutionLifecycleStatus.VERIFIED,
            ExecutionLifecycleStatus.COMPLETED,
        ),
        start=1,
    ):
        lifecycle = apply(machine, lifecycle, status, offset)

    assert lifecycle.status is ExecutionLifecycleStatus.COMPLETED


def test_illegal_transition_is_rejected_without_mutating_lifecycle() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())

    result = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.DELIVERED,
        occurred_at=NOW + timedelta(seconds=1),
        reason="Attempt to skip required stages.",
    )

    assert result.disposition is TransitionDisposition.REJECTED
    assert result.lifecycle is lifecycle
    assert result.transition is None
    assert result.rejection_reason == "illegal_transition:authorized->delivered"


def test_same_status_is_rejected() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())

    result = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.AUTHORIZED,
        occurred_at=NOW,
        reason="Duplicate update.",
    )

    assert not result.applied
    assert result.rejection_reason == "status_unchanged"


def test_terminal_states_never_resume() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    lifecycle = apply(machine, lifecycle, ExecutionLifecycleStatus.REJECTED, 1)

    result = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.AUTHORIZED,
        occurred_at=NOW + timedelta(seconds=2),
        reason="Unsafe resume attempt.",
    )

    assert lifecycle.terminal
    assert not result.applied
    assert result.rejection_reason == "terminal_state_cannot_transition"


@pytest.mark.parametrize(
    "terminal_status",
    [
        ExecutionLifecycleStatus.FAILED,
        ExecutionLifecycleStatus.TIMED_OUT,
        ExecutionLifecycleStatus.ABORTED,
        ExecutionLifecycleStatus.SUPERSEDED,
    ],
)
def test_execution_can_enter_failure_terminal_states(
    terminal_status: ExecutionLifecycleStatus,
) -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    lifecycle = apply(machine, lifecycle, ExecutionLifecycleStatus.PLANNED, 1)
    lifecycle = apply(machine, lifecycle, ExecutionLifecycleStatus.EXECUTING, 2)

    lifecycle = apply(machine, lifecycle, terminal_status, 3)

    assert lifecycle.status is terminal_status
    assert lifecycle.terminal


def test_transition_time_cannot_move_backward() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    lifecycle = apply(machine, lifecycle, ExecutionLifecycleStatus.PLANNED, 5)

    result = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.EXECUTING,
        occurred_at=NOW + timedelta(seconds=4),
        reason="Stale transition.",
    )

    assert not result.applied
    assert result.rejection_reason == "transition_time_precedes_current_state"


def test_transition_identifier_is_deterministic() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    kwargs = {
        "to_status": ExecutionLifecycleStatus.PLANNED,
        "occurred_at": NOW + timedelta(seconds=1),
        "reason": "Plan accepted.",
        "actor": "test",
        "metadata": {"source": "unit-test"},
    }

    first = machine.transition(lifecycle, **kwargs)
    second = machine.transition(lifecycle, **kwargs)

    assert first.transition is not None
    assert second.transition is not None
    assert first.transition.transition_id == second.transition.transition_id


def test_transition_artifacts_and_collections_are_immutable() -> None:
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan())
    metadata = {"source": "test"}

    result = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.PLANNED,
        occurred_at=NOW + timedelta(seconds=1),
        reason="Plan constructed.",
        metadata=metadata,
    )
    metadata["changed"] = "yes"

    assert result.transition is not None
    assert dict(result.transition.metadata) == {"source": "test"}
    with pytest.raises(FrozenInstanceError):
        result.transition.reason = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.lifecycle.metadata["new"] = "value"  # type: ignore[index]


def test_lifecycle_rejects_noncontiguous_transition_history() -> None:
    transition = ExecutionStateTransition(
        transition_id="transition-1",
        plan_id="plan-1",
        from_status=ExecutionLifecycleStatus.PLANNED,
        to_status=ExecutionLifecycleStatus.EXECUTING,
        occurred_at=NOW + timedelta(seconds=1),
        reason="Invalid first transition.",
    )

    with pytest.raises(ValueError, match="status-contiguous"):
        ExecutionLifecycle(
            plan_id="plan-1",
            initial_status=ExecutionLifecycleStatus.AUTHORIZED,
            status=ExecutionLifecycleStatus.EXECUTING,
            initialized_at=NOW,
            updated_at=NOW + timedelta(seconds=1),
            transitions=(transition,),
        )


def test_state_machine_has_no_delivery_collaborator() -> None:
    machine = ExecutionStateMachine()

    assert not hasattr(machine, "gateway")
    assert not hasattr(machine, "endpoint")
    assert not hasattr(machine, "transport")
    assert not hasattr(machine, "home_assistant")
