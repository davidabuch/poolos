from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.execution_plan_boundary import (
    ExecutionPlanBoundary,
    ExecutionPlanBoundaryReason,
    ExecutionPlanBoundaryStatus,
    ExecutionPlanRequest,
)
from poolos.execution_proposal_boundary import (
    ExecutionProposalBoundary,
    ExecutionProposalBoundaryReason,
    ExecutionProposalBoundaryStatus,
)
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
)
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalTarget,
)


def _action(*, correlation_id: str | None = "correlation-a") -> CanonicalOperationalAction:
    return CanonicalOperationalAction(
        action_id="operational-action-a",
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        context_id="context-a",
        disposition=OperationalDisposition.SUBMIT_NEW_PLAN.value,
        reason_code="new_plan_required",
        reason="No active plan satisfies the selected decision.",
        decision_id="decision-a",
        correlation_id=correlation_id,
    )


def _proposal_result(*, correlation_id: str | None = "correlation-a"):
    pipeline = OperationalActionPipeline().process(_action(correlation_id=correlation_id))
    return ExecutionProposalBoundary().evaluate(pipeline)


def test_accepts_valid_proposal_request() -> None:
    proposal = _proposal_result()
    result = ExecutionPlanBoundary().evaluate(proposal)

    assert proposal.status is ExecutionProposalBoundaryStatus.ACCEPTED
    assert result.status is ExecutionPlanBoundaryStatus.ACCEPTED
    assert result.reason is ExecutionPlanBoundaryReason.PLAN_REQUEST_ACCEPTED
    assert result.plan_request is not None
    assert result.plan_request.source_proposal_result_id == proposal.result_id
    assert (
        result.plan_request.proposal_request_id
        == proposal.proposal_request.proposal_request_id  # type: ignore[union-attr]
    )
    assert result.plan_request.source_action_id == "operational-action-a"
    assert result.plan_request.context_id == "context-a"
    assert result.plan_request.decision_id == "decision-a"


def test_identity_is_deterministic() -> None:
    first = ExecutionPlanBoundary().evaluate(_proposal_result())
    second = ExecutionPlanBoundary().evaluate(_proposal_result())

    assert first.result_id == second.result_id
    assert first.plan_request is not None
    assert second.plan_request is not None
    assert first.plan_request.plan_request_id == second.plan_request.plan_request_id


def test_correlation_identity_is_preserved() -> None:
    result = ExecutionPlanBoundary().evaluate(
        _proposal_result(correlation_id="correlation-z")
    )

    assert result.plan_request is not None
    assert result.plan_request.correlation_id == "correlation-z"
    assert result.provenance["source_correlation_id"] == "correlation-z"


def test_provenance_preserves_upstream_identities() -> None:
    proposal = _proposal_result()
    result = ExecutionPlanBoundary().evaluate(proposal)

    assert result.plan_request is not None
    assert result.provenance["source_proposal_result_id"] == proposal.result_id
    assert (
        result.plan_request.provenance["source_proposal_request_id"]
        == proposal.proposal_request.proposal_request_id  # type: ignore[union-attr]
    )
    assert result.plan_request.provenance["source_decision_id"] == "decision-a"


def test_rejects_rejected_proposal_result() -> None:
    wrong_action = CanonicalOperationalAction(
        action_id="operational-action-wait",
        action=OperationalAction.NO_ACTION,
        target=OperationalTarget.NONE,
        context_id="context-a",
        disposition=OperationalDisposition.WAIT.value,
        reason_code="wait",
        reason="No action is required.",
    )
    pipeline = OperationalActionPipeline().process(wrong_action)
    proposal = ExecutionProposalBoundary().evaluate(pipeline)
    result = ExecutionPlanBoundary().evaluate(proposal)

    assert proposal.status is ExecutionProposalBoundaryStatus.REJECTED
    assert proposal.reason is ExecutionProposalBoundaryReason.UNSUPPORTED_ACTION
    assert result.status is ExecutionPlanBoundaryStatus.REJECTED
    assert result.reason is ExecutionPlanBoundaryReason.PROPOSAL_NOT_ACCEPTED
    assert result.plan_request is None


def test_result_and_request_are_immutable() -> None:
    result = ExecutionPlanBoundary().evaluate(_proposal_result())
    assert result.plan_request is not None

    with pytest.raises(FrozenInstanceError):
        result.result_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.plan_request.plan_request_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.plan_request.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionPlanBoundary(boundary_name="")


def test_plan_request_rejects_empty_required_identity() -> None:
    with pytest.raises(ValueError, match="plan_request_id"):
        ExecutionPlanRequest(
            plan_request_id="",
            source_proposal_result_id="proposal-result-a",
            proposal_request_id="proposal-request-a",
            source_action_id="action-a",
            context_id="context-a",
            decision_id="decision-a",
            reason_code="reason-a",
            reason="Reason.",
        )


def test_plan_request_rejects_empty_correlation_identity() -> None:
    with pytest.raises(ValueError, match="correlation_id"):
        ExecutionPlanRequest(
            plan_request_id="plan-request-a",
            source_proposal_result_id="proposal-result-a",
            proposal_request_id="proposal-request-a",
            source_action_id="action-a",
            context_id="context-a",
            decision_id="decision-a",
            correlation_id="",
            reason_code="reason-a",
            reason="Reason.",
        )


def test_boundary_creates_request_evidence_only() -> None:
    result = ExecutionPlanBoundary().evaluate(_proposal_result())

    assert result.plan_request is not None
    assert not hasattr(result, "execution_plan")
    assert not hasattr(result, "authorization")
    assert not hasattr(result, "delivery")
