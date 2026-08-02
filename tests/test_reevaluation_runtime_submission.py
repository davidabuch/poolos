from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import inspect

import pytest

import poolos.reevaluation_runtime_submission as submission_module
from poolos.downstream_operational_action_adapter import (
    NonHardwareOperationalActionAdapter,
)
from poolos.evaluation_context import EvaluationTrigger
from poolos.evaluation_triggers import EvaluationTriggerRequest
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
    ReevaluationRuntimeSubmissionReason,
    ReevaluationRuntimeSubmissionRequest,
)
from poolos.reevaluation_scheduling import (
    DeterministicReevaluationScheduler,
    ReevaluationScheduleRequest,
    ReevaluationScheduleResult,
)
from poolos.reevaluation_state_persistence import (
    ReevaluationStatePersistenceBoundary,
)
from poolos.reevaluation_trigger_boundary import (
    DueReevaluationTriggerBoundary,
    ReevaluationTriggerResult,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
SCHEDULED_FOR = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def _scheduled(
    *,
    context_id: str = "context-15l",
    scheduled_for: datetime = SCHEDULED_FOR,
) -> ReevaluationScheduleResult:
    evaluation = OperationalEvaluationResult(
        disposition=OperationalDisposition.SCHEDULE_REEVALUATION,
        reason_code=OperationalReasonCode.REEVALUATION_HINT_AVAILABLE,
        reason="A future expected change requires reevaluation",
        context_id=context_id,
        decision_id=f"decision-{context_id}",
        reevaluation_hint=f"expected-change-{context_id}",
        diagnostics={"evaluation_source": "epic-10.15l-test"},
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
        provenance={"request_source": "runtime-submission-test"},
    )
    return DeterministicReevaluationScheduler().schedule(
        request,
        processed_at=REQUESTED_AT,
    )


def _emitted(
    *,
    context_id: str = "context-15l",
    scheduled_for: datetime = SCHEDULED_FOR,
) -> ReevaluationTriggerResult:
    scheduled = _scheduled(context_id=context_id, scheduled_for=scheduled_for)
    return DueReevaluationTriggerBoundary().evaluate(
        (scheduled,),
        as_of=scheduled_for,
    ).results[0]


def _request(
    *,
    context_id: str = "context-15l",
    scheduled_for: datetime = SCHEDULED_FOR,
) -> ReevaluationRuntimeSubmissionRequest:
    return ReevaluationRuntimeSubmissionRequest.from_trigger_result(
        _emitted(context_id=context_id, scheduled_for=scheduled_for)
    )


def test_single_valid_trigger_is_accepted() -> None:
    request = _request()

    batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=SCHEDULED_FOR,
    )

    result = batch.results[0]
    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.ACCEPTED
    assert result.reason is ReevaluationRuntimeSubmissionReason.SUBMISSION_ACCEPTED
    assert batch.accepted_submission_ids == (request.submission_id,)
    assert batch.accepted_trigger_requests == (request.trigger_request,)


def test_submission_identity_is_deterministic() -> None:
    first = _request()
    second = _request()

    first_batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (first,), submitted_at=SCHEDULED_FOR
    )
    second_batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (second,), submitted_at=SCHEDULED_FOR
    )

    assert first == second
    assert first.submission_id == second.submission_id
    assert first_batch == second_batch
    assert first_batch.results[0].result_id == second_batch.results[0].result_id


def test_submission_is_independent_of_input_order() -> None:
    later = _request(
        context_id="later",
        scheduled_for=SCHEDULED_FOR + timedelta(hours=1),
    )
    earlier = _request(context_id="earlier")
    submitted_at = SCHEDULED_FOR + timedelta(hours=1)
    boundary = ReevaluationRuntimeSubmissionBoundary()

    first = boundary.submit((later, earlier), submitted_at=submitted_at)
    second = boundary.submit((earlier, later), submitted_at=submitted_at)

    assert first == second
    assert first.batch_id == second.batch_id
    assert tuple(result.request for result in first.results) == (earlier, later)


def test_explicit_prior_acceptance_suppresses_duplicate() -> None:
    request = _request()

    batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=SCHEDULED_FOR,
        accepted_submission_ids=(request.submission_id,),
    )

    result = batch.results[0]
    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.DUPLICATE
    assert (
        result.reason
        is ReevaluationRuntimeSubmissionReason.SUBMISSION_ALREADY_ACCEPTED
    )
    assert batch.accepted_trigger_requests == ()


def test_restored_reevaluation_evidence_is_accepted_consistently() -> None:
    scheduled = _scheduled()
    persistence = ReevaluationStatePersistenceBoundary()
    snapshot = persistence.capture(
        (scheduled,),
        captured_at=SCHEDULED_FOR,
    )
    restored = persistence.restore(persistence.serialize(snapshot))
    original_emission = DueReevaluationTriggerBoundary().evaluate(
        snapshot.schedule_results,
        as_of=SCHEDULED_FOR,
        completed_request_ids=snapshot.completed_request_ids,
    ).results[0]
    restored_emission = DueReevaluationTriggerBoundary().evaluate(
        restored.schedule_results,
        as_of=SCHEDULED_FOR,
        completed_request_ids=restored.completed_request_ids,
    ).results[0]
    original_request = ReevaluationRuntimeSubmissionRequest.from_trigger_result(
        original_emission
    )
    restored_request = ReevaluationRuntimeSubmissionRequest.from_trigger_result(
        restored_emission
    )
    boundary = ReevaluationRuntimeSubmissionBoundary()

    assert restored_request == original_request
    assert boundary.submit(
        (restored_request,), submitted_at=SCHEDULED_FOR
    ) == boundary.submit((original_request,), submitted_at=SCHEDULED_FOR)


def test_previously_accepted_restored_trigger_returns_duplicate() -> None:
    request = _request()
    first = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,), submitted_at=SCHEDULED_FOR
    )

    replay = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=SCHEDULED_FOR,
        accepted_submission_ids=first.accepted_submission_ids,
    )

    assert replay.results[0].outcome is ReevaluationRuntimeSubmissionOutcome.DUPLICATE
    assert replay.accepted_submission_ids == first.accepted_submission_ids


def test_malformed_trigger_evidence_is_rejected() -> None:
    request = _request()
    malformed_trigger = replace(request.trigger_request, reason="malformed reason")
    malformed = replace(request, trigger_request=malformed_trigger)

    result = ReevaluationRuntimeSubmissionBoundary().submit(
        (malformed,), submitted_at=SCHEDULED_FOR
    ).results[0]

    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.REJECTED
    assert (
        result.reason
        is ReevaluationRuntimeSubmissionReason.TRIGGER_EVIDENCE_INVALID
    )


def test_naive_trigger_and_submission_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EvaluationTriggerRequest(
            trigger=EvaluationTrigger.EXPECTED_CHANGE_REACHED,
            requested_at=datetime(2026, 8, 2, 9, 0),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        ReevaluationRuntimeSubmissionBoundary().submit(
            (_request(),),
            submitted_at=datetime(2026, 8, 2, 9, 0),
        )


def test_future_dated_trigger_is_rejected() -> None:
    request = _request()

    result = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,),
        submitted_at=SCHEDULED_FOR - timedelta(seconds=1),
    ).results[0]

    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.REJECTED
    assert result.reason is ReevaluationRuntimeSubmissionReason.TRIGGER_FROM_FUTURE


def test_unsupported_trigger_type_is_rejected() -> None:
    request = _request()
    unsupported = replace(
        request,
        trigger_request=replace(
            request.trigger_request,
            trigger=EvaluationTrigger.MANUAL,
        ),
    )

    result = ReevaluationRuntimeSubmissionBoundary().submit(
        (unsupported,), submitted_at=SCHEDULED_FOR
    ).results[0]

    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.REJECTED
    assert (
        result.reason
        is ReevaluationRuntimeSubmissionReason.TRIGGER_TYPE_UNSUPPORTED
    )


def test_inconsistent_provenance_is_rejected() -> None:
    request = _request()
    provenance = dict(request.provenance)
    provenance["source_correlation_id"] = "different-cycle"
    inconsistent = replace(request, provenance=provenance)

    result = ReevaluationRuntimeSubmissionBoundary().submit(
        (inconsistent,), submitted_at=SCHEDULED_FOR
    ).results[0]

    assert result.outcome is ReevaluationRuntimeSubmissionOutcome.REJECTED
    assert result.reason is ReevaluationRuntimeSubmissionReason.PROVENANCE_INCONSISTENT


def test_duplicate_inputs_are_accepted_at_most_once() -> None:
    request = _request()

    batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (request, request),
        submitted_at=SCHEDULED_FOR,
    )

    assert tuple(result.outcome for result in batch.results) == (
        ReevaluationRuntimeSubmissionOutcome.ACCEPTED,
        ReevaluationRuntimeSubmissionOutcome.DUPLICATE,
    )
    assert batch.accepted_submission_ids == (request.submission_id,)
    assert batch.accepted_trigger_requests == (request.trigger_request,)


def test_replay_produces_equivalent_batch_and_acceptance_evidence() -> None:
    first = _request(context_id="first")
    second = _request(context_id="second")
    boundary = ReevaluationRuntimeSubmissionBoundary()

    original = boundary.submit((second, first), submitted_at=SCHEDULED_FOR)
    replay = boundary.submit((first, second), submitted_at=SCHEDULED_FOR)

    assert replay == original
    assert replay.batch_id == original.batch_id
    assert replay.accepted_submission_ids == original.accepted_submission_ids


def test_results_and_provenance_are_immutable() -> None:
    request = _request()
    batch = ReevaluationRuntimeSubmissionBoundary().submit(
        (request,), submitted_at=SCHEDULED_FOR
    )
    result = batch.results[0]

    with pytest.raises(FrozenInstanceError):
        result.outcome = ReevaluationRuntimeSubmissionOutcome.REJECTED  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.provenance["changed"] = "yes"  # type: ignore[index]


def test_invalid_explicit_acceptance_evidence_is_rejected() -> None:
    request = _request()
    boundary = ReevaluationRuntimeSubmissionBoundary()

    with pytest.raises(ValueError, match="unique"):
        boundary.submit(
            (request,),
            submitted_at=SCHEDULED_FOR,
            accepted_submission_ids=(request.submission_id, request.submission_id),
        )


def test_empty_submission_batch_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ReevaluationRuntimeSubmissionBoundary().submit(
            (), submitted_at=SCHEDULED_FOR
        )


def test_module_has_no_runtime_hardware_vendor_network_or_io_imports() -> None:
    tree = ast.parse(inspect.getsource(submission_module))
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
        "queue",
        "threading",
        "asyncio",
    }
    assert not any(
        component in prohibited
        for module_name in imported_modules
        for component in module_name.split(".")
    )
