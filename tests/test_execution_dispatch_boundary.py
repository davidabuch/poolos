from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from poolos.execution_dispatch_boundary import (
    ExecutionDispatchBoundary,
    ExecutionDispatchBoundaryRequest,
    ExecutionDispatchDisposition,
    ExecutionDispatchReason,
)
from poolos.execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from poolos.execution_plan_authorization import ExecutionPlanAuthorizationResult
from poolos.execution_plan_scheduler import (
    ExecutionPlanScheduleDisposition,
    ExecutionPlanScheduleReason,
    ExecutionPlanScheduleResult,
    ScheduledExecutionPlan,
)
from poolos.integration import StartPump

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 19, 0, tzinfo=UTC)


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-a",
        proposal_id="proposal-a",
        authorization_id="build-authorization-a",
        decision_id="decision-a",
        context_id="context-a",
        created_at=NOW - timedelta(minutes=10),
        steps=(
            ExecutionStep(
                step_id="plan-a:step:1",
                sequence=1,
                operation=StartPump(
                    equipment_id="pump-main",
                    operation_id="operation-start-main",
                ),
                expected_observations={"pump_running": True},
            ),
        ),
        status=ExecutionLifecycleStatus.AUTHORIZED,
    )


def _authorization(plan: ExecutionPlan) -> ExecutionPlanAuthorizationResult:
    authorization = cast(
        ExecutionPlanAuthorizationResult,
        object.__new__(ExecutionPlanAuthorizationResult),
    )
    object.__setattr__(authorization, "authorization_id", "authorization-a")
    object.__setattr__(authorization, "plan", plan)
    return authorization


def _schedule_result(
    *,
    disposition: ExecutionPlanScheduleDisposition = ExecutionPlanScheduleDisposition.IMMEDIATE,
    execute_at: datetime = NOW,
) -> ExecutionPlanScheduleResult:
    plan = _plan()
    authorization = _authorization(plan)
    scheduled_plan = None
    if disposition in {
        ExecutionPlanScheduleDisposition.IMMEDIATE,
        ExecutionPlanScheduleDisposition.SCHEDULED,
    }:
        scheduled_plan = ScheduledExecutionPlan(
            schedule_id="schedule-a",
            authorization_id="authorization-a",
            plan=plan,
            execute_at=execute_at,
            disposition=disposition,
            correlation_id="correlation-a",
            provenance={"source_execution_plan_id": "plan-a"},
        )
    reason = {
        ExecutionPlanScheduleDisposition.IMMEDIATE: (
            ExecutionPlanScheduleReason.PLAN_READY_IMMEDIATELY
        ),
        ExecutionPlanScheduleDisposition.SCHEDULED: (
            ExecutionPlanScheduleReason.PLAN_SCHEDULED
        ),
        ExecutionPlanScheduleDisposition.DEFERRED: (
            ExecutionPlanScheduleReason.PLAN_DEFERRED
        ),
        ExecutionPlanScheduleDisposition.REJECTED: (
            ExecutionPlanScheduleReason.AUTHORIZATION_NOT_ACCEPTED
        ),
    }[disposition]
    return ExecutionPlanScheduleResult(
        result_id="schedule-result-a",
        disposition=disposition,
        reason=reason,
        evaluated_at=NOW - timedelta(minutes=1),
        authorization_result=authorization,
        scheduled_plan=scheduled_plan,
        deferral_reasons=("await_window",)
        if disposition is ExecutionPlanScheduleDisposition.DEFERRED
        else (),
        provenance={
            "execution_plan_schedule_id": "schedule-a" if scheduled_plan else "",
            "source_execution_plan_id": "plan-a",
        },
    )


def test_due_immediate_plan_produces_dispatch_request() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
            correlation_id="correlation-a",
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.READY
    assert result.reason is ExecutionDispatchReason.DISPATCH_REQUEST_READY
    assert result.dispatch_request is not None
    assert result.dispatch_request.plan.plan_id == "plan-a"
    assert result.dispatch_request.schedule_id == "schedule-a"


def test_future_scheduled_plan_is_deferred_until_due() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(
                disposition=ExecutionPlanScheduleDisposition.SCHEDULED,
                execute_at=NOW + timedelta(minutes=30),
            ),
            evaluated_at=NOW,
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.DEFERRED
    assert result.reason is ExecutionDispatchReason.DISPATCH_BEFORE_EXECUTION_TIME
    assert result.dispatch_request is None
    assert result.deferral_reasons == ("execution_time_not_reached",)


def test_due_scheduled_plan_produces_dispatch_request() -> None:
    execute_at = NOW + timedelta(minutes=30)
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(
                disposition=ExecutionPlanScheduleDisposition.SCHEDULED,
                execute_at=execute_at,
            ),
            evaluated_at=execute_at,
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.READY
    assert result.dispatch_request is not None
    assert result.dispatch_request.execute_at == execute_at


def test_explicit_deferral_produces_no_dispatch_request() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
            deferral_reasons=("transport_unavailable",),
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.DEFERRED
    assert result.reason is ExecutionDispatchReason.DISPATCH_DEFERRED
    assert result.dispatch_request is None


def test_explicit_cancellation_produces_no_dispatch_request() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
            cancellation_reasons=("operator_cancelled",),
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.CANCELLED
    assert result.reason is ExecutionDispatchReason.DISPATCH_CANCELLED
    assert result.dispatch_request is None


@pytest.mark.parametrize(
    "disposition",
    [
        ExecutionPlanScheduleDisposition.DEFERRED,
        ExecutionPlanScheduleDisposition.REJECTED,
    ],
)
def test_non_ready_schedule_results_are_rejected(disposition) -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(disposition=disposition),
            evaluated_at=NOW,
        )
    )

    assert result.disposition is ExecutionDispatchDisposition.REJECTED
    assert result.reason is ExecutionDispatchReason.SCHEDULE_NOT_READY


def test_dispatch_identity_is_deterministic() -> None:
    request = ExecutionDispatchBoundaryRequest(
        schedule_result=_schedule_result(),
        evaluated_at=NOW,
        correlation_id="correlation-a",
    )

    first = ExecutionDispatchBoundary().evaluate(request)
    second = ExecutionDispatchBoundary().evaluate(request)

    assert first.result_id == second.result_id
    assert first.dispatch_request is not None
    assert second.dispatch_request is not None
    assert first.dispatch_request.dispatch_request_id == (
        second.dispatch_request.dispatch_request_id
    )


def test_provenance_preserves_upstream_identities() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
            correlation_id="correlation-a",
        )
    )

    assert result.provenance["source_execution_plan_schedule_result_id"] == (
        "schedule-result-a"
    )
    assert result.provenance["source_execution_plan_schedule_id"] == "schedule-a"
    assert result.provenance["source_execution_plan_authorization_id"] == (
        "authorization-a"
    )
    assert result.provenance["source_execution_plan_id"] == "plan-a"
    assert result.provenance["source_decision_id"] == "decision-a"
    assert result.provenance["source_context_id"] == "context-a"
    assert result.provenance["source_correlation_id"] == "correlation-a"


def test_request_rejects_conflicting_hold_reasons() -> None:
    with pytest.raises(ValueError, match="cannot be deferred and cancelled"):
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
            deferral_reasons=("wait",),
            cancellation_reasons=("cancel",),
        )


def test_request_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=datetime(2026, 8, 5, 19, 0),
        )


def test_result_and_provenance_are_immutable() -> None:
    result = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=_schedule_result(),
            evaluated_at=NOW,
        )
    )

    with pytest.raises(FrozenInstanceError):
        result.evaluated_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        ExecutionDispatchBoundary(boundary_name="")
