from dataclasses import replace

import pytest

from poolos.decision_intelligence import DecisionOutcome
from poolos.decision_orchestrator import OrchestrationStatus
from poolos.execution_models import ExecutionLifecycleStatus
from poolos.operational_disposition import (
    OperationalDecisionSnapshot,
    OperationalDisposition,
    OperationalDispositionEngine,
    OperationalEvaluationRequest,
    OperationalPlanSummary,
    OperationalReasonCode,
)


def decision(
    outcome: DecisionOutcome,
    *,
    decision_id: str = "decision-new",
    next_change: str | None = None,
) -> OperationalDecisionSnapshot:
    return OperationalDecisionSnapshot(
        context_id="context-10-15a",
        orchestration_status=OrchestrationStatus.COMPLETED,
        decision_id=decision_id,
        outcome=outcome,
        selected_alternative_id=(
            "alternative-heater" if outcome is DecisionOutcome.SELECTED else None
        ),
        next_change=next_change,
        blockers=("Safety constraint failed",) if outcome is DecisionOutcome.BLOCKED else (),
    )


def plan(
    *,
    decision_id: str = "decision-old",
    cancellable: bool = True,
    replaceable: bool = True,
) -> OperationalPlanSummary:
    return OperationalPlanSummary(
        plan_id="execution-plan-1",
        decision_id=decision_id,
        status=ExecutionLifecycleStatus.EXECUTING,
        cancellable=cancellable,
        replaceable=replaceable,
    )


def evaluate(
    snapshot: OperationalDecisionSnapshot,
    current: OperationalPlanSummary | None = None,
):
    return OperationalDispositionEngine().evaluate(
        OperationalEvaluationRequest(snapshot, current)
    )


def test_blocked_context_blocks_without_an_accepted_decision():
    result = evaluate(
        OperationalDecisionSnapshot(
            context_id="context-blocked",
            orchestration_status=OrchestrationStatus.BLOCKED_CONTEXT,
            blockers=("telemetry stale",),
        )
    )

    assert result.disposition is OperationalDisposition.BLOCK
    assert result.reason_code is OperationalReasonCode.CONTEXT_BLOCKED
    assert result.decision_id is None


def test_blocked_decision_blocks_operational_action():
    result = evaluate(decision(DecisionOutcome.BLOCKED))

    assert result.disposition is OperationalDisposition.BLOCK
    assert result.reason_code is OperationalReasonCode.DECISION_BLOCKED


def test_selected_decision_without_plan_submits_new_plan():
    result = evaluate(decision(DecisionOutcome.SELECTED))

    assert result.disposition is OperationalDisposition.SUBMIT_NEW_PLAN
    assert result.reason_code is OperationalReasonCode.SELECTED_WITHOUT_PLAN
    assert result.plan_id is None


def test_matching_active_plan_is_kept():
    result = evaluate(
        decision(DecisionOutcome.SELECTED),
        plan(decision_id="decision-new"),
    )

    assert result.disposition is OperationalDisposition.KEEP_EXISTING_PLAN
    assert result.reason_code is OperationalReasonCode.EXISTING_PLAN_MATCHES_DECISION
    assert result.plan_id == "execution-plan-1"


def test_changed_selected_decision_replaces_replaceable_plan():
    result = evaluate(decision(DecisionOutcome.SELECTED), plan())

    assert result.disposition is OperationalDisposition.REPLACE_EXISTING_PLAN
    assert result.reason_code is OperationalReasonCode.SELECTED_DECISION_CHANGED


def test_changed_selected_decision_blocks_when_plan_is_not_replaceable():
    result = evaluate(
        decision(DecisionOutcome.SELECTED),
        plan(cancellable=False, replaceable=False),
    )

    assert result.disposition is OperationalDisposition.BLOCK
    assert result.reason_code is OperationalReasonCode.ACTIVE_PLAN_NOT_REPLACEABLE


@pytest.mark.parametrize("outcome", [DecisionOutcome.NO_ACTION, DecisionOutcome.DEFERRED])
def test_non_selected_decision_cancels_unneeded_active_plan(outcome):
    result = evaluate(decision(outcome), plan())

    assert result.disposition is OperationalDisposition.CANCEL_EXISTING_PLAN
    assert result.reason_code is OperationalReasonCode.ACTIVE_PLAN_NO_LONGER_REQUIRED


def test_non_selected_decision_blocks_when_active_plan_is_not_cancellable():
    result = evaluate(
        decision(DecisionOutcome.NO_ACTION),
        plan(cancellable=False, replaceable=False),
    )

    assert result.disposition is OperationalDisposition.BLOCK
    assert result.reason_code is OperationalReasonCode.ACTIVE_PLAN_NOT_CANCELLABLE


def test_future_change_schedules_reevaluation_without_plan():
    result = evaluate(
        decision(
            DecisionOutcome.DEFERRED,
            next_change="Reevaluate when off-peak pricing begins at 15:00",
        )
    )

    assert result.disposition is OperationalDisposition.SCHEDULE_REEVALUATION
    assert result.reason_code is OperationalReasonCode.REEVALUATION_HINT_AVAILABLE
    assert result.reevaluation_hint == "Reevaluate when off-peak pricing begins at 15:00"


def test_no_action_without_plan_or_hint_waits():
    result = evaluate(decision(DecisionOutcome.NO_ACTION))

    assert result.disposition is OperationalDisposition.WAIT
    assert result.reason_code is OperationalReasonCode.NO_ACTION_REQUIRED


def test_results_are_deterministic_and_diagnostics_are_immutable():
    request = OperationalEvaluationRequest(
        decision(DecisionOutcome.SELECTED),
        plan(decision_id="decision-new"),
    )

    first = OperationalDispositionEngine().evaluate(request)
    second = OperationalDispositionEngine().evaluate(request)

    assert first == second
    assert first.diagnostics["current_plan_status"] == "executing"
    with pytest.raises(TypeError):
        first.diagnostics["current_plan_status"] = "planned"  # type: ignore[index]


def test_plan_summary_rejects_terminal_status_and_inconsistent_capabilities():
    with pytest.raises(ValueError, match="active plan status"):
        replace(plan(), status=ExecutionLifecycleStatus.COMPLETED)
    with pytest.raises(ValueError, match="must also be cancellable"):
        plan(cancellable=False, replaceable=True)
