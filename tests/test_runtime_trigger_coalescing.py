from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.evaluation_context import EvaluationTrigger
from poolos.evaluation_triggers import EvaluationTriggerRequest, TriggerUrgency
from poolos.reevaluation_runtime_submission import (
    ReevaluationRuntimeSubmissionOutcome,
)
from poolos.runtime_trigger_coalescing import (
    RuntimeTriggerCoalescingBoundary,
    RuntimeTriggerCoalescingOutcome,
    RuntimeTriggerCoalescingReason,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Request:
    submission_id: str
    trigger_request: EvaluationTriggerRequest


@dataclass(frozen=True)
class _Submission:
    result_id: str
    outcome: ReevaluationRuntimeSubmissionOutcome
    request: _Request
    submitted_at: datetime
    accepted_submission_ids: tuple[str, ...]


def _submission(
    submission_id: str,
    *,
    outcome: ReevaluationRuntimeSubmissionOutcome = (
        ReevaluationRuntimeSubmissionOutcome.ACCEPTED
    ),
    requested_at: datetime = NOW - timedelta(minutes=5),
    submitted_at: datetime = NOW - timedelta(minutes=1),
    urgency: TriggerUrgency = TriggerUrgency.NORMAL,
    trigger: EvaluationTrigger = EvaluationTrigger.EXPECTED_CHANGE_REACHED,
) -> _Submission:
    request = _Request(
        submission_id=submission_id,
        trigger_request=EvaluationTriggerRequest(
            trigger=trigger,
            requested_at=requested_at,
            urgency=urgency,
            source="poolos.due_reevaluation_trigger_boundary",
            reason=f"reason-{submission_id}",
        ),
    )
    accepted = (submission_id,) if outcome is ReevaluationRuntimeSubmissionOutcome.ACCEPTED else ()
    return _Submission(
        result_id=f"result-{submission_id}",
        outcome=outcome,
        request=request,
        submitted_at=submitted_at,
        accepted_submission_ids=accepted,
    )


def test_single_accepted_submission_is_consumed_and_coalesced() -> None:
    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (_submission("submission-a"),), coalesced_at=NOW
    )

    assert batch.results[0].outcome is RuntimeTriggerCoalescingOutcome.CONSUMED
    assert batch.consumed_submission_ids == ("submission-a",)
    assert batch.coalesced_trigger is not None
    assert batch.coalesced_trigger.primary.reason == "reason-submission-a"


def test_existing_coalescer_precedence_is_preserved() -> None:
    routine = _submission("routine", urgency=TriggerUrgency.ROUTINE)
    immediate = _submission("immediate", urgency=TriggerUrgency.IMMEDIATE)

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (routine, immediate), coalesced_at=NOW
    )

    assert batch.coalesced_trigger is not None
    assert batch.coalesced_trigger.primary.urgency is TriggerUrgency.IMMEDIATE
    assert len(batch.coalesced_trigger.requests) == 2


def test_input_order_does_not_change_batch() -> None:
    first = _submission("first", requested_at=NOW - timedelta(minutes=3))
    second = _submission("second", requested_at=NOW - timedelta(minutes=2))
    boundary = RuntimeTriggerCoalescingBoundary()

    a = boundary.coalesce((second, first), coalesced_at=NOW)
    b = boundary.coalesce((first, second), coalesced_at=NOW)

    assert a == b
    assert a.batch_id == b.batch_id


def test_nonaccepted_submission_is_rejected() -> None:
    rejected = _submission(
        "rejected", outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED
    )

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (rejected,), coalesced_at=NOW
    )

    assert batch.results[0].outcome is RuntimeTriggerCoalescingOutcome.REJECTED
    assert batch.results[0].reason is RuntimeTriggerCoalescingReason.SUBMISSION_NOT_ACCEPTED
    assert batch.coalesced_trigger is None


def test_inconsistent_acceptance_evidence_is_rejected() -> None:
    accepted = _submission("missing-evidence")
    inconsistent = replace(accepted, accepted_submission_ids=())

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (inconsistent,), coalesced_at=NOW
    )

    assert batch.results[0].reason is RuntimeTriggerCoalescingReason.SUBMISSION_EVIDENCE_INVALID
    assert batch.coalesced_trigger is None


def test_future_submission_is_rejected() -> None:
    future = _submission("future", submitted_at=NOW + timedelta(seconds=1))

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (future,), coalesced_at=NOW
    )

    assert batch.results[0].reason is RuntimeTriggerCoalescingReason.SUBMISSION_FROM_FUTURE


def test_prior_consumption_returns_duplicate_without_recoalescing() -> None:
    submission = _submission("already-consumed")

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (submission,),
        coalesced_at=NOW,
        consumed_submission_ids=("already-consumed",),
    )

    assert batch.results[0].outcome is RuntimeTriggerCoalescingOutcome.DUPLICATE
    assert batch.coalesced_trigger is None


def test_duplicate_inputs_are_consumed_at_most_once() -> None:
    submission = _submission("duplicate")

    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (submission, submission), coalesced_at=NOW
    )

    assert [item.outcome for item in batch.results] == [
        RuntimeTriggerCoalescingOutcome.CONSUMED,
        RuntimeTriggerCoalescingOutcome.DUPLICATE,
    ]
    assert batch.consumed_submission_ids == ("duplicate",)
    assert batch.coalesced_trigger is not None
    assert len(batch.coalesced_trigger.requests) == 1


def test_replay_with_consumed_ids_is_deterministic() -> None:
    submission = _submission("replay")
    boundary = RuntimeTriggerCoalescingBoundary()
    first = boundary.coalesce((submission,), coalesced_at=NOW)
    second = boundary.coalesce(
        (submission,),
        coalesced_at=NOW,
        consumed_submission_ids=first.consumed_submission_ids,
    )

    assert second.results[0].outcome is RuntimeTriggerCoalescingOutcome.DUPLICATE
    assert second.coalesced_trigger is None


def test_naive_coalescing_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RuntimeTriggerCoalescingBoundary().coalesce(
            (_submission("naive"),), coalesced_at=datetime(2026, 8, 4, 12, 0)
        )


def test_consumed_ids_are_normalized_and_validated() -> None:
    boundary = RuntimeTriggerCoalescingBoundary()
    a = _submission("a")

    batch = boundary.coalesce(
        (a,), coalesced_at=NOW, consumed_submission_ids=("z", "b")
    )
    assert batch.consumed_submission_ids == ("a", "b", "z")

    with pytest.raises(ValueError, match="unique"):
        boundary.coalesce(
            (a,), coalesced_at=NOW, consumed_submission_ids=("x", "x")
        )


def test_batch_and_provenance_are_immutable() -> None:
    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (_submission("immutable"),), coalesced_at=NOW
    )

    with pytest.raises(FrozenInstanceError):
        batch.coalesced_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        batch.provenance["changed"] = "yes"  # type: ignore[index]
