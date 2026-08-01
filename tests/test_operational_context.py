from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from poolos.execution_models import ExecutionLifecycleStatus
from poolos.operational_context import (
    ActivePlanSummary,
    OperationalContext,
    OperationalContextFactory,
    OperationalExecutionState,
    OperationalMode,
    OperationalSafetyState,
    PendingOperationalAction,
    ReevaluationState,
)

NOW = datetime(2026, 8, 1, 19, 0, tzinfo=UTC)


def _plan(
    *,
    status: ExecutionLifecycleStatus = ExecutionLifecycleStatus.EXECUTING,
) -> ActivePlanSummary:
    return ActivePlanSummary(
        plan_id="plan-1",
        lifecycle_state=status,
        current_step_id="step-1" if status is ExecutionLifecycleStatus.EXECUTING else None,
        remaining_steps=2,
        created_at=NOW,
    )


def test_active_plan_summary_is_minimal_and_immutable() -> None:
    plan = _plan()

    assert plan.plan_id == "plan-1"
    assert plan.current_step_id == "step-1"
    assert plan.remaining_steps == 2
    with pytest.raises(FrozenInstanceError):
        plan.remaining_steps = 1  # type: ignore[misc]


def test_active_plan_rejects_terminal_lifecycle() -> None:
    with pytest.raises(ValueError, match="active lifecycle state"):
        _plan(status=ExecutionLifecycleStatus.COMPLETED)


def test_executing_plan_requires_current_step() -> None:
    with pytest.raises(ValueError, match="requires current_step_id"):
        ActivePlanSummary(
            plan_id="plan-1",
            lifecycle_state=ExecutionLifecycleStatus.EXECUTING,
            current_step_id=None,
            remaining_steps=1,
            created_at=NOW,
        )


def test_factory_creates_normal_idle_context() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
    )

    assert context.operational_mode is OperationalMode.NORMAL
    assert context.execution_state is OperationalExecutionState.IDLE
    assert context.active_plan is None
    assert context.diagnostics["active_plan_id"] == "none"


def test_factory_derives_waiting_mode_from_scheduled_reevaluation() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        reevaluation_state=ReevaluationState.SCHEDULED,
    )

    assert context.operational_mode is OperationalMode.WAITING


def test_factory_derives_manual_override_mode() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        manual_override=True,
    )

    assert context.operational_mode is OperationalMode.MANUAL_OVERRIDE


def test_factory_derives_blocked_mode_with_reasons() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        blocked_reasons=("ownership unavailable",),
    )

    assert context.operational_mode is OperationalMode.BLOCKED
    assert context.blocked_reasons == ("ownership unavailable",)


@pytest.mark.parametrize(
    "safety_state",
    [OperationalSafetyState.FAULTED, OperationalSafetyState.LOCKED_OUT],
)
def test_factory_derives_safe_mode_from_serious_safety_state(
    safety_state: OperationalSafetyState,
) -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        safety_state=safety_state,
    )

    assert context.operational_mode is OperationalMode.SAFE_MODE


def test_safe_mode_takes_priority_over_manual_override_and_blockers() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        safety_state=OperationalSafetyState.LOCKED_OUT,
        manual_override=True,
        blocked_reasons=("operator lockout",),
    )

    assert context.operational_mode is OperationalMode.SAFE_MODE
    assert context.blocked_reasons == ("operator lockout",)


def test_context_accepts_executing_active_plan() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        active_plan=_plan(),
        execution_state=OperationalExecutionState.EXECUTING,
    )

    assert context.active_plan is not None
    assert context.active_plan.plan_id == "plan-1"


def test_context_rejects_execution_without_active_plan() -> None:
    with pytest.raises(ValueError, match="requires active_plan"):
        OperationalContextFactory().create(
            evaluation_id="evaluation-1",
            captured_at=NOW,
            execution_state=OperationalExecutionState.EXECUTING,
        )


def test_context_rejects_inconsistent_executing_plan_summary() -> None:
    with pytest.raises(ValueError, match="executing or verifying"):
        OperationalContextFactory().create(
            evaluation_id="evaluation-1",
            captured_at=NOW,
            active_plan=_plan(),
            execution_state=OperationalExecutionState.IDLE,
        )


def test_pending_reevaluation_cannot_already_be_scheduled() -> None:
    with pytest.raises(ValueError, match="cannot already be scheduled"):
        OperationalContextFactory().create(
            evaluation_id="evaluation-1",
            captured_at=NOW,
            pending_action=PendingOperationalAction.SCHEDULING_REEVALUATION,
            reevaluation_state=ReevaluationState.SCHEDULED,
        )


def test_context_and_diagnostics_are_immutable() -> None:
    context = OperationalContextFactory().create(
        evaluation_id="evaluation-1",
        captured_at=NOW,
        diagnostics={"source": "test"},
    )

    with pytest.raises(FrozenInstanceError):
        context.operational_mode = OperationalMode.BLOCKED  # type: ignore[misc]
    with pytest.raises(TypeError):
        context.diagnostics["source"] = "changed"  # type: ignore[index]


def test_factory_is_deterministic() -> None:
    factory = OperationalContextFactory()
    kwargs = {
        "evaluation_id": "evaluation-1",
        "captured_at": NOW,
        "active_plan": _plan(),
        "execution_state": OperationalExecutionState.VERIFYING,
        "safety_state": OperationalSafetyState.DEGRADED,
    }

    assert factory.create(**kwargs) == factory.create(**kwargs)


def test_direct_context_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationalContext(
            evaluation_id="evaluation-1",
            captured_at=datetime(2026, 8, 1, 12, 0),
            active_plan=None,
            pending_action=PendingOperationalAction.NONE,
            reevaluation_state=ReevaluationState.NONE,
            execution_state=OperationalExecutionState.IDLE,
            operational_mode=OperationalMode.NORMAL,
            safety_state=OperationalSafetyState.NORMAL,
        )
