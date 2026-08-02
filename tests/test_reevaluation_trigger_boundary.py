from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import inspect

import pytest

import poolos.reevaluation_trigger_boundary as trigger_module
from poolos.downstream_operational_action_adapter import (
    NonHardwareOperationalActionAdapter,
)
from poolos.evaluation_context import EvaluationTrigger
from poolos.evaluation_triggers import TriggerUrgency
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
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
    ReevaluationScheduleRequest,
    ReevaluationScheduleResult,
)
from poolos.reevaluation_trigger_boundary import (
    DueReevaluationTriggerBoundary,
    ReevaluationTriggerOutcome,
    ReevaluationTriggerReason,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


def _schedule_result(
    *,
    context_id: str = "context-15j",
    hint: str = "forecast-window-15j",
    requested_at: datetime = REQUESTED_AT,
    scheduled_for: datetime | None = None,
    scheduler: DeterministicReevaluationScheduler | None = None,
) -> ReevaluationScheduleResult:
    evaluation = OperationalEvaluationResult(
        disposition=OperationalDisposition.SCHEDULE_REEVALUATION,
        reason_code=OperationalReasonCode.REEVALUATION_HINT_AVAILABLE,
        reason="A future expected change requires reevaluation",
        context_id=context_id,
        decision_id=f"decision-{context_id}",
        reevaluation_hint=hint,
        diagnostics={"evaluation_source": "epic-10.15j-test"},
    )
    instruction = OperationalDispositionOrchestrator().orchestrate(evaluation)
    action = CanonicalOperationalAction.from_instruction(
        instruction,
        correlation_id=f"cycle-{context_id}",
    )
    pipeline_result = OperationalActionPipeline().process(action)
    receipt = NonHardwareOperationalActionAdapter().adapt(pipeline_result)
    request = ReevaluationScheduleRequest(
        receipt=receipt,
        requested_at=requested_at,
        scheduled_for=scheduled_for or requested_at + timedelta(hours=1),
        provenance={"request_source": "trigger-boundary-test"},
    )
    active_scheduler = scheduler or DeterministicReevaluationScheduler()
    return active_scheduler.schedule(
        request,
        processed_at=requested_at,
    )


def test_due_schedule_emits_expected_change_trigger_and_completion() -> None:
    scheduled = _schedule_result()
    as_of = scheduled.scheduled_for

    batch = DueReevaluationTriggerBoundary().evaluate((scheduled,), as_of=as_of)

    assert len(batch.results) == 1
    result = batch.results[0]
    assert result.outcome is ReevaluationTriggerOutcome.EMITTED
    assert result.reason is ReevaluationTriggerReason.TRIGGER_EMITTED
    assert result.trigger_request is not None
    assert result.trigger_request.trigger is EvaluationTrigger.EXPECTED_CHANGE_REACHED
    assert result.trigger_request.requested_at == as_of
    assert result.trigger_request.urgency is TriggerUrgency.NORMAL
    assert result.trigger_request.source == "poolos.due_reevaluation_trigger_boundary"
    assert "forecast-window-15j" in result.trigger_request.reason
    assert batch.completed_request_ids == (scheduled.request_id,)
    assert batch.trigger_requests == (result.trigger_request,)


def test_future_schedule_is_not_due_and_is_not_completed() -> None:
    scheduled = _schedule_result()

    batch = DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=scheduled.scheduled_for - timedelta(seconds=1),
    )

    result = batch.results[0]
    assert result.outcome is ReevaluationTriggerOutcome.NOT_DUE
    assert result.reason is ReevaluationTriggerReason.SCHEDULE_NOT_DUE
    assert result.trigger_request is None
    assert batch.completed_request_ids == ()


def test_cancelled_schedule_never_emits_a_trigger() -> None:
    scheduler = DeterministicReevaluationScheduler()
    scheduled = _schedule_result(scheduler=scheduler)
    cancelled = scheduler.cancel(
        scheduled.request,
        cancelled_at=scheduled.processed_at + timedelta(minutes=1),
        cancellation_reason="Expected change was superseded",
    )

    batch = DueReevaluationTriggerBoundary().evaluate(
        (cancelled,),
        as_of=scheduled.scheduled_for,
    )

    result = batch.results[0]
    assert result.outcome is ReevaluationTriggerOutcome.CANCELLED
    assert result.reason is ReevaluationTriggerReason.REQUEST_CANCELLED
    assert result.trigger_request is None
    assert batch.completed_request_ids == ()


def test_invalid_schedule_result_is_rejected() -> None:
    scheduler = DeterministicReevaluationScheduler()
    scheduled = _schedule_result(scheduler=scheduler)
    duplicate = scheduler.schedule(
        scheduled.request,
        processed_at=scheduled.processed_at + timedelta(minutes=1),
    )

    result = DueReevaluationTriggerBoundary().evaluate(
        (duplicate,),
        as_of=scheduled.scheduled_for,
    ).results[0]

    assert result.outcome is ReevaluationTriggerOutcome.REJECTED
    assert result.reason is ReevaluationTriggerReason.SCHEDULE_RESULT_INVALID


def test_schedule_evidence_from_the_future_is_rejected() -> None:
    requested_at = REQUESTED_AT + timedelta(hours=1)
    scheduled = _schedule_result(requested_at=requested_at)

    result = DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=REQUESTED_AT,
    ).results[0]

    assert result.outcome is ReevaluationTriggerOutcome.REJECTED
    assert result.reason is ReevaluationTriggerReason.SCHEDULE_EVIDENCE_FROM_FUTURE


def test_completed_schedule_is_reported_as_duplicate() -> None:
    scheduled = _schedule_result()

    batch = DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=scheduled.scheduled_for,
        completed_request_ids=(scheduled.request_id,),
    )

    result = batch.results[0]
    assert result.outcome is ReevaluationTriggerOutcome.DUPLICATE
    assert result.reason is ReevaluationTriggerReason.REQUEST_ALREADY_COMPLETED
    assert result.trigger_request is None
    assert batch.completed_request_ids == (scheduled.request_id,)


def test_duplicate_records_emit_once_and_complete_once() -> None:
    scheduled = _schedule_result()

    batch = DueReevaluationTriggerBoundary().evaluate(
        (scheduled, scheduled),
        as_of=scheduled.scheduled_for,
    )

    assert tuple(result.outcome for result in batch.results) == (
        ReevaluationTriggerOutcome.EMITTED,
        ReevaluationTriggerOutcome.DUPLICATE,
    )
    assert len(batch.trigger_requests) == 1
    assert batch.completed_request_ids == (scheduled.request_id,)


def test_batch_order_and_replay_are_deterministic() -> None:
    later = _schedule_result(
        context_id="later",
        hint="later-change",
        scheduled_for=REQUESTED_AT + timedelta(hours=2),
    )
    earlier = _schedule_result(
        context_id="earlier",
        hint="earlier-change",
        scheduled_for=REQUESTED_AT + timedelta(hours=1),
    )
    as_of = REQUESTED_AT + timedelta(hours=2)
    boundary = DueReevaluationTriggerBoundary()

    first = boundary.evaluate((later, earlier), as_of=as_of)
    second = boundary.evaluate((earlier, later), as_of=as_of)

    assert first == second
    assert first.batch_id == second.batch_id
    assert tuple(result.request_id for result in first.results) == (
        earlier.request_id,
        later.request_id,
    )
    assert len(first.trigger_requests) == 2


def test_trigger_provenance_is_preserved_and_immutable() -> None:
    scheduled = _schedule_result()

    result = DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=scheduled.scheduled_for,
    ).results[0]

    assert result.provenance["source_action_id"] == scheduled.request.action_id
    assert result.provenance["source_context_id"] == scheduled.request.context_id
    assert result.provenance["source_decision_id"] == scheduled.request.decision_id
    assert result.provenance["source_correlation_id"] == scheduled.request.correlation_id
    assert result.provenance["reevaluation_request_id"] == scheduled.request_id
    assert result.provenance["reevaluation_trigger_type"] == "expected_change_reached"
    with pytest.raises(TypeError):
        result.provenance["reevaluation_trigger_type"] = "changed"  # type: ignore[index]


def test_boundary_requires_explicit_aware_time_and_valid_completion_ids() -> None:
    scheduled = _schedule_result()
    boundary = DueReevaluationTriggerBoundary()

    with pytest.raises(ValueError, match="timezone-aware"):
        boundary.evaluate((scheduled,), as_of=datetime(2026, 8, 2, 9, 0))
    with pytest.raises(ValueError, match="must be unique"):
        boundary.evaluate(
            (scheduled,),
            as_of=scheduled.scheduled_for,
            completed_request_ids=(scheduled.request_id, scheduled.request_id),
        )


def test_module_has_no_runtime_hardware_vendor_or_home_assistant_imports() -> None:
    tree = ast.parse(inspect.getsource(trigger_module))
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

    prohibited = {
        "runtime",
        "decision_orchestrator",
        "hal",
        "delivery",
        "homeassistant",
        "intellicenter",
        "vendors",
    }
    assert not any(
        component in prohibited
        for module_name in imported_modules
        for component in module_name.split(".")
    )
