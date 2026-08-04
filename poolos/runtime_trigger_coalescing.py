"""Deterministic coalescing of accepted reevaluation runtime submissions.

This boundary consumes immutable acceptance evidence from ADR-048 and delegates
trigger precedence to the existing ``EvaluationTriggerCoalescer``. It emits
immutable coalescing evidence without constructing evaluation contexts,
invoking the Decision Orchestrator, enqueuing work, performing I/O, or actuating
equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .evaluation_triggers import CoalescedEvaluationTrigger, EvaluationTriggerCoalescer
from .reevaluation_runtime_submission import (
    ReevaluationRuntimeSubmissionOutcome,
    ReevaluationRuntimeSubmissionResult,
)


class RuntimeTriggerCoalescingOutcome(str, Enum):
    """Outcome of consuming one runtime-submission result."""

    CONSUMED = "consumed"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class RuntimeTriggerCoalescingReason(str, Enum):
    """Stable machine-readable coalescing reasons."""

    SUBMISSION_CONSUMED = "submission_consumed"
    SUBMISSION_NOT_ACCEPTED = "submission_not_accepted"
    SUBMISSION_EVIDENCE_INVALID = "submission_evidence_invalid"
    SUBMISSION_FROM_FUTURE = "submission_from_future"
    SUBMISSION_ALREADY_CONSUMED = "submission_already_consumed"


_REASON_OUTCOME: Mapping[
    RuntimeTriggerCoalescingReason, RuntimeTriggerCoalescingOutcome
] = MappingProxyType(
    {
        RuntimeTriggerCoalescingReason.SUBMISSION_CONSUMED: (
            RuntimeTriggerCoalescingOutcome.CONSUMED
        ),
        RuntimeTriggerCoalescingReason.SUBMISSION_NOT_ACCEPTED: (
            RuntimeTriggerCoalescingOutcome.REJECTED
        ),
        RuntimeTriggerCoalescingReason.SUBMISSION_EVIDENCE_INVALID: (
            RuntimeTriggerCoalescingOutcome.REJECTED
        ),
        RuntimeTriggerCoalescingReason.SUBMISSION_FROM_FUTURE: (
            RuntimeTriggerCoalescingOutcome.REJECTED
        ),
        RuntimeTriggerCoalescingReason.SUBMISSION_ALREADY_CONSUMED: (
            RuntimeTriggerCoalescingOutcome.DUPLICATE
        ),
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _derived_id(prefix: str, payload: object) -> str:
    return prefix + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RuntimeTriggerCoalescingItemResult:
    """Immutable evidence for one submission-consumption attempt."""

    result_id: str
    outcome: RuntimeTriggerCoalescingOutcome
    reason: RuntimeTriggerCoalescingReason
    submission_result: ReevaluationRuntimeSubmissionResult
    coalesced_at: datetime
    consumed_submission_ids: tuple[str, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        _require_aware(self.coalesced_at, "coalesced_at")
        if _REASON_OUTCOME[self.reason] is not self.outcome:
            raise ValueError("coalescing reason must match its outcome")
        consumed = tuple(self.consumed_submission_ids)
        if any(not item.strip() for item in consumed):
            raise ValueError("consumed submission IDs must not be empty")
        if len(set(consumed)) != len(consumed):
            raise ValueError("consumed submission IDs must be unique")
        if consumed != tuple(sorted(consumed)):
            raise ValueError("consumed submission IDs must be sorted")
        submission_id = self.submission_result.request.submission_id
        if self.outcome is RuntimeTriggerCoalescingOutcome.CONSUMED:
            if submission_id not in consumed:
                raise ValueError("consumed result must record its submission identity")
        elif self.outcome is RuntimeTriggerCoalescingOutcome.REJECTED:
            if submission_id in consumed:
                raise ValueError("rejected result cannot consume its submission identity")
        elif submission_id not in consumed:
            raise ValueError("duplicate result requires prior consumption evidence")
        object.__setattr__(self, "consumed_submission_ids", consumed)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class RuntimeTriggerCoalescingBatch:
    """Immutable result of one deterministic coalescing cycle."""

    batch_id: str
    coalesced_at: datetime
    results: tuple[RuntimeTriggerCoalescingItemResult, ...]
    consumed_submission_ids: tuple[str, ...]
    coalesced_trigger: CoalescedEvaluationTrigger | None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must not be empty")
        _require_aware(self.coalesced_at, "coalesced_at")
        results = tuple(self.results)
        consumed = tuple(self.consumed_submission_ids)
        if consumed != tuple(sorted(consumed)):
            raise ValueError("consumed submission IDs must be sorted")
        if len(set(consumed)) != len(consumed):
            raise ValueError("consumed submission IDs must be unique")
        if results and results[-1].consumed_submission_ids != consumed:
            raise ValueError("batch consumption evidence must match final result")
        consumed_count = sum(
            item.outcome is RuntimeTriggerCoalescingOutcome.CONSUMED
            for item in results
        )
        if consumed_count == 0 and self.coalesced_trigger is not None:
            raise ValueError("empty consumption cannot produce a coalesced trigger")
        if consumed_count > 0 and self.coalesced_trigger is None:
            raise ValueError("consumed submissions require a coalesced trigger")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "consumed_submission_ids", consumed)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class RuntimeTriggerCoalescingBoundary:
    """Consume accepted submission evidence and coalesce its trigger requests."""

    coalescer: EvaluationTriggerCoalescer = field(
        default_factory=EvaluationTriggerCoalescer
    )
    boundary_name: str = "poolos.runtime_trigger_coalescing_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def coalesce(
        self,
        submission_results: tuple[ReevaluationRuntimeSubmissionResult, ...],
        *,
        coalesced_at: datetime,
        consumed_submission_ids: tuple[str, ...] = (),
    ) -> RuntimeTriggerCoalescingBatch:
        """Return deterministic coalescing evidence without runtime side effects."""

        _require_aware(coalesced_at, "coalesced_at")
        if not submission_results:
            raise ValueError("at least one submission result is required")
        consumed = self._normalize_consumed_ids(consumed_submission_ids)
        initial_consumed = consumed
        ordered = tuple(
            sorted(
                submission_results,
                key=lambda item: (
                    item.request.trigger_request.requested_at,
                    item.request.submission_id,
                    item.result_id,
                ),
            )
        )
        results: list[RuntimeTriggerCoalescingItemResult] = []
        accepted_triggers = []
        for submission in ordered:
            item = self._consume_one(
                submission,
                coalesced_at=coalesced_at,
                consumed_submission_ids=consumed,
            )
            consumed = item.consumed_submission_ids
            results.append(item)
            if item.outcome is RuntimeTriggerCoalescingOutcome.CONSUMED:
                accepted_triggers.append(submission.request.trigger_request)

        coalesced_trigger = (
            self.coalescer.coalesce(tuple(accepted_triggers))
            if accepted_triggers
            else None
        )
        batch_id = _derived_id(
            "runtime-trigger-coalescing-batch-",
            {
                "boundary_name": self.boundary_name,
                "coalesced_at": coalesced_at.isoformat(),
                "initial_consumed_submission_ids": initial_consumed,
                "result_ids": tuple(item.result_id for item in results),
                "coalesced_trigger": self._coalesced_payload(coalesced_trigger),
            },
        )
        return RuntimeTriggerCoalescingBatch(
            batch_id=batch_id,
            coalesced_at=coalesced_at,
            results=tuple(results),
            consumed_submission_ids=consumed,
            coalesced_trigger=coalesced_trigger,
            provenance={
                "runtime_trigger_coalescing_batch_id": batch_id,
                "runtime_trigger_coalescing_boundary": self.boundary_name,
                "runtime_trigger_coalesced_at": coalesced_at.isoformat(),
                "runtime_trigger_submission_count": str(len(ordered)),
                "runtime_trigger_consumed_count": str(len(accepted_triggers)),
            },
        )

    def _consume_one(
        self,
        submission: ReevaluationRuntimeSubmissionResult,
        *,
        coalesced_at: datetime,
        consumed_submission_ids: tuple[str, ...],
    ) -> RuntimeTriggerCoalescingItemResult:
        submission_id = submission.request.submission_id
        if submission.outcome is not ReevaluationRuntimeSubmissionOutcome.ACCEPTED:
            return self._result(
                submission,
                coalesced_at=coalesced_at,
                outcome=RuntimeTriggerCoalescingOutcome.REJECTED,
                reason=RuntimeTriggerCoalescingReason.SUBMISSION_NOT_ACCEPTED,
                consumed_submission_ids=consumed_submission_ids,
            )
        if submission_id not in submission.accepted_submission_ids:
            return self._result(
                submission,
                coalesced_at=coalesced_at,
                outcome=RuntimeTriggerCoalescingOutcome.REJECTED,
                reason=RuntimeTriggerCoalescingReason.SUBMISSION_EVIDENCE_INVALID,
                consumed_submission_ids=consumed_submission_ids,
            )
        if submission.submitted_at > coalesced_at:
            return self._result(
                submission,
                coalesced_at=coalesced_at,
                outcome=RuntimeTriggerCoalescingOutcome.REJECTED,
                reason=RuntimeTriggerCoalescingReason.SUBMISSION_FROM_FUTURE,
                consumed_submission_ids=consumed_submission_ids,
            )
        if submission_id in consumed_submission_ids:
            return self._result(
                submission,
                coalesced_at=coalesced_at,
                outcome=RuntimeTriggerCoalescingOutcome.DUPLICATE,
                reason=RuntimeTriggerCoalescingReason.SUBMISSION_ALREADY_CONSUMED,
                consumed_submission_ids=consumed_submission_ids,
            )
        updated = tuple(sorted((*consumed_submission_ids, submission_id)))
        return self._result(
            submission,
            coalesced_at=coalesced_at,
            outcome=RuntimeTriggerCoalescingOutcome.CONSUMED,
            reason=RuntimeTriggerCoalescingReason.SUBMISSION_CONSUMED,
            consumed_submission_ids=updated,
        )

    def _result(
        self,
        submission: ReevaluationRuntimeSubmissionResult,
        *,
        coalesced_at: datetime,
        outcome: RuntimeTriggerCoalescingOutcome,
        reason: RuntimeTriggerCoalescingReason,
        consumed_submission_ids: tuple[str, ...],
    ) -> RuntimeTriggerCoalescingItemResult:
        result_id = _derived_id(
            "runtime-trigger-coalescing-result-",
            {
                "boundary_name": self.boundary_name,
                "coalesced_at": coalesced_at.isoformat(),
                "consumed_submission_ids": consumed_submission_ids,
                "outcome": outcome.value,
                "reason": reason.value,
                "submission_id": submission.request.submission_id,
                "submission_result_id": submission.result_id,
            },
        )
        return RuntimeTriggerCoalescingItemResult(
            result_id=result_id,
            outcome=outcome,
            reason=reason,
            submission_result=submission,
            coalesced_at=coalesced_at,
            consumed_submission_ids=consumed_submission_ids,
            provenance={
                "runtime_trigger_coalescing_result_id": result_id,
                "runtime_trigger_coalescing_boundary": self.boundary_name,
                "runtime_submission_id": submission.request.submission_id,
                "runtime_submission_result_id": submission.result_id,
                "runtime_trigger_coalescing_outcome": outcome.value,
                "runtime_trigger_coalescing_reason": reason.value,
            },
        )

    @staticmethod
    def _normalize_consumed_ids(values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(values)
        if any(not item.strip() for item in normalized):
            raise ValueError("consumed submission IDs must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("consumed submission IDs must be unique")
        return tuple(sorted(normalized))

    @staticmethod
    def _coalesced_payload(
        value: CoalescedEvaluationTrigger | None,
    ) -> object:
        if value is None:
            return None
        return {
            "primary": {
                "trigger": value.primary.trigger.value,
                "requested_at": value.primary.requested_at.isoformat(),
                "urgency": int(value.primary.urgency),
                "source": value.primary.source,
                "reason": value.primary.reason,
            },
            "requests": tuple(
                {
                    "trigger": request.trigger.value,
                    "requested_at": request.requested_at.isoformat(),
                    "urgency": int(request.urgency),
                    "source": request.source,
                    "reason": request.reason,
                }
                for request in value.requests
            ),
        }
