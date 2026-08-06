from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from poolos.execution_proposal_boundary import (
    ExecutionProposalBoundary,
    ExecutionProposalBoundaryReason,
    ExecutionProposalBoundaryStatus,
)
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineResult,
)
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalOrchestrationInstruction,
    OperationalTarget,
)


def _instruction(
    *,
    action: OperationalAction = OperationalAction.REQUEST_PROPOSAL,
    target: OperationalTarget = OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
    decision_id: str | None = "decision-a",
    plan_id: str | None = None,
) -> OperationalOrchestrationInstruction:
    return OperationalOrchestrationInstruction(
        action=action,
        target=target,
        context_id="context-a",
        disposition=(
            OperationalDisposition.SUBMIT_NEW_PLAN
            if action is OperationalAction.REQUEST_PROPOSAL
            else OperationalDisposition.BLOCK
        ),
        reason_code="decision_ready",
        reason="A new execution proposal is required.",
        decision_id=decision_id,
        plan_id=plan_id,
        diagnostics={"source": "test"},
    )


def _pipeline_result(
    *,
    correlation_id: str | None = "correlation-a",
) -> OperationalActionPipelineResult:
    action = CanonicalOperationalAction.from_instruction(
        _instruction(), correlation_id=correlation_id
    )
    return OperationalActionPipeline().process(action)


def test_accepts_validated_request_proposal_action() -> None:
    pipeline = _pipeline_result()

    result = ExecutionProposalBoundary().evaluate(pipeline)

    assert result.status is ExecutionProposalBoundaryStatus.ACCEPTED
    assert result.reason is ExecutionProposalBoundaryReason.PROPOSAL_REQUEST_ACCEPTED
    assert result.proposal_request is not None
    assert result.proposal_request.source_action_id == pipeline.action.action_id
    assert result.proposal_request.context_id == "context-a"
    assert result.proposal_request.decision_id == "decision-a"
    assert result.proposal_request.correlation_id == "correlation-a"


def test_identity_is_deterministic_across_replay() -> None:
    boundary = ExecutionProposalBoundary()

    first = boundary.evaluate(_pipeline_result())
    second = boundary.evaluate(_pipeline_result())

    assert first.result_id == second.result_id
    assert first.proposal_request is not None
    assert second.proposal_request is not None
    assert (
        first.proposal_request.proposal_request_id
        == second.proposal_request.proposal_request_id
    )


def test_rejects_pipeline_rejection() -> None:
    accepted = _pipeline_result()
    rejected = OperationalActionPipeline().process(
        accepted.action,
        accepted_action_ids=(accepted.action.action_id,),
    )

    result = ExecutionProposalBoundary().evaluate(rejected)

    assert result.status is ExecutionProposalBoundaryStatus.REJECTED
    assert result.reason is ExecutionProposalBoundaryReason.PIPELINE_NOT_ACCEPTED
    assert result.proposal_request is None


def test_rejects_non_proposal_action() -> None:
    instruction = _instruction(
        action=OperationalAction.HALT,
        target=OperationalTarget.OPERATOR_REVIEW,
        decision_id=None,
    )
    action = CanonicalOperationalAction.from_instruction(instruction)
    pipeline = OperationalActionPipeline().process(action)

    result = ExecutionProposalBoundary().evaluate(pipeline)

    assert result.reason is ExecutionProposalBoundaryReason.UNSUPPORTED_ACTION
    assert result.proposal_request is None


def test_rejects_missing_decision_identity() -> None:
    action = CanonicalOperationalAction(
        action_id="action-a",
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        context_id="context-a",
        disposition=OperationalDisposition.SUBMIT_NEW_PLAN.value,
        reason_code="decision_ready",
        reason="Proposal required.",
        decision_id=None,
    )
    pipeline = OperationalActionPipeline().process(action)

    result = ExecutionProposalBoundary().evaluate(pipeline)

    assert result.reason is ExecutionProposalBoundaryReason.MISSING_DECISION_ID


def test_rejects_unexpected_existing_plan_identity() -> None:
    action = CanonicalOperationalAction(
        action_id="action-a",
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        context_id="context-a",
        disposition=OperationalDisposition.SUBMIT_NEW_PLAN.value,
        reason_code="decision_ready",
        reason="Proposal required.",
        decision_id="decision-a",
        plan_id="plan-existing",
    )
    pipeline = OperationalActionPipeline().process(action)

    result = ExecutionProposalBoundary().evaluate(pipeline)

    assert result.reason is ExecutionProposalBoundaryReason.UNEXPECTED_PLAN_ID


def test_rejects_inconsistent_pipeline_boundary_evidence() -> None:
    pipeline = _pipeline_result()
    invalid = replace(pipeline, boundary_name="wrong_boundary")

    result = ExecutionProposalBoundary().evaluate(invalid)

    assert result.reason is ExecutionProposalBoundaryReason.PIPELINE_EVIDENCE_INVALID


def test_result_and_request_are_immutable() -> None:
    result = ExecutionProposalBoundary().evaluate(_pipeline_result())
    assert result.proposal_request is not None

    with pytest.raises(FrozenInstanceError):
        result.result_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.proposal_request.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionProposalBoundary(boundary_name="")


def test_boundary_creates_no_execution_plan_or_command_evidence() -> None:
    result = ExecutionProposalBoundary().evaluate(_pipeline_result())

    assert result.proposal_request is not None
    assert "execution_plan" not in result.provenance
    assert "command" not in result.provenance
    assert result.proposal_request.provenance["source_decision_id"] == "decision-a"
