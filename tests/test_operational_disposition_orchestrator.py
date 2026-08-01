from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
    OperationalReasonCode,
)
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalDispositionOrchestrator,
    OperationalOrchestrationInstruction,
    OperationalTarget,
)


def _result(
    disposition: OperationalDisposition,
    *,
    decision_id: str | None = "decision-1",
    plan_id: str | None = None,
    reevaluation_hint: str | None = None,
) -> OperationalEvaluationResult:
    return OperationalEvaluationResult(
        disposition=disposition,
        reason_code=OperationalReasonCode.NO_ACTION_REQUIRED,
        reason="deterministic test reason",
        context_id="context-1",
        decision_id=decision_id,
        plan_id=plan_id,
        reevaluation_hint=reevaluation_hint,
        diagnostics={"source": "test"},
    )


@pytest.mark.parametrize(
    ("result", "action", "target"),
    [
        (
            _result(OperationalDisposition.WAIT),
            OperationalAction.NO_ACTION,
            OperationalTarget.NONE,
        ),
        (
            _result(
                OperationalDisposition.SCHEDULE_REEVALUATION,
                reevaluation_hint="after forecast refresh",
            ),
            OperationalAction.REQUEST_REEVALUATION,
            OperationalTarget.REEVALUATION_SCHEDULER,
        ),
        (
            _result(OperationalDisposition.SUBMIT_NEW_PLAN),
            OperationalAction.REQUEST_PROPOSAL,
            OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        ),
        (
            _result(OperationalDisposition.KEEP_EXISTING_PLAN, plan_id="plan-1"),
            OperationalAction.RETAIN_PLAN,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        (
            _result(OperationalDisposition.CANCEL_EXISTING_PLAN, plan_id="plan-1"),
            OperationalAction.REQUEST_PLAN_CANCELLATION,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        (
            _result(OperationalDisposition.REPLACE_EXISTING_PLAN, plan_id="plan-1"),
            OperationalAction.REQUEST_PLAN_REPLACEMENT,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        (
            _result(OperationalDisposition.BLOCK),
            OperationalAction.HALT,
            OperationalTarget.OPERATOR_REVIEW,
        ),
    ],
)
def test_orchestrator_maps_every_disposition_to_one_instruction(
    result: OperationalEvaluationResult,
    action: OperationalAction,
    target: OperationalTarget,
) -> None:
    instruction = OperationalDispositionOrchestrator().orchestrate(result)

    assert instruction.action is action
    assert instruction.target is target
    assert instruction.disposition is result.disposition
    assert instruction.context_id == result.context_id
    assert instruction.reason_code == result.reason_code.value
    assert instruction.reason == result.reason
    assert instruction.decision_id == result.decision_id
    assert instruction.plan_id == result.plan_id
    assert instruction.diagnostics["source"] == "test"
    assert instruction.diagnostics["operational_action"] == action.value
    assert instruction.diagnostics["operational_target"] == target.value


def test_reevaluation_hint_is_preserved_only_for_reevaluation() -> None:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        _result(
            OperationalDisposition.SCHEDULE_REEVALUATION,
            reevaluation_hint="at 15:00 UTC",
        )
    )

    assert instruction.reevaluation_hint == "at 15:00 UTC"


def test_instruction_and_diagnostics_are_immutable() -> None:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        _result(OperationalDisposition.WAIT)
    )

    with pytest.raises(FrozenInstanceError):
        instruction.reason = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        instruction.diagnostics["source"] = "changed"  # type: ignore[index]


def test_orchestration_is_deterministic() -> None:
    result = _result(OperationalDisposition.REPLACE_EXISTING_PLAN, plan_id="plan-1")
    orchestrator = OperationalDispositionOrchestrator()

    assert orchestrator.orchestrate(result) == orchestrator.orchestrate(result)


def test_proposal_instruction_rejects_missing_decision() -> None:
    with pytest.raises(ValueError, match="proposal instruction requires decision_id"):
        OperationalOrchestrationInstruction(
            action=OperationalAction.REQUEST_PROPOSAL,
            target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
            context_id="context-1",
            disposition=OperationalDisposition.SUBMIT_NEW_PLAN,
            reason_code="selected_without_plan",
            reason="proposal required",
        )


def test_plan_action_rejects_missing_plan() -> None:
    with pytest.raises(ValueError, match="retain_plan requires plan_id"):
        OperationalOrchestrationInstruction(
            action=OperationalAction.RETAIN_PLAN,
            target=OperationalTarget.EXECUTION_PLAN_BOUNDARY,
            context_id="context-1",
            disposition=OperationalDisposition.KEEP_EXISTING_PLAN,
            reason_code="existing_plan_matches_decision",
            reason="retain plan",
            decision_id="decision-1",
        )


def test_no_action_cannot_target_a_subsystem() -> None:
    with pytest.raises(ValueError, match="no-action instruction must target none"):
        OperationalOrchestrationInstruction(
            action=OperationalAction.NO_ACTION,
            target=OperationalTarget.OPERATOR_REVIEW,
            context_id="context-1",
            disposition=OperationalDisposition.WAIT,
            reason_code="no_action_required",
            reason="wait",
            decision_id="decision-1",
        )
