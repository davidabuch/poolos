from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionProposal,
)
from poolos.execution_plan_boundary import (
    ExecutionPlanBoundary,
    ExecutionPlanBoundaryResult,
)
from poolos.execution_plan_constructor import (
    ExecutionPlanConstructionReason,
    ExecutionPlanConstructionStatus,
    ExecutionPlanConstructor,
)
from poolos.execution_plans import (
    ExecutionPlanBuildRequest,
    ExecutionStepSpecification,
)
from poolos.execution_proposal_boundary import ExecutionProposalBoundary
from poolos.integration import PoolOperation, StartPump
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
)
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalTarget,
)

NOW = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)


def _operation() -> PoolOperation:
    return StartPump(
        operation_id="operation-filter-on",
        equipment_id="pool_filter_pump",
    )


def _plan_boundary_result() -> ExecutionPlanBoundaryResult:
    action = CanonicalOperationalAction(
        action_id="operational-action-a",
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        context_id="context-a",
        disposition=OperationalDisposition.SUBMIT_NEW_PLAN.value,
        reason_code="decision_changed",
        reason="A new plan is required.",
        decision_id="decision-a",
        correlation_id="correlation-a",
    )
    pipeline = OperationalActionPipeline().process(action)
    proposal_result = ExecutionProposalBoundary().evaluate(pipeline)
    return ExecutionPlanBoundary().evaluate(proposal_result)


def _build_request(
    *,
    authorized: bool = True,
    context_id: str = "context-a",
) -> ExecutionPlanBuildRequest:
    proposal = ExecutionProposal(
        proposal_id="execution-proposal-request-PLACEHOLDER",
        decision_id="decision-a",
        context_id=context_id,
        objective_id="objective-a",
        created_at=NOW,
        runtime_mode=RuntimeMode.SIMULATION,
        operations=(_operation(),),
        reason="Build the selected operation.",
        expected_final_state={"pool_filter": True},
        metadata={"source_proposal_request_id": "placeholder"},
    )
    disposition = (
        AuthorizationDisposition.AUTHORIZED
        if authorized
        else AuthorizationDisposition.REJECTED
    )
    authorization = ExecutionAuthorization(
        authorization_id="authorization-a",
        proposal_id=proposal.proposal_id,
        evaluated_at=NOW,
        disposition=disposition,
        reason="Authorized for deterministic construction." if authorized else "Rejected.",
        blocking_reasons=() if authorized else ("safety_block",),
    )
    return ExecutionPlanBuildRequest(
        proposal=proposal,
        authorization=authorization,
        step_specifications=(
            ExecutionStepSpecification(
                operation_id="operation-filter-on",
                expected_observations={"pool_filter": True},
            ),
        ),
    )


def _matching_build_request() -> ExecutionPlanBuildRequest:
    boundary_result = _plan_boundary_result()
    assert boundary_result.plan_request is not None
    base = _build_request()
    proposal = replace(
        base.proposal,
        proposal_id="proposal-a",
        metadata={
            "source_proposal_request_id": (
                boundary_result.plan_request.proposal_request_id
            )
        },
    )
    authorization = replace(base.authorization, proposal_id=proposal.proposal_id)
    return replace(base, proposal=proposal, authorization=authorization)


def test_constructs_canonical_plan_from_accepted_request() -> None:
    boundary_result = _plan_boundary_result()
    result = ExecutionPlanConstructor().construct(
        boundary_result,
        _matching_build_request(),
    )

    assert result.status is ExecutionPlanConstructionStatus.CONSTRUCTED
    assert result.reason is ExecutionPlanConstructionReason.PLAN_CONSTRUCTED
    assert result.plan is not None
    assert result.plan.decision_id == "decision-a"
    assert result.plan.context_id == "context-a"
    assert result.plan.steps[0].operation.operation_id == "operation-filter-on"


def test_construction_is_deterministic() -> None:
    boundary_result = _plan_boundary_result()
    request = _matching_build_request()

    first = ExecutionPlanConstructor().construct(boundary_result, request)
    second = ExecutionPlanConstructor().construct(boundary_result, request)

    assert first.construction_id == second.construction_id
    assert first.plan is not None and second.plan is not None
    assert first.plan.plan_id == second.plan.plan_id


def test_preserves_upstream_identity_and_provenance() -> None:
    boundary_result = _plan_boundary_result()
    result = ExecutionPlanConstructor().construct(
        boundary_result,
        _matching_build_request(),
    )

    assert result.plan is not None
    assert result.provenance["source_plan_boundary_result_id"] == boundary_result.result_id
    assert result.provenance["source_plan_request_id"] == boundary_result.plan_request.plan_request_id  # type: ignore[union-attr]
    assert result.provenance["execution_plan_id"] == result.plan.plan_id
    assert result.provenance["source_authorization_id"] == "authorization-a"


def test_rejects_nonaccepted_plan_boundary_result() -> None:
    accepted = _plan_boundary_result()
    from poolos.execution_plan_boundary import (
        ExecutionPlanBoundaryReason,
        ExecutionPlanBoundaryStatus,
    )

    rejected = replace(
        accepted,
        status=ExecutionPlanBoundaryStatus.REJECTED,
        reason=ExecutionPlanBoundaryReason.PROPOSAL_NOT_ACCEPTED,
        plan_request=None,
    )

    result = ExecutionPlanConstructor().construct(rejected, _matching_build_request())

    assert result.status is ExecutionPlanConstructionStatus.REJECTED
    assert result.reason is ExecutionPlanConstructionReason.PLAN_REQUEST_NOT_ACCEPTED
    assert result.plan is None


def test_rejects_build_request_identity_mismatch() -> None:
    result = ExecutionPlanConstructor().construct(
        _plan_boundary_result(),
        _build_request(context_id="different-context"),
    )

    assert result.reason is ExecutionPlanConstructionReason.BUILD_REQUEST_MISMATCH
    assert result.build_result is None
    assert result.plan is None


def test_preserves_builder_rejection_without_constructing_plan() -> None:
    boundary_result = _plan_boundary_result()
    request = _matching_build_request()
    rejected_authorization = replace(
        request.authorization,
        disposition=AuthorizationDisposition.REJECTED,
        reason="Rejected.",
        blocking_reasons=("safety_block",),
    )
    request = replace(request, authorization=rejected_authorization)

    result = ExecutionPlanConstructor().construct(boundary_result, request)

    assert result.reason is ExecutionPlanConstructionReason.BUILDER_REJECTED
    assert result.build_result is not None
    assert result.plan is None
    assert "authorization_not_authorized" in result.build_result.reasons


def test_result_and_provenance_are_immutable() -> None:
    result = ExecutionPlanConstructor().construct(
        _plan_boundary_result(),
        _matching_build_request(),
    )

    with pytest.raises(FrozenInstanceError):
        result.construction_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionPlanConstructor(boundary_name="")
