from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import inspect

import pytest

import poolos.reevaluation_scheduling as scheduling_module
from poolos.downstream_operational_action_adapter import (
    DownstreamOperationalActionOutcome,
    DownstreamOperationalActionReason,
    DownstreamOperationalActionReceipt,
    NonHardwareOperationalActionAdapter,
)
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineResult,
)
from poolos.operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
    OperationalReasonCode,
)
from poolos.operational_disposition_orchestrator import (
    OperationalDispositionOrchestrator,
)
from poolos.reevaluation_scheduling import (
    DeterministicReevaluationScheduler,
    ReevaluationScheduleOutcome,
    ReevaluationScheduleReason,
    ReevaluationScheduleRequest,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
SCHEDULED_FOR = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def _pipeline_result(
    disposition: OperationalDisposition,
) -> OperationalActionPipelineResult:
    is_reevaluation = disposition is OperationalDisposition.SCHEDULE_REEVALUATION
    evaluation = OperationalEvaluationResult(
        disposition=disposition,
        reason_code=(
            OperationalReasonCode.REEVALUATION_HINT_AVAILABLE
            if is_reevaluation
            else OperationalReasonCode.DECISION_BLOCKED
        ),
        reason="Reevaluation scheduling test",
        context_id="context-15i",
        decision_id="decision-15i",
        reevaluation_hint="forecast-window-15i" if is_reevaluation else None,
        diagnostics={"evaluation_source": "epic-10.15i-test"},
    )
    instruction = OperationalDispositionOrchestrator().orchestrate(evaluation)
    action = CanonicalOperationalAction.from_instruction(
        instruction,
        correlation_id="cycle-15i",
    )
    return OperationalActionPipeline().process(action)


def _deferred_receipt() -> DownstreamOperationalActionReceipt:
    return NonHardwareOperationalActionAdapter().adapt(
        _pipeline_result(OperationalDisposition.SCHEDULE_REEVALUATION)
    )


def _request(
    *,
    receipt: DownstreamOperationalActionReceipt | None = None,
    requested_at: datetime = REQUESTED_AT,
    scheduled_for: datetime = SCHEDULED_FOR,
) -> ReevaluationScheduleRequest:
    return ReevaluationScheduleRequest(
        receipt=receipt or _deferred_receipt(),
        requested_at=requested_at,
        scheduled_for=scheduled_for,
        provenance={"request_source": "test-suite"},
    )


def test_valid_deferred_receipt_is_scheduled() -> None:
    request = _request()
    scheduler = DeterministicReevaluationScheduler()

    result = scheduler.schedule(request, processed_at=REQUESTED_AT)

    assert result.outcome is ReevaluationScheduleOutcome.SCHEDULED
    assert result.reason is ReevaluationScheduleReason.SCHEDULE_ACCEPTED
    assert result.request is request
    assert result.scheduled_for == SCHEDULED_FOR
    assert scheduler.get(request.request_id) is result
    assert scheduler.records == (result,)


def test_non_deferred_receipt_is_rejected() -> None:
    operator_receipt = NonHardwareOperationalActionAdapter().adapt(
        _pipeline_result(OperationalDisposition.BLOCK)
    )
    request = _request(receipt=operator_receipt)

    result = DeterministicReevaluationScheduler().schedule(
        request,
        processed_at=REQUESTED_AT,
    )

    assert result.outcome is ReevaluationScheduleOutcome.REJECTED
    assert result.reason is ReevaluationScheduleReason.RECEIPT_NOT_DEFERRED


def test_deferred_receipt_with_wrong_route_is_rejected() -> None:
    operator_pipeline = _pipeline_result(OperationalDisposition.BLOCK)
    invalid_receipt = DownstreamOperationalActionReceipt(
        receipt_id="invalid-deferred-receipt",
        adapter_name="test.invalid_adapter",
        outcome=DownstreamOperationalActionOutcome.DEFERRED,
        reason=DownstreamOperationalActionReason.REEVALUATION_DEFERRED,
        pipeline_result=operator_pipeline,
    )

    result = DeterministicReevaluationScheduler().schedule(
        _request(receipt=invalid_receipt),
        processed_at=REQUESTED_AT,
    )

    assert result.outcome is ReevaluationScheduleOutcome.REJECTED
    assert result.reason is ReevaluationScheduleReason.RECEIPT_ROUTE_INVALID


def test_request_and_scheduled_result_are_deterministic() -> None:
    first_request = _request()
    second_request = _request()

    first = DeterministicReevaluationScheduler().schedule(
        first_request,
        processed_at=REQUESTED_AT,
    )
    second = DeterministicReevaluationScheduler().schedule(
        second_request,
        processed_at=REQUESTED_AT,
    )

    assert first_request == second_request
    assert first_request.request_id == second_request.request_id
    assert first == second
    assert first.result_id == second.result_id


def test_repeated_request_is_reported_as_duplicate() -> None:
    request = _request()
    scheduler = DeterministicReevaluationScheduler()
    scheduler.schedule(request, processed_at=REQUESTED_AT)

    duplicate = scheduler.schedule(
        request,
        processed_at=REQUESTED_AT + timedelta(minutes=1),
    )

    assert duplicate.outcome is ReevaluationScheduleOutcome.DUPLICATE
    assert duplicate.reason is ReevaluationScheduleReason.REQUEST_ALREADY_SCHEDULED
    assert scheduler.get(request.request_id).outcome is ReevaluationScheduleOutcome.SCHEDULED


def test_scheduled_request_can_be_cancelled_immutably() -> None:
    request = _request()
    scheduler = DeterministicReevaluationScheduler()
    scheduled = scheduler.schedule(request, processed_at=REQUESTED_AT)

    cancelled = scheduler.cancel(
        request,
        cancelled_at=REQUESTED_AT + timedelta(minutes=5),
        cancellation_reason="Forecast input was superseded",
    )

    assert scheduled.outcome is ReevaluationScheduleOutcome.SCHEDULED
    assert cancelled.outcome is ReevaluationScheduleOutcome.CANCELLED
    assert cancelled.reason is ReevaluationScheduleReason.CANCELLED_BY_REQUEST
    assert cancelled.cancellation_reason == "Forecast input was superseded"
    assert scheduler.get(request.request_id) is cancelled
    with pytest.raises(FrozenInstanceError):
        cancelled.cancellation_reason = "changed"  # type: ignore[misc]


def test_unknown_cancellation_and_repeat_cancellation_fail_closed() -> None:
    request = _request()
    scheduler = DeterministicReevaluationScheduler()

    missing = scheduler.cancel(
        request,
        cancelled_at=REQUESTED_AT,
        cancellation_reason="Not needed",
    )
    scheduler.schedule(request, processed_at=REQUESTED_AT)
    scheduler.cancel(
        request,
        cancelled_at=REQUESTED_AT + timedelta(minutes=1),
        cancellation_reason="Not needed",
    )
    repeated = scheduler.cancel(
        request,
        cancelled_at=REQUESTED_AT + timedelta(minutes=2),
        cancellation_reason="Still not needed",
    )

    assert missing.outcome is ReevaluationScheduleOutcome.REJECTED
    assert missing.reason is ReevaluationScheduleReason.REQUEST_NOT_SCHEDULED
    assert repeated.outcome is ReevaluationScheduleOutcome.DUPLICATE
    assert repeated.reason is ReevaluationScheduleReason.REQUEST_ALREADY_CANCELLED


def test_time_is_explicit_and_invalid_ordering_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(requested_at=datetime(2026, 8, 2, 8, 0))

    request = _request(scheduled_for=REQUESTED_AT - timedelta(seconds=1))
    result = DeterministicReevaluationScheduler().schedule(
        request,
        processed_at=REQUESTED_AT,
    )

    assert result.outcome is ReevaluationScheduleOutcome.REJECTED
    assert result.reason is ReevaluationScheduleReason.SCHEDULE_TIME_INVALID


def test_identity_and_provenance_are_preserved_and_immutable() -> None:
    request = _request()
    result = DeterministicReevaluationScheduler().schedule(
        request,
        processed_at=REQUESTED_AT,
    )

    assert request.action_id == request.receipt.action_id
    assert request.context_id == "context-15i"
    assert request.decision_id == "decision-15i"
    assert request.correlation_id == "cycle-15i"
    assert result.provenance["source_action_id"] == request.action_id
    assert result.provenance["source_context_id"] == request.context_id
    assert result.provenance["source_decision_id"] == request.decision_id
    assert result.provenance["source_correlation_id"] == request.correlation_id
    assert result.provenance["reevaluation_hint"] == "forecast-window-15i"
    assert result.provenance["request_source"] == "test-suite"
    with pytest.raises(TypeError):
        result.provenance["request_source"] = "changed"  # type: ignore[index]


def test_module_has_no_hardware_vendor_or_home_assistant_imports() -> None:
    tree = ast.parse(inspect.getsource(scheduling_module))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    prohibited = {"hal", "delivery", "homeassistant", "intellicenter", "vendors"}
    assert not any(
        component in prohibited
        for module_name in imported_modules
        for component in module_name.split(".")
    )
