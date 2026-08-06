from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from poolos.execution_plan_authorization import (
    ExecutionPlanAuthorizationDisposition,
    ExecutionPlanAuthorizationReason,
    ExecutionPlanAuthorizationResult,
)
from poolos.execution_plan_constructor import ExecutionPlanConstructionResult
from poolos.execution_plan_scheduler import (
    ExecutionPlanScheduleDisposition,
    ExecutionPlanScheduleReason,
    ExecutionPlanScheduleRequest,
    ExecutionPlanScheduler,
)
from poolos.integration import StartPump

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)


def _plan() -> ExecutionPlan:
    operation = StartPump(
        equipment_id="pump-main",
        operation_id="operation-start-main",
    )
    return ExecutionPlan(
        plan_id="plan-a",
        proposal_id="proposal-a",
        authorization_id="build-authorization-a",
        decision_id="decision-a",
        context_id="context-a",
        created_at=NOW - timedelta(minutes=5),
        steps=(
            ExecutionStep(
                step_id="plan-a:step:1",
                sequence=1,
                operation=operation,
                expected_observations={"pump_running": True},
            ),
        ),
        status=ExecutionLifecycleStatus.AUTHORIZED,
        metadata={"runtime_mode": RuntimeMode.SIMULATION.value},
    )


def _authorization(
    *,
    disposition: ExecutionPlanAuthorizationDisposition = (
        ExecutionPlanAuthorizationDisposition.AUTHORIZED
    ),
) -> ExecutionPlanAuthorizationResult:
    plan = _plan()
    construction = cast(ExecutionPlanConstructionResult, object.__new__(ExecutionPlanConstructionResult))
    object.__setattr__(construction, "plan", plan)
    exposed_plan = plan if disposition is ExecutionPlanAuthorizationDisposition.AUTHORIZED else None
    blockers = ("policy_block",) if disposition is ExecutionPlanAuthorizationDisposition.REJECTED else ()
    deferrals = ("await_window",) if disposition is ExecutionPlanAuthorizationDisposition.DEFERRED else ()
    reason = {
        ExecutionPlanAuthorizationDisposition.AUTHORIZED: ExecutionPlanAuthorizationReason.PLAN_AUTHORIZED,
        ExecutionPlanAuthorizationDisposition.DEFERRED: ExecutionPlanAuthorizationReason.PLAN_DEFERRED,
        ExecutionPlanAuthorizationDisposition.REJECTED: ExecutionPlanAuthorizationReason.PLAN_REJECTED,
    }[disposition]
    return ExecutionPlanAuthorizationResult(
        authorization_id="authorization-a",
        disposition=disposition,
        reason=reason,
        evaluated_at=NOW - timedelta(minutes=1),
        construction_result=construction,
        plan=exposed_plan,
        blocking_reasons=blockers,
        deferral_reasons=deferrals,
        correlation_id="correlation-a",
        provenance={"source_execution_plan_id": plan.plan_id},
    )


def test_authorized_plan_is_ready_immediately_by_default() -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            correlation_id="correlation-a",
        )
    )

    assert result.disposition is ExecutionPlanScheduleDisposition.IMMEDIATE
    assert result.reason is ExecutionPlanScheduleReason.PLAN_READY_IMMEDIATELY
    assert result.scheduled_plan is not None
    assert result.scheduled_plan.execute_at == NOW
    assert result.scheduled_plan.plan.plan_id == "plan-a"


def test_future_time_produces_scheduled_plan() -> None:
    execute_at = NOW + timedelta(minutes=30)
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            execute_at=execute_at,
        )
    )

    assert result.disposition is ExecutionPlanScheduleDisposition.SCHEDULED
    assert result.reason is ExecutionPlanScheduleReason.PLAN_SCHEDULED
    assert result.scheduled_plan is not None
    assert result.scheduled_plan.execute_at == execute_at


def test_explicit_deferral_produces_no_scheduled_plan() -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            deferral_reasons=("maintenance_window_closed",),
        )
    )

    assert result.disposition is ExecutionPlanScheduleDisposition.DEFERRED
    assert result.reason is ExecutionPlanScheduleReason.PLAN_DEFERRED
    assert result.scheduled_plan is None
    assert result.deferral_reasons == ("maintenance_window_closed",)


@pytest.mark.parametrize(
    "disposition",
    [
        ExecutionPlanAuthorizationDisposition.DEFERRED,
        ExecutionPlanAuthorizationDisposition.REJECTED,
    ],
)
def test_non_authorized_results_are_rejected(disposition) -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(disposition=disposition),
            evaluated_at=NOW,
        )
    )

    assert result.disposition is ExecutionPlanScheduleDisposition.REJECTED
    assert result.reason is ExecutionPlanScheduleReason.AUTHORIZATION_NOT_ACCEPTED
    assert result.scheduled_plan is None


def test_past_execution_time_is_rejected() -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            execute_at=NOW - timedelta(seconds=1),
        )
    )

    assert result.disposition is ExecutionPlanScheduleDisposition.REJECTED
    assert result.reason is ExecutionPlanScheduleReason.EXECUTION_TIME_IN_PAST


def test_schedule_identity_is_deterministic() -> None:
    request = ExecutionPlanScheduleRequest(
        authorization_result=_authorization(),
        evaluated_at=NOW,
        execute_at=NOW + timedelta(minutes=15),
        correlation_id="correlation-a",
    )

    first = ExecutionPlanScheduler().schedule(request)
    second = ExecutionPlanScheduler().schedule(request)

    assert first.result_id == second.result_id
    assert first.scheduled_plan is not None
    assert second.scheduled_plan is not None
    assert first.scheduled_plan.schedule_id == second.scheduled_plan.schedule_id


def test_provenance_preserves_upstream_identities() -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            correlation_id="correlation-a",
        )
    )

    assert result.provenance["source_execution_plan_authorization_id"] == "authorization-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"
    assert result.provenance["source_decision_id"] == "decision-a"
    assert result.provenance["source_context_id"] == "context-a"
    assert result.provenance["source_correlation_id"] == "correlation-a"


def test_request_rejects_naive_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=datetime(2026, 8, 5, 18, 0),
        )


def test_request_rejects_deferral_with_execution_time() -> None:
    with pytest.raises(ValueError, match="cannot define execute_at"):
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
            execute_at=NOW + timedelta(minutes=10),
            deferral_reasons=("not_ready",),
        )


def test_result_and_provenance_are_immutable() -> None:
    result = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=_authorization(),
            evaluated_at=NOW,
        )
    )

    with pytest.raises(FrozenInstanceError):
        result.evaluated_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionPlanScheduler(boundary_name="")
