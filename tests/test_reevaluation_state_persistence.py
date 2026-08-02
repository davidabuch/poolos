from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import inspect
import json

import pytest

import poolos.reevaluation_state_persistence as persistence_module
from poolos.downstream_operational_action_adapter import (
    NonHardwareOperationalActionAdapter,
)
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
from poolos.reevaluation_runtime_submission import (
    ReevaluationRuntimeSubmissionBoundary,
    ReevaluationRuntimeSubmissionOutcome,
    ReevaluationRuntimeSubmissionRequest,
)
from poolos.reevaluation_scheduling import (
    DeterministicReevaluationScheduler,
    ReevaluationScheduleOutcome,
    ReevaluationScheduleRequest,
    ReevaluationScheduleResult,
)
from poolos.reevaluation_state_persistence import (
    ReevaluationStatePersistenceBoundary,
    ReevaluationStatePersistenceError,
)
from poolos.reevaluation_trigger_boundary import (
    DueReevaluationTriggerBoundary,
    ReevaluationTriggerOutcome,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
SCHEDULED_FOR = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def _schedule_result(
    *,
    context_id: str = "context-15k",
    scheduled_for: datetime = SCHEDULED_FOR,
    cancelled: bool = False,
) -> ReevaluationScheduleResult:
    evaluation = OperationalEvaluationResult(
        disposition=OperationalDisposition.SCHEDULE_REEVALUATION,
        reason_code=OperationalReasonCode.REEVALUATION_HINT_AVAILABLE,
        reason="A future expected change requires reevaluation",
        context_id=context_id,
        decision_id=f"decision-{context_id}",
        reevaluation_hint=f"expected-change-{context_id}",
        diagnostics={"evaluation_source": "epic-10.15k-test"},
    )
    instruction = OperationalDispositionOrchestrator().orchestrate(evaluation)
    action = CanonicalOperationalAction.from_instruction(
        instruction,
        correlation_id=f"cycle-{context_id}",
    )
    receipt = NonHardwareOperationalActionAdapter().adapt(
        OperationalActionPipeline().process(action)
    )
    request = ReevaluationScheduleRequest(
        receipt=receipt,
        requested_at=REQUESTED_AT,
        scheduled_for=scheduled_for,
        provenance={"request_source": "persistence-test"},
    )
    scheduler = DeterministicReevaluationScheduler()
    scheduled = scheduler.schedule(request, processed_at=REQUESTED_AT)
    if not cancelled:
        return scheduled
    return scheduler.cancel(
        request,
        cancelled_at=REQUESTED_AT + timedelta(minutes=5),
        cancellation_reason="Expected change was superseded",
    )


def _round_trip(
    results: tuple[ReevaluationScheduleResult, ...],
    *,
    completed_request_ids: tuple[str, ...] = (),
    accepted_submission_ids: tuple[str, ...] = (),
    captured_at: datetime = SCHEDULED_FOR,
):
    boundary = ReevaluationStatePersistenceBoundary()
    snapshot = boundary.capture(
        results,
        completed_request_ids=completed_request_ids,
        accepted_submission_ids=accepted_submission_ids,
        captured_at=captured_at,
    )
    return snapshot, boundary.serialize(snapshot), boundary.restore(
        boundary.serialize(snapshot)
    )


def _accepted_submission_evidence(
    scheduled: ReevaluationScheduleResult,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    trigger_batch = DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=scheduled.scheduled_for,
    )
    request = ReevaluationRuntimeSubmissionRequest.from_trigger_result(
        trigger_batch.results[0]
    )
    submission_batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=scheduled.scheduled_for,
    )
    return (
        trigger_batch.completed_request_ids,
        submission_batch.accepted_submission_ids,
    )


def test_empty_state_snapshot_and_restore() -> None:
    snapshot, serialized, restored = _round_trip(())

    assert restored == snapshot
    assert restored.schedule_results == ()
    assert restored.completed_request_ids == ()
    assert restored.accepted_submission_ids == ()
    assert json.loads(serialized)["schema_version"] == 2


def test_scheduled_record_round_trip_preserves_typed_evidence() -> None:
    scheduled = _schedule_result()

    snapshot, _, restored = _round_trip((scheduled,))

    assert restored == snapshot
    assert restored.schedule_results == (scheduled,)
    assert restored.schedule_results[0].request.receipt == scheduled.request.receipt
    assert restored.schedule_results[0].provenance == scheduled.provenance


def test_cancelled_record_round_trip_remains_cancelled() -> None:
    cancelled = _schedule_result(cancelled=True)

    _, _, restored = _round_trip((cancelled,))

    assert restored.schedule_results[0].outcome is ReevaluationScheduleOutcome.CANCELLED
    result = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
    ).results[0]
    assert result.outcome is ReevaluationTriggerOutcome.CANCELLED


def test_completed_request_identity_round_trip() -> None:
    scheduled = _schedule_result()

    _, _, restored = _round_trip(
        (scheduled,), completed_request_ids=(scheduled.request_id,)
    )

    assert restored.completed_request_ids == (scheduled.request_id,)


def test_accepted_submission_identity_round_trip_and_restart_suppression() -> None:
    scheduled = _schedule_result()
    completed_ids, accepted_ids = _accepted_submission_evidence(scheduled)

    snapshot, serialized, restored = _round_trip(
        (scheduled,),
        completed_request_ids=completed_ids,
        accepted_submission_ids=accepted_ids,
    )

    assert restored == snapshot
    assert restored.accepted_submission_ids == accepted_ids
    assert json.loads(serialized)["accepted_submission_ids"] == list(accepted_ids)

    trigger_batch = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
    )
    request = ReevaluationRuntimeSubmissionRequest.from_trigger_result(
        trigger_batch.results[0]
    )
    replay = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=SCHEDULED_FOR,
        accepted_submission_ids=restored.accepted_submission_ids,
    )
    assert (
        replay.results[0].outcome
        is ReevaluationRuntimeSubmissionOutcome.DUPLICATE
    )


def test_accepted_submission_serialization_is_input_order_independent() -> None:
    first = _schedule_result(context_id="first")
    second = _schedule_result(context_id="second")
    first_completed, first_accepted = _accepted_submission_evidence(first)
    second_completed, second_accepted = _accepted_submission_evidence(second)
    boundary = ReevaluationStatePersistenceBoundary()

    forward = boundary.capture(
        (first, second),
        completed_request_ids=(*first_completed, *second_completed),
        accepted_submission_ids=(*first_accepted, *second_accepted),
        captured_at=SCHEDULED_FOR,
    )
    reverse = boundary.capture(
        (second, first),
        completed_request_ids=(*second_completed, *first_completed),
        accepted_submission_ids=(*second_accepted, *first_accepted),
        captured_at=SCHEDULED_FOR,
    )

    assert forward == reverse
    assert boundary.serialize(forward) == boundary.serialize(reverse)


def test_accepted_submission_evidence_changes_snapshot_identity() -> None:
    scheduled = _schedule_result()
    completed_ids, accepted_ids = _accepted_submission_evidence(scheduled)
    boundary = ReevaluationStatePersistenceBoundary()

    emitted_only = boundary.capture(
        (scheduled,),
        completed_request_ids=completed_ids,
        captured_at=SCHEDULED_FOR,
    )
    accepted = boundary.capture(
        (scheduled,),
        completed_request_ids=completed_ids,
        accepted_submission_ids=accepted_ids,
        captured_at=SCHEDULED_FOR,
    )

    assert emitted_only.snapshot_id != accepted.snapshot_id


def test_serialization_is_deterministic() -> None:
    scheduled = _schedule_result()
    boundary = ReevaluationStatePersistenceBoundary()
    first = boundary.capture((scheduled,), captured_at=SCHEDULED_FOR)
    second = boundary.capture((scheduled,), captured_at=SCHEDULED_FOR)

    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert boundary.serialize(first) == boundary.serialize(second)


def test_capture_is_independent_of_input_order() -> None:
    later = _schedule_result(
        context_id="later",
        scheduled_for=SCHEDULED_FOR + timedelta(hours=1),
    )
    earlier = _schedule_result(context_id="earlier")
    boundary = ReevaluationStatePersistenceBoundary()
    captured_at = SCHEDULED_FOR + timedelta(hours=1)

    first = boundary.capture((later, earlier), captured_at=captured_at)
    second = boundary.capture((earlier, later), captured_at=captured_at)

    assert first == second
    assert boundary.serialize(first) == boundary.serialize(second)
    assert tuple(item.request_id for item in first.schedule_results) == tuple(
        sorted((later.request_id, earlier.request_id))
    )


def test_restart_followed_by_due_evaluation_emits_trigger() -> None:
    scheduled = _schedule_result()
    _, _, restored = _round_trip((scheduled,))

    batch = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
        completed_request_ids=restored.completed_request_ids,
    )

    assert batch.results[0].outcome is ReevaluationTriggerOutcome.EMITTED
    assert batch.completed_request_ids == (scheduled.request_id,)


def test_completed_request_does_not_reemit_after_restart() -> None:
    scheduled = _schedule_result()
    _, _, restored = _round_trip(
        (scheduled,), completed_request_ids=(scheduled.request_id,)
    )

    batch = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
        completed_request_ids=restored.completed_request_ids,
    )

    assert batch.results[0].outcome is ReevaluationTriggerOutcome.DUPLICATE
    assert batch.trigger_requests == ()


def test_future_request_remains_not_due_after_restart() -> None:
    scheduled = _schedule_result(
        scheduled_for=SCHEDULED_FOR + timedelta(hours=1)
    )
    _, _, restored = _round_trip(
        (scheduled,), captured_at=SCHEDULED_FOR - timedelta(minutes=1)
    )

    batch = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
        completed_request_ids=restored.completed_request_ids,
    )

    assert batch.results[0].outcome is ReevaluationTriggerOutcome.NOT_DUE
    assert batch.trigger_requests == ()


@pytest.mark.parametrize(
    "serialized",
    (
        "not-json",
        "[]",
        '{"schema_version":1}',
        '{"schema_version":true}',
    ),
)
def test_malformed_persisted_state_is_rejected(serialized: str) -> None:
    with pytest.raises(ReevaluationStatePersistenceError):
        ReevaluationStatePersistenceBoundary().restore(serialized)


@pytest.mark.parametrize("unsupported_version", (1, 3))
def test_unsupported_schema_version_is_rejected(
    unsupported_version: int,
) -> None:
    _, serialized, _ = _round_trip(())
    payload = json.loads(serialized)
    payload["schema_version"] = unsupported_version

    with pytest.raises(ReevaluationStatePersistenceError, match="unsupported"):
        ReevaluationStatePersistenceBoundary().restore(json.dumps(payload))


def test_tampered_snapshot_evidence_is_rejected() -> None:
    scheduled = _schedule_result()
    _, serialized, _ = _round_trip((scheduled,))
    payload = json.loads(serialized)
    payload["captured_at"] = (SCHEDULED_FOR + timedelta(minutes=1)).isoformat()

    with pytest.raises(ReevaluationStatePersistenceError, match="identity"):
        ReevaluationStatePersistenceBoundary().restore(json.dumps(payload))


def test_duplicate_and_inconsistent_evidence_is_rejected() -> None:
    scheduled = _schedule_result()
    cancelled = _schedule_result(context_id="cancelled", cancelled=True)
    boundary = ReevaluationStatePersistenceBoundary()

    with pytest.raises(ReevaluationStatePersistenceError, match="unique"):
        boundary.capture((scheduled, scheduled), captured_at=SCHEDULED_FOR)
    with pytest.raises(ReevaluationStatePersistenceError, match="reference"):
        boundary.capture(
            (scheduled,),
            completed_request_ids=("unknown-request",),
            captured_at=SCHEDULED_FOR,
        )
    with pytest.raises(ReevaluationStatePersistenceError, match="cancelled"):
        boundary.capture(
            (cancelled,),
            completed_request_ids=(cancelled.request_id,),
            captured_at=SCHEDULED_FOR,
        )
    with pytest.raises(ReevaluationStatePersistenceError, match="result identity"):
        boundary.capture(
            (replace(scheduled, result_id="tampered-result-id"),),
            captured_at=SCHEDULED_FOR,
        )


def test_invalid_accepted_submission_evidence_is_rejected() -> None:
    scheduled = _schedule_result()
    completed_ids, accepted_ids = _accepted_submission_evidence(scheduled)
    boundary = ReevaluationStatePersistenceBoundary()

    with pytest.raises(ReevaluationStatePersistenceError, match="canonical format"):
        boundary.capture(
            (scheduled,),
            completed_request_ids=completed_ids,
            accepted_submission_ids=("not-a-submission-id",),
            captured_at=SCHEDULED_FOR,
        )
    with pytest.raises(ReevaluationStatePersistenceError, match="unique"):
        boundary.capture(
            (scheduled,),
            completed_request_ids=completed_ids,
            accepted_submission_ids=(*accepted_ids, *accepted_ids),
            captured_at=SCHEDULED_FOR,
        )
    with pytest.raises(ReevaluationStatePersistenceError, match="cannot exceed"):
        boundary.capture(
            (scheduled,),
            completed_request_ids=completed_ids,
            accepted_submission_ids=(
                *accepted_ids,
                "reevaluation-runtime-submission-aaaaaaaaaaaaaaaaaaaaaaaa",
            ),
            captured_at=SCHEDULED_FOR,
        )


def test_missing_schema_v2_submission_evidence_is_rejected() -> None:
    _, serialized, _ = _round_trip(())
    payload = json.loads(serialized)
    del payload["accepted_submission_ids"]

    with pytest.raises(ReevaluationStatePersistenceError):
        ReevaluationStatePersistenceBoundary().restore(json.dumps(payload))


def test_deterministic_replay_is_equivalent_before_and_after_restart() -> None:
    first = _schedule_result(context_id="first")
    second = _schedule_result(
        context_id="second",
        scheduled_for=SCHEDULED_FOR + timedelta(hours=1),
    )
    as_of = SCHEDULED_FOR + timedelta(hours=1)
    boundary = ReevaluationStatePersistenceBoundary()
    snapshot = boundary.capture((second, first), captured_at=as_of)
    restored = boundary.restore(boundary.serialize(snapshot))
    trigger_boundary = DueReevaluationTriggerBoundary()

    original_batch = trigger_boundary.evaluate(
        snapshot.schedule_results,
        as_of=as_of,
        completed_request_ids=snapshot.completed_request_ids,
    )
    restored_batch = trigger_boundary.evaluate(
        restored.schedule_results,
        as_of=as_of,
        completed_request_ids=restored.completed_request_ids,
    )

    assert restored_batch == original_batch
    assert restored_batch.batch_id == original_batch.batch_id


def test_snapshot_and_restored_provenance_are_immutable() -> None:
    scheduled = _schedule_result()
    snapshot, _, restored = _round_trip((scheduled,))

    with pytest.raises(FrozenInstanceError):
        snapshot.captured_at = REQUESTED_AT  # type: ignore[misc]
    with pytest.raises(TypeError):
        restored.schedule_results[0].provenance["changed"] = "yes"  # type: ignore[index]


def test_module_has_no_runtime_hardware_vendor_or_io_imports() -> None:
    tree = ast.parse(inspect.getsource(persistence_module))
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
        "socket",
        "pathlib",
    }
    assert not any(
        component in prohibited
        for module_name in imported_modules
        for component in module_name.split(".")
    )
