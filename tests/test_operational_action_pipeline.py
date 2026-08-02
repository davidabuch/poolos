from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
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


def _instruction(
    disposition: OperationalDisposition = OperationalDisposition.SUBMIT_NEW_PLAN,
) -> OperationalOrchestrationInstruction:
    result = OperationalEvaluationResult(
        disposition=disposition,
        reason_code=OperationalReasonCode.SELECTED_WITHOUT_PLAN,
        reason="A new proposal is required",
        context_id="context-1",
        decision_id="decision-1",
        plan_id=None,
        diagnostics={"source": "test"},
    )
    return OperationalDispositionOrchestrator().orchestrate(result)


def test_canonical_action_is_deterministic() -> None:
    instruction = _instruction()

    first = CanonicalOperationalAction.from_instruction(instruction)
    second = CanonicalOperationalAction.from_instruction(instruction)

    assert first == second
    assert first.action_id.startswith("operational-action-")
    assert first.target is OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY


def test_canonical_action_preserves_identity_and_correlation() -> None:
    action = CanonicalOperationalAction.from_instruction(
        _instruction(),
        correlation_id="cycle-1",
    )

    assert action.context_id == "context-1"
    assert action.decision_id == "decision-1"
    assert action.correlation_id == "cycle-1"
    assert action.diagnostics["source"] == "test"


def test_action_and_diagnostics_are_immutable() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    with pytest.raises(FrozenInstanceError):
        action.reason = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        action.diagnostics["source"] = "changed"  # type: ignore[index]


def test_pipeline_accepts_valid_route_without_invoking_target() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    result = OperationalActionPipeline().process(action)

    assert result.status is OperationalActionPipelineStatus.ACCEPTED
    assert result.reason is OperationalActionPipelineReason.ROUTE_ACCEPTED
    assert result.routed_target is OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY
    assert result.boundary_name == "execution_proposal_boundary"
    assert result.accepted_action_ids == (action.action_id,)


@pytest.mark.parametrize(
    ("disposition", "expected_action", "expected_target"),
    [
        (
            OperationalDisposition.SUBMIT_NEW_PLAN,
            OperationalAction.REQUEST_PROPOSAL,
            OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        ),
        (
            OperationalDisposition.BLOCK,
            OperationalAction.HALT,
            OperationalTarget.OPERATOR_REVIEW,
        ),
    ],
)
def test_pipeline_preserves_orchestrator_route(
    disposition: OperationalDisposition,
    expected_action: OperationalAction,
    expected_target: OperationalTarget,
) -> None:
    if disposition is OperationalDisposition.BLOCK:
        instruction = OperationalDispositionOrchestrator().orchestrate(
            OperationalEvaluationResult(
                disposition=disposition,
                reason_code=OperationalReasonCode.DECISION_BLOCKED,
                reason="Blocked",
                context_id="context-1",
                decision_id="decision-1",
            )
        )
    else:
        instruction = _instruction(disposition)
    action = CanonicalOperationalAction.from_instruction(instruction)

    result = OperationalActionPipeline().process(action)

    assert action.action is expected_action
    assert result.routed_target is expected_target


def test_no_action_is_validly_routed_to_none() -> None:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        OperationalEvaluationResult(
            disposition=OperationalDisposition.WAIT,
            reason_code=OperationalReasonCode.NO_ACTION_REQUIRED,
            reason="No action required",
            context_id="context-1",
            decision_id="decision-1",
        )
    )
    action = CanonicalOperationalAction.from_instruction(instruction)

    result = OperationalActionPipeline().process(action)

    assert result.status is OperationalActionPipelineStatus.ACCEPTED
    assert result.routed_target is OperationalTarget.NONE
    assert result.boundary_name == "none"


def test_pipeline_rejects_action_target_mismatch() -> None:
    valid = CanonicalOperationalAction.from_instruction(_instruction())
    invalid = CanonicalOperationalAction(
        action_id=valid.action_id,
        action=valid.action,
        target=OperationalTarget.OPERATOR_REVIEW,
        context_id=valid.context_id,
        disposition=valid.disposition,
        reason_code=valid.reason_code,
        reason=valid.reason,
        decision_id=valid.decision_id,
    )

    result = OperationalActionPipeline().process(invalid)

    assert result.status is OperationalActionPipelineStatus.REJECTED
    assert result.reason is OperationalActionPipelineReason.ACTION_TARGET_MISMATCH
    assert result.routed_target is OperationalTarget.NONE
    assert result.boundary_name is None
    assert result.accepted_action_ids == ()


def test_pipeline_rejects_duplicate_action_id() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())
    pipeline = OperationalActionPipeline()
    accepted = pipeline.process(action)

    duplicate = pipeline.process(
        action,
        accepted_action_ids=accepted.accepted_action_ids,
    )

    assert duplicate.status is OperationalActionPipelineStatus.REJECTED
    assert duplicate.reason is OperationalActionPipelineReason.DUPLICATE_ACTION_ID
    assert duplicate.accepted_action_ids == (action.action_id,)


def test_different_instruction_identity_produces_different_action_id() -> None:
    first = CanonicalOperationalAction.from_instruction(_instruction())
    second_instruction = OperationalDispositionOrchestrator().orchestrate(
        OperationalEvaluationResult(
            disposition=OperationalDisposition.SUBMIT_NEW_PLAN,
            reason_code=OperationalReasonCode.SELECTED_WITHOUT_PLAN,
            reason="A new proposal is required",
            context_id="context-2",
            decision_id="decision-1",
        )
    )
    second = CanonicalOperationalAction.from_instruction(second_instruction)

    assert first.action_id != second.action_id


def test_pipeline_result_and_diagnostics_are_immutable() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())
    result = OperationalActionPipeline().process(action)

    with pytest.raises(FrozenInstanceError):
        result.status = OperationalActionPipelineStatus.REJECTED  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.diagnostics["pipeline_status"] = "changed"  # type: ignore[index]


def test_result_rejects_duplicate_accepted_ids() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    with pytest.raises(ValueError, match="must be unique"):
        OperationalActionPipelineResult(
            status=OperationalActionPipelineStatus.ACCEPTED,
            reason=OperationalActionPipelineReason.ROUTE_ACCEPTED,
            action=action,
            routed_target=action.target,
            boundary_name="execution_proposal_boundary",
            accepted_action_ids=(action.action_id, action.action_id),
        )


def test_pipeline_result_preserves_registry_boundary_evidence() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    result = OperationalActionPipeline().process(action)

    assert result.boundary_name == "execution_proposal_boundary"
    assert result.diagnostics["boundary_name"] == "execution_proposal_boundary"
    assert result.diagnostics["registry_status"] == "found"
    assert result.diagnostics["registry_reason"] == "route_found"


def test_accepted_result_requires_boundary_name() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    with pytest.raises(ValueError, match="requires a boundary name"):
        OperationalActionPipelineResult(
            status=OperationalActionPipelineStatus.ACCEPTED,
            reason=OperationalActionPipelineReason.ROUTE_ACCEPTED,
            action=action,
            routed_target=action.target,
            boundary_name=None,
            accepted_action_ids=(action.action_id,),
        )


def test_rejected_result_cannot_identify_boundary() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())

    with pytest.raises(ValueError, match="must not identify a boundary name"):
        OperationalActionPipelineResult(
            status=OperationalActionPipelineStatus.REJECTED,
            reason=OperationalActionPipelineReason.UNSUPPORTED_ACTION,
            action=action,
            routed_target=OperationalTarget.NONE,
            boundary_name="execution_proposal_boundary",
            accepted_action_ids=(),
        )


def test_pipeline_is_deterministic() -> None:
    action = CanonicalOperationalAction.from_instruction(_instruction())
    pipeline = OperationalActionPipeline()

    assert pipeline.process(action) == pipeline.process(action)
