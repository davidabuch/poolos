from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import cast

import pytest

from poolos.execution_models import ExecutionPlan
from poolos.execution_plan_authorization import (
    ExecutionPlanAuthorizationDisposition,
    ExecutionPlanAuthorizationReason,
    ExecutionPlanAuthorizationRequest,
    ExecutionPlanAuthorizer,
)
from poolos.execution_plan_constructor import (
    ExecutionPlanConstructionReason,
    ExecutionPlanConstructionResult,
    ExecutionPlanConstructionStatus,
)
from poolos.execution_plans import PlanBuildDisposition

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 23, 0, tzinfo=UTC)


def _construction(
    *,
    status: ExecutionPlanConstructionStatus = (
        ExecutionPlanConstructionStatus.CONSTRUCTED
    ),
) -> ExecutionPlanConstructionResult:
    plan = cast(
        ExecutionPlan,
        SimpleNamespace(
            plan_id="plan-a",
            proposal_id="proposal-a",
            authorization_id="proposal-auth-a",
            decision_id="decision-a",
            context_id="context-a",
        ),
    )
    plan_request = SimpleNamespace(
        decision_id="decision-a",
        context_id="context-a",
    )
    boundary_result = SimpleNamespace(plan_request=plan_request)
    constructed = status is ExecutionPlanConstructionStatus.CONSTRUCTED
    build_result = (
        SimpleNamespace(disposition=PlanBuildDisposition.BUILT, plan=plan)
        if constructed
        else None
    )
    return ExecutionPlanConstructionResult(
        construction_id="construction-a",
        status=status,
        reason=(
            ExecutionPlanConstructionReason.PLAN_CONSTRUCTED
            if constructed
            else ExecutionPlanConstructionReason.BUILDER_REJECTED
        ),
        plan_boundary_result=boundary_result,
        build_result=build_result,
        plan=plan if constructed else None,
        provenance={"source": "test"},
    )


def _request(**kwargs):
    return ExecutionPlanAuthorizationRequest(
        construction_result=kwargs.pop("construction_result", _construction()),
        evaluated_at=kwargs.pop("evaluated_at", NOW),
        **kwargs,
    )


def test_authorizes_constructed_plan_without_policy_reasons() -> None:
    result = ExecutionPlanAuthorizer().authorize(_request(correlation_id="corr-a"))

    assert result.disposition is ExecutionPlanAuthorizationDisposition.AUTHORIZED
    assert result.reason is ExecutionPlanAuthorizationReason.PLAN_AUTHORIZED
    assert result.plan is not None
    assert result.plan.plan_id == "plan-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"
    assert result.provenance["source_correlation_id"] == "corr-a"


def test_rejects_with_explicit_blocking_reasons() -> None:
    result = ExecutionPlanAuthorizer().authorize(
        _request(blocking_reasons=("safety_interlock", "manual_override"))
    )

    assert result.disposition is ExecutionPlanAuthorizationDisposition.REJECTED
    assert result.reason is ExecutionPlanAuthorizationReason.PLAN_REJECTED
    assert result.plan is None
    assert result.blocking_reasons == ("safety_interlock", "manual_override")


def test_defers_with_explicit_deferral_reasons() -> None:
    result = ExecutionPlanAuthorizer().authorize(
        _request(deferral_reasons=("awaiting_fresh_observation",))
    )

    assert result.disposition is ExecutionPlanAuthorizationDisposition.DEFERRED
    assert result.reason is ExecutionPlanAuthorizationReason.PLAN_DEFERRED
    assert result.plan is None
    assert result.deferral_reasons == ("awaiting_fresh_observation",)


def test_blocking_reasons_take_precedence_over_deferral_reasons() -> None:
    result = ExecutionPlanAuthorizer().authorize(
        _request(
            blocking_reasons=("unsafe",),
            deferral_reasons=("wait",),
        )
    )

    assert result.disposition is ExecutionPlanAuthorizationDisposition.REJECTED
    assert result.blocking_reasons == ("unsafe",)
    assert result.deferral_reasons == ()


def test_rejects_nonconstructed_result() -> None:
    result = ExecutionPlanAuthorizer().authorize(
        _request(construction_result=_construction(status=ExecutionPlanConstructionStatus.REJECTED))
    )

    assert result.reason is ExecutionPlanAuthorizationReason.CONSTRUCTION_NOT_ACCEPTED
    assert result.plan is None


def test_authorization_identity_is_deterministic_and_time_independent() -> None:
    authorizer = ExecutionPlanAuthorizer()
    first = authorizer.authorize(_request(evaluated_at=NOW))
    second = authorizer.authorize(
        _request(evaluated_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC))
    )

    assert first.authorization_id == second.authorization_id
    assert first.evaluated_at != second.evaluated_at


def test_policy_version_changes_identity() -> None:
    authorizer = ExecutionPlanAuthorizer()
    first = authorizer.authorize(_request(policy_version="1"))
    second = authorizer.authorize(_request(policy_version="2"))

    assert first.authorization_id != second.authorization_id


def test_request_rejects_naive_time_and_invalid_reason_sets() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(evaluated_at=datetime(2026, 8, 5, 23, 0))
    with pytest.raises(ValueError, match="unique"):
        _request(blocking_reasons=("x", "x"))
    with pytest.raises(ValueError, match="overlap"):
        _request(blocking_reasons=("x",), deferral_reasons=("x",))


def test_result_and_provenance_are_immutable() -> None:
    result = ExecutionPlanAuthorizer().authorize(_request())

    with pytest.raises(FrozenInstanceError):
        result.policy_version = "2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_result_invariants_reject_invalid_authorized_evidence() -> None:
    valid = ExecutionPlanAuthorizer().authorize(_request())

    with pytest.raises(ValueError, match="requires a plan"):
        replace(valid, plan=None)
    with pytest.raises(ValueError, match="cannot contain policy reasons"):
        replace(valid, blocking_reasons=("x",))


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionPlanAuthorizer(boundary_name="")
