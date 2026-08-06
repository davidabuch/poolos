from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest

from poolos.execution_dispatch_boundary import (
    ExecutionDispatchBoundaryResult,
    ExecutionDispatchDisposition,
    ExecutionDispatchReason,
    ExecutionDispatchRequest,
)
from poolos.execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from poolos.execution_plan_scheduler import ExecutionPlanScheduleResult
from poolos.integration import (
    StartPump,
    StopPump,
    TranslationResult,
    UnsupportedOperationError,
    VendorCommand,
)
from poolos.vendor_translation_boundary import (
    VendorTranslationBoundary,
    VendorTranslationDisposition,
    VendorTranslationReason,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 19, 0, tzinfo=UTC)


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-a",
        proposal_id="proposal-a",
        authorization_id="authorization-a",
        decision_id="decision-a",
        context_id="context-a",
        created_at=NOW,
        steps=(
            ExecutionStep(
                step_id="plan-a:step:1",
                sequence=1,
                operation=StartPump(
                    equipment_id="pump-main",
                    operation_id="operation-start",
                ),
                expected_observations={"pump_running": True},
            ),
            ExecutionStep(
                step_id="plan-a:step:2",
                sequence=2,
                operation=StopPump(
                    equipment_id="pump-main",
                    operation_id="operation-stop",
                ),
                expected_observations={"pump_running": False},
            ),
        ),
        status=ExecutionLifecycleStatus.AUTHORIZED,
    )


def _dispatch_result(
    *,
    disposition: ExecutionDispatchDisposition = ExecutionDispatchDisposition.READY,
) -> ExecutionDispatchBoundaryResult:
    plan = _plan()
    schedule_result = cast(
        ExecutionPlanScheduleResult,
        object.__new__(ExecutionPlanScheduleResult),
    )
    scheduled_plan = SimpleNamespace()
    object.__setattr__(scheduled_plan, "plan", plan)
    object.__setattr__(scheduled_plan, "schedule_id", "schedule-a")
    object.__setattr__(scheduled_plan, "authorization_id", "authorization-a")
    object.__setattr__(schedule_result, "scheduled_plan", scheduled_plan)

    dispatch_request = None
    if disposition is ExecutionDispatchDisposition.READY:
        dispatch_request = ExecutionDispatchRequest(
            dispatch_request_id="dispatch-a",
            schedule_id="schedule-a",
            authorization_id="authorization-a",
            plan=plan,
            execute_at=NOW,
            prepared_at=NOW,
            correlation_id="correlation-a",
            provenance={"source_execution_plan_id": "plan-a"},
        )
    return ExecutionDispatchBoundaryResult(
        result_id="dispatch-result-a",
        disposition=disposition,
        reason=(
            ExecutionDispatchReason.DISPATCH_REQUEST_READY
            if disposition is ExecutionDispatchDisposition.READY
            else ExecutionDispatchReason.DISPATCH_DEFERRED
        ),
        evaluated_at=NOW,
        schedule_result=schedule_result,
        dispatch_request=dispatch_request,
        deferral_reasons=("not_ready",) if disposition is ExecutionDispatchDisposition.DEFERRED else (),
        provenance={"execution_dispatch_request_id": "dispatch-a" if dispatch_request else ""},
    )


def _translator(operation) -> TranslationResult:
    command = VendorCommand(
        vendor="test_vendor",
        operation=type(operation).__name__.lower(),
        target=operation.equipment_id,
        metadata={"operation_id": operation.operation_id},
    )
    return TranslationResult(commands=(command,), metadata={"translator": "test"})


def test_ready_dispatch_translates_all_steps_in_order() -> None:
    result = VendorTranslationBoundary().translate(_dispatch_result(), _translator)

    assert result.disposition is VendorTranslationDisposition.TRANSLATED
    assert result.reason is VendorTranslationReason.DISPATCH_TRANSLATED
    assert [step.sequence for step in result.translated_steps] == [1, 2]
    assert [step.operation_id for step in result.translated_steps] == [
        "operation-start",
        "operation-stop",
    ]
    assert [command.operation for command in result.commands] == [
        "startpump",
        "stoppump",
    ]


def test_translation_identity_is_deterministic() -> None:
    dispatch = _dispatch_result()
    first = VendorTranslationBoundary().translate(dispatch, _translator)
    second = VendorTranslationBoundary().translate(dispatch, _translator)

    assert first.result_id == second.result_id
    assert [step.translation_id for step in first.translated_steps] == [
        step.translation_id for step in second.translated_steps
    ]


def test_provenance_preserves_upstream_identities() -> None:
    result = VendorTranslationBoundary().translate(_dispatch_result(), _translator)

    assert result.provenance["source_execution_dispatch_request_id"] == "dispatch-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"
    assert result.provenance["source_proposal_id"] == "proposal-a"
    assert result.provenance["source_decision_id"] == "decision-a"
    assert result.provenance["source_context_id"] == "context-a"
    assert result.provenance["source_correlation_id"] == "correlation-a"
    assert result.provenance["translated_step_count"] == "2"
    assert result.provenance["translated_command_count"] == "2"


def test_non_ready_dispatch_is_rejected() -> None:
    result = VendorTranslationBoundary().translate(
        _dispatch_result(disposition=ExecutionDispatchDisposition.DEFERRED),
        _translator,
    )

    assert result.disposition is VendorTranslationDisposition.REJECTED
    assert result.reason is VendorTranslationReason.DISPATCH_NOT_READY
    assert result.translated_steps == ()


def test_integration_error_is_recorded_without_partial_translation() -> None:
    def translator(operation):
        if operation.operation_id == "operation-stop":
            raise UnsupportedOperationError("test_vendor", type(operation))
        return _translator(operation)

    result = VendorTranslationBoundary().translate(_dispatch_result(), translator)

    assert result.disposition is VendorTranslationDisposition.REJECTED
    assert result.reason is VendorTranslationReason.OPERATION_TRANSLATION_FAILED
    assert result.translated_steps == ()
    assert result.failure_step_id == "plan-a:step:2"
    assert result.failure_detail is not None
    assert "UnsupportedOperationError" in result.failure_detail


def test_empty_translation_result_is_rejected() -> None:
    result = VendorTranslationBoundary().translate(
        _dispatch_result(),
        lambda operation: TranslationResult(commands=()),
    )

    assert result.reason is VendorTranslationReason.EMPTY_TRANSLATION_RESULT
    assert result.failure_step_id == "plan-a:step:1"


def test_invalid_translation_return_is_rejected() -> None:
    result = VendorTranslationBoundary().translate(
        _dispatch_result(),
        cast(object, lambda operation: object()),
    )

    assert result.reason is VendorTranslationReason.TRANSLATION_RESULT_INVALID
    assert result.failure_detail == "translator_must_return_translation_result"


def test_result_and_provenance_are_immutable() -> None:
    result = VendorTranslationBoundary().translate(_dispatch_result(), _translator)

    with pytest.raises(FrozenInstanceError):
        result.result_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        VendorTranslationBoundary(boundary_name="")
