"""Deterministic conversion of due reevaluations into typed trigger requests.

The boundary consumes immutable reevaluation schedule records and explicit
completion evidence.  It selects due records deterministically and emits typed
``EvaluationTriggerRequest`` values without running a decision cycle, mutating
the scheduler, contacting an external system, or actuating equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .evaluation_context import EvaluationTrigger
from .evaluation_triggers import EvaluationTriggerRequest, TriggerUrgency
from .reevaluation_scheduling import (
    ReevaluationScheduleOutcome,
    ReevaluationScheduleReason,
    ReevaluationScheduleResult,
)


class ReevaluationTriggerOutcome(str, Enum):
    """Outcome of evaluating one reevaluation schedule record."""

    EMITTED = "emitted"
    NOT_DUE = "not_due"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    CANCELLED = "cancelled"


class ReevaluationTriggerReason(str, Enum):
    """Stable machine-readable trigger-boundary result reasons."""

    TRIGGER_EMITTED = "trigger_emitted"
    SCHEDULE_NOT_DUE = "schedule_not_due"
    SCHEDULE_RESULT_INVALID = "schedule_result_invalid"
    SCHEDULE_EVIDENCE_FROM_FUTURE = "schedule_evidence_from_future"
    REQUEST_ALREADY_COMPLETED = "request_already_completed"
    REQUEST_CANCELLED = "request_cancelled"


_OUTCOME_BY_REASON: Mapping[
    ReevaluationTriggerReason,
    ReevaluationTriggerOutcome,
] = MappingProxyType(
    {
        ReevaluationTriggerReason.TRIGGER_EMITTED: ReevaluationTriggerOutcome.EMITTED,
        ReevaluationTriggerReason.SCHEDULE_NOT_DUE: ReevaluationTriggerOutcome.NOT_DUE,
        ReevaluationTriggerReason.SCHEDULE_RESULT_INVALID: (
            ReevaluationTriggerOutcome.REJECTED
        ),
        ReevaluationTriggerReason.SCHEDULE_EVIDENCE_FROM_FUTURE: (
            ReevaluationTriggerOutcome.REJECTED
        ),
        ReevaluationTriggerReason.REQUEST_ALREADY_COMPLETED: (
            ReevaluationTriggerOutcome.DUPLICATE
        ),
        ReevaluationTriggerReason.REQUEST_CANCELLED: (
            ReevaluationTriggerOutcome.CANCELLED
        ),
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReevaluationTriggerResult:
    """Immutable evidence for one schedule-record evaluation."""

    emission_id: str
    outcome: ReevaluationTriggerOutcome
    reason: ReevaluationTriggerReason
    schedule_result: ReevaluationScheduleResult
    evaluated_at: datetime
    completed_request_ids: tuple[str, ...]
    trigger_request: EvaluationTriggerRequest | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.emission_id.strip():
            raise ValueError("emission_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        if _OUTCOME_BY_REASON[self.reason] is not self.outcome:
            raise ValueError("trigger reason must match its outcome")
        completed_ids = tuple(self.completed_request_ids)
        if any(not request_id.strip() for request_id in completed_ids):
            raise ValueError("completed request IDs must not be empty")
        if len(set(completed_ids)) != len(completed_ids):
            raise ValueError("completed request IDs must be unique")
        if completed_ids != tuple(sorted(completed_ids)):
            raise ValueError("completed request IDs must be sorted")
        if self.outcome is ReevaluationTriggerOutcome.EMITTED:
            if self.trigger_request is None:
                raise ValueError("emitted result requires a trigger request")
            if self.schedule_result.request_id not in completed_ids:
                raise ValueError("emitted result must complete its schedule request")
            if self.trigger_request.trigger is not EvaluationTrigger.EXPECTED_CHANGE_REACHED:
                raise ValueError("emitted result requires expected-change trigger")
        elif self.trigger_request is not None:
            raise ValueError("non-emitted result cannot contain a trigger request")
        object.__setattr__(self, "completed_request_ids", completed_ids)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def request_id(self) -> str:
        return self.schedule_result.request_id


@dataclass(frozen=True, slots=True)
class DueReevaluationTriggerBatch:
    """Immutable deterministic result of evaluating a schedule-record batch."""

    batch_id: str
    evaluated_at: datetime
    results: tuple[ReevaluationTriggerResult, ...]
    completed_request_ids: tuple[str, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        results = tuple(self.results)
        completed_ids = tuple(self.completed_request_ids)
        if any(not request_id.strip() for request_id in completed_ids):
            raise ValueError("completed request IDs must not be empty")
        if len(set(completed_ids)) != len(completed_ids):
            raise ValueError("completed request IDs must be unique")
        if completed_ids != tuple(sorted(completed_ids)):
            raise ValueError("completed request IDs must be sorted")
        if results and results[-1].completed_request_ids != completed_ids:
            raise ValueError("batch completion evidence must match its final result")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "completed_request_ids", completed_ids)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def trigger_requests(self) -> tuple[EvaluationTriggerRequest, ...]:
        """Return emitted trigger requests in deterministic schedule order."""

        return tuple(
            result.trigger_request
            for result in self.results
            if result.trigger_request is not None
        )


@dataclass(frozen=True, slots=True)
class DueReevaluationTriggerBoundary:
    """Select due immutable records and emit typed trigger requests only."""

    boundary_name: str = "poolos.due_reevaluation_trigger_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self,
        schedule_results: tuple[ReevaluationScheduleResult, ...],
        *,
        as_of: datetime,
        completed_request_ids: tuple[str, ...] = (),
    ) -> DueReevaluationTriggerBatch:
        """Return deterministic trigger evidence without invoking orchestration."""

        _require_aware(as_of, "as_of")
        completed = self._normalize_completed_ids(completed_request_ids)
        ordered = tuple(
            sorted(
                schedule_results,
                key=lambda result: (
                    result.scheduled_for,
                    result.request_id,
                    result.result_id,
                ),
            )
        )
        initial_completed = completed
        results: list[ReevaluationTriggerResult] = []
        for schedule_result in ordered:
            result = self._evaluate_one(
                schedule_result,
                as_of=as_of,
                completed_request_ids=completed,
            )
            completed = result.completed_request_ids
            results.append(result)

        identity_payload = {
            "as_of": as_of.isoformat(),
            "boundary_name": self.boundary_name,
            "initial_completed_request_ids": initial_completed,
            "result_ids": tuple(result.emission_id for result in results),
        }
        batch_id = "reevaluation-trigger-batch-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        return DueReevaluationTriggerBatch(
            batch_id=batch_id,
            evaluated_at=as_of,
            results=tuple(results),
            completed_request_ids=completed,
            provenance={
                "reevaluation_trigger_batch_id": batch_id,
                "reevaluation_trigger_boundary": self.boundary_name,
                "reevaluation_trigger_evaluated_at": as_of.isoformat(),
                "reevaluation_trigger_record_count": str(len(ordered)),
                "reevaluation_trigger_emitted_count": str(
                    sum(
                        result.outcome is ReevaluationTriggerOutcome.EMITTED
                        for result in results
                    )
                ),
            },
        )

    def _evaluate_one(
        self,
        schedule_result: ReevaluationScheduleResult,
        *,
        as_of: datetime,
        completed_request_ids: tuple[str, ...],
    ) -> ReevaluationTriggerResult:
        request_id = schedule_result.request_id
        if schedule_result.outcome is ReevaluationScheduleOutcome.CANCELLED:
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.CANCELLED,
                reason=ReevaluationTriggerReason.REQUEST_CANCELLED,
                completed_request_ids=completed_request_ids,
            )
        if (
            schedule_result.outcome is not ReevaluationScheduleOutcome.SCHEDULED
            or schedule_result.reason is not ReevaluationScheduleReason.SCHEDULE_ACCEPTED
        ):
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.REJECTED,
                reason=ReevaluationTriggerReason.SCHEDULE_RESULT_INVALID,
                completed_request_ids=completed_request_ids,
            )
        if schedule_result.processed_at > as_of:
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.REJECTED,
                reason=ReevaluationTriggerReason.SCHEDULE_EVIDENCE_FROM_FUTURE,
                completed_request_ids=completed_request_ids,
            )
        if request_id in completed_request_ids:
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.DUPLICATE,
                reason=ReevaluationTriggerReason.REQUEST_ALREADY_COMPLETED,
                completed_request_ids=completed_request_ids,
            )
        if schedule_result.scheduled_for > as_of:
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.NOT_DUE,
                reason=ReevaluationTriggerReason.SCHEDULE_NOT_DUE,
                completed_request_ids=completed_request_ids,
            )

        updated_completed = tuple(sorted((*completed_request_ids, request_id)))
        hint = schedule_result.request.receipt.pipeline_result.action.reevaluation_hint
        if hint is None or not hint.strip():
            return self._result(
                schedule_result,
                as_of=as_of,
                outcome=ReevaluationTriggerOutcome.REJECTED,
                reason=ReevaluationTriggerReason.SCHEDULE_RESULT_INVALID,
                completed_request_ids=completed_request_ids,
            )
        trigger_request = EvaluationTriggerRequest(
            trigger=EvaluationTrigger.EXPECTED_CHANGE_REACHED,
            requested_at=as_of,
            urgency=TriggerUrgency.NORMAL,
            source=self.boundary_name,
            reason=f"Scheduled expected change reached: {hint}",
        )
        return self._result(
            schedule_result,
            as_of=as_of,
            outcome=ReevaluationTriggerOutcome.EMITTED,
            reason=ReevaluationTriggerReason.TRIGGER_EMITTED,
            completed_request_ids=updated_completed,
            trigger_request=trigger_request,
        )

    def _result(
        self,
        schedule_result: ReevaluationScheduleResult,
        *,
        as_of: datetime,
        outcome: ReevaluationTriggerOutcome,
        reason: ReevaluationTriggerReason,
        completed_request_ids: tuple[str, ...],
        trigger_request: EvaluationTriggerRequest | None = None,
    ) -> ReevaluationTriggerResult:
        identity_payload = {
            "as_of": as_of.isoformat(),
            "boundary_name": self.boundary_name,
            "completed_request_ids": completed_request_ids,
            "outcome": outcome.value,
            "reason": reason.value,
            "schedule_result_id": schedule_result.result_id,
            "trigger": trigger_request.trigger.value if trigger_request else None,
        }
        emission_id = "reevaluation-trigger-result-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        provenance = {
            **dict(schedule_result.provenance),
            "reevaluation_trigger_result_id": emission_id,
            "reevaluation_trigger_boundary": self.boundary_name,
            "reevaluation_trigger_outcome": outcome.value,
            "reevaluation_trigger_reason": reason.value,
            "reevaluation_trigger_evaluated_at": as_of.isoformat(),
            "reevaluation_trigger_type": (
                trigger_request.trigger.value if trigger_request else ""
            ),
        }
        return ReevaluationTriggerResult(
            emission_id=emission_id,
            outcome=outcome,
            reason=reason,
            schedule_result=schedule_result,
            evaluated_at=as_of,
            completed_request_ids=completed_request_ids,
            trigger_request=trigger_request,
            provenance=provenance,
        )

    @staticmethod
    def _normalize_completed_ids(request_ids: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(request_ids)
        if any(not request_id.strip() for request_id in normalized):
            raise ValueError("completed request IDs must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("completed request IDs must be unique")
        return tuple(sorted(normalized))
