"""Deterministic evidence boundary for future reevaluation runtime submission.

The boundary validates typed requests emitted by the due reevaluation trigger
architecture and returns immutable submission evidence.  It does not import or
invoke the runtime, construct evaluation contexts, enqueue work, or perform I/O.
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
from .reevaluation_trigger_boundary import (
    ReevaluationTriggerOutcome,
    ReevaluationTriggerReason,
    ReevaluationTriggerResult,
)


class ReevaluationRuntimeSubmissionOutcome(str, Enum):
    """Outcome of one side-effect-free runtime-submission evaluation."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class ReevaluationRuntimeSubmissionReason(str, Enum):
    """Stable machine-readable runtime-submission result reasons."""

    SUBMISSION_ACCEPTED = "submission_accepted"
    TRIGGER_EVIDENCE_INVALID = "trigger_evidence_invalid"
    TRIGGER_TYPE_UNSUPPORTED = "trigger_type_unsupported"
    TRIGGER_FROM_FUTURE = "trigger_from_future"
    PROVENANCE_INCONSISTENT = "provenance_inconsistent"
    SUBMISSION_ALREADY_ACCEPTED = "submission_already_accepted"


_OUTCOME_BY_REASON: Mapping[
    ReevaluationRuntimeSubmissionReason,
    ReevaluationRuntimeSubmissionOutcome,
] = MappingProxyType(
    {
        ReevaluationRuntimeSubmissionReason.SUBMISSION_ACCEPTED: (
            ReevaluationRuntimeSubmissionOutcome.ACCEPTED
        ),
        ReevaluationRuntimeSubmissionReason.TRIGGER_EVIDENCE_INVALID: (
            ReevaluationRuntimeSubmissionOutcome.REJECTED
        ),
        ReevaluationRuntimeSubmissionReason.TRIGGER_TYPE_UNSUPPORTED: (
            ReevaluationRuntimeSubmissionOutcome.REJECTED
        ),
        ReevaluationRuntimeSubmissionReason.TRIGGER_FROM_FUTURE: (
            ReevaluationRuntimeSubmissionOutcome.REJECTED
        ),
        ReevaluationRuntimeSubmissionReason.PROVENANCE_INCONSISTENT: (
            ReevaluationRuntimeSubmissionOutcome.REJECTED
        ),
        ReevaluationRuntimeSubmissionReason.SUBMISSION_ALREADY_ACCEPTED: (
            ReevaluationRuntimeSubmissionOutcome.DUPLICATE
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
class ReevaluationRuntimeSubmissionRequest:
    """Immutable typed trigger plus canonical reevaluation correlation evidence."""

    trigger_request: EvaluationTriggerRequest
    trigger_result_id: str
    schedule_request_id: str
    schedule_result_id: str
    action_id: str
    context_id: str
    decision_id: str | None
    correlation_id: str | None
    provenance: Mapping[str, str] = field(default_factory=dict)
    submission_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_aware(self.trigger_request.requested_at, "trigger requested_at")
        for field_name, value in (
            ("trigger_result_id", self.trigger_result_id),
            ("schedule_request_id", self.schedule_request_id),
            ("schedule_result_id", self.schedule_result_id),
            ("action_id", self.action_id),
            ("context_id", self.context_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.decision_id is not None and not self.decision_id.strip():
            raise ValueError("decision_id must not be empty when provided")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.provenance.items()
        ):
            raise ValueError("submission provenance must contain string pairs")
        provenance = MappingProxyType(dict(self.provenance))
        identity_payload = {
            "action_id": self.action_id,
            "context_id": self.context_id,
            "correlation_id": self.correlation_id,
            "decision_id": self.decision_id,
            "provenance": dict(sorted(provenance.items())),
            "schedule_request_id": self.schedule_request_id,
            "schedule_result_id": self.schedule_result_id,
            "trigger": self.trigger_request.trigger.value,
            "trigger_reason": self.trigger_request.reason,
            "trigger_requested_at": self.trigger_request.requested_at.isoformat(),
            "trigger_result_id": self.trigger_result_id,
            "trigger_source": self.trigger_request.source,
            "trigger_urgency": int(self.trigger_request.urgency),
        }
        submission_id = _derived_id(
            "reevaluation-runtime-submission-", identity_payload
        )
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "submission_id", submission_id)

    @classmethod
    def from_trigger_result(
        cls,
        result: ReevaluationTriggerResult,
    ) -> ReevaluationRuntimeSubmissionRequest:
        """Build a submission request from one emitted ADR-046 result."""

        if result.trigger_request is None:
            raise ValueError("submission requests require emitted trigger evidence")
        schedule = result.schedule_result
        action = schedule.request.receipt.pipeline_result.action
        return cls(
            trigger_request=result.trigger_request,
            trigger_result_id=result.emission_id,
            schedule_request_id=schedule.request_id,
            schedule_result_id=schedule.result_id,
            action_id=action.action_id,
            context_id=action.context_id,
            decision_id=action.decision_id,
            correlation_id=action.correlation_id,
            provenance=result.provenance,
        )


@dataclass(frozen=True, slots=True)
class ReevaluationRuntimeSubmissionResult:
    """Immutable evidence for one runtime-submission validation attempt."""

    result_id: str
    outcome: ReevaluationRuntimeSubmissionOutcome
    reason: ReevaluationRuntimeSubmissionReason
    request: ReevaluationRuntimeSubmissionRequest
    submitted_at: datetime
    accepted_submission_ids: tuple[str, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        _require_aware(self.submitted_at, "submitted_at")
        if _OUTCOME_BY_REASON[self.reason] is not self.outcome:
            raise ValueError("submission reason must match its outcome")
        accepted_ids = tuple(self.accepted_submission_ids)
        if any(not submission_id.strip() for submission_id in accepted_ids):
            raise ValueError("accepted submission IDs must not be empty")
        if len(set(accepted_ids)) != len(accepted_ids):
            raise ValueError("accepted submission IDs must be unique")
        if accepted_ids != tuple(sorted(accepted_ids)):
            raise ValueError("accepted submission IDs must be sorted")
        if (
            self.outcome is ReevaluationRuntimeSubmissionOutcome.ACCEPTED
            and self.request.submission_id not in accepted_ids
        ):
            raise ValueError("accepted result must record its submission identity")
        if (
            self.outcome is ReevaluationRuntimeSubmissionOutcome.REJECTED
            and self.request.submission_id in accepted_ids
        ):
            raise ValueError("rejected result cannot accept its submission identity")
        if (
            self.outcome is ReevaluationRuntimeSubmissionOutcome.DUPLICATE
            and self.request.submission_id not in accepted_ids
        ):
            raise ValueError("duplicate result requires prior acceptance evidence")
        object.__setattr__(self, "accepted_submission_ids", accepted_ids)
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )


@dataclass(frozen=True, slots=True)
class ReevaluationRuntimeSubmissionBatch:
    """Immutable ordered result of validating a submission-request batch."""

    batch_id: str
    submitted_at: datetime
    results: tuple[ReevaluationRuntimeSubmissionResult, ...]
    accepted_submission_ids: tuple[str, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must not be empty")
        _require_aware(self.submitted_at, "submitted_at")
        results = tuple(self.results)
        accepted_ids = tuple(self.accepted_submission_ids)
        if any(not submission_id.strip() for submission_id in accepted_ids):
            raise ValueError("accepted submission IDs must not be empty")
        if len(set(accepted_ids)) != len(accepted_ids):
            raise ValueError("accepted submission IDs must be unique")
        if accepted_ids != tuple(sorted(accepted_ids)):
            raise ValueError("accepted submission IDs must be sorted")
        if results and results[-1].accepted_submission_ids != accepted_ids:
            raise ValueError("batch acceptance evidence must match its final result")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "accepted_submission_ids", accepted_ids)
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    @property
    def accepted_trigger_requests(self) -> tuple[EvaluationTriggerRequest, ...]:
        """Return validated requests without submitting them to any runtime."""

        return tuple(
            result.request.trigger_request
            for result in self.results
            if result.outcome is ReevaluationRuntimeSubmissionOutcome.ACCEPTED
        )


@dataclass(frozen=True, slots=True)
class ReevaluationRuntimeSubmissionBoundary:
    """Validate future runtime submissions without invoking the runtime."""

    boundary_name: str = "poolos.reevaluation_runtime_submission_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def submit(
        self,
        requests: tuple[ReevaluationRuntimeSubmissionRequest, ...],
        *,
        submitted_at: datetime,
        accepted_submission_ids: tuple[str, ...] = (),
    ) -> ReevaluationRuntimeSubmissionBatch:
        """Return deterministic acceptance evidence without runtime side effects."""

        _require_aware(submitted_at, "submitted_at")
        if not requests:
            raise ValueError("at least one runtime-submission request is required")
        accepted = self._normalize_accepted_ids(accepted_submission_ids)
        initial_accepted = accepted
        ordered = tuple(
            sorted(
                requests,
                key=lambda request: (
                    request.trigger_request.requested_at,
                    request.submission_id,
                ),
            )
        )
        results: list[ReevaluationRuntimeSubmissionResult] = []
        for request in ordered:
            result = self._submit_one(
                request,
                submitted_at=submitted_at,
                accepted_submission_ids=accepted,
            )
            accepted = result.accepted_submission_ids
            results.append(result)

        batch_id = _derived_id(
            "reevaluation-runtime-submission-batch-",
            {
                "boundary_name": self.boundary_name,
                "initial_accepted_submission_ids": initial_accepted,
                "result_ids": tuple(result.result_id for result in results),
                "submitted_at": submitted_at.isoformat(),
            },
        )
        return ReevaluationRuntimeSubmissionBatch(
            batch_id=batch_id,
            submitted_at=submitted_at,
            results=tuple(results),
            accepted_submission_ids=accepted,
            provenance={
                "reevaluation_submission_batch_id": batch_id,
                "reevaluation_submission_boundary": self.boundary_name,
                "reevaluation_submission_submitted_at": submitted_at.isoformat(),
                "reevaluation_submission_request_count": str(len(ordered)),
                "reevaluation_submission_accepted_count": str(
                    sum(
                        result.outcome
                        is ReevaluationRuntimeSubmissionOutcome.ACCEPTED
                        for result in results
                    )
                ),
            },
        )

    def _submit_one(
        self,
        request: ReevaluationRuntimeSubmissionRequest,
        *,
        submitted_at: datetime,
        accepted_submission_ids: tuple[str, ...],
    ) -> ReevaluationRuntimeSubmissionResult:
        trigger = request.trigger_request
        if trigger.trigger is not EvaluationTrigger.EXPECTED_CHANGE_REACHED:
            return self._result(
                request,
                submitted_at=submitted_at,
                outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED,
                reason=(
                    ReevaluationRuntimeSubmissionReason.TRIGGER_TYPE_UNSUPPORTED
                ),
                accepted_submission_ids=accepted_submission_ids,
            )
        if (
            trigger.urgency is not TriggerUrgency.NORMAL
            or not trigger.reason.startswith("Scheduled expected change reached: ")
        ):
            return self._result(
                request,
                submitted_at=submitted_at,
                outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED,
                reason=ReevaluationRuntimeSubmissionReason.TRIGGER_EVIDENCE_INVALID,
                accepted_submission_ids=accepted_submission_ids,
            )
        if trigger.requested_at > submitted_at:
            return self._result(
                request,
                submitted_at=submitted_at,
                outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED,
                reason=ReevaluationRuntimeSubmissionReason.TRIGGER_FROM_FUTURE,
                accepted_submission_ids=accepted_submission_ids,
            )
        if not self._has_consistent_provenance(request):
            return self._result(
                request,
                submitted_at=submitted_at,
                outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED,
                reason=ReevaluationRuntimeSubmissionReason.PROVENANCE_INCONSISTENT,
                accepted_submission_ids=accepted_submission_ids,
            )
        if request.submission_id in accepted_submission_ids:
            return self._result(
                request,
                submitted_at=submitted_at,
                outcome=ReevaluationRuntimeSubmissionOutcome.DUPLICATE,
                reason=(
                    ReevaluationRuntimeSubmissionReason.SUBMISSION_ALREADY_ACCEPTED
                ),
                accepted_submission_ids=accepted_submission_ids,
            )
        updated_accepted = tuple(
            sorted((*accepted_submission_ids, request.submission_id))
        )
        return self._result(
            request,
            submitted_at=submitted_at,
            outcome=ReevaluationRuntimeSubmissionOutcome.ACCEPTED,
            reason=ReevaluationRuntimeSubmissionReason.SUBMISSION_ACCEPTED,
            accepted_submission_ids=updated_accepted,
        )

    @staticmethod
    def _has_consistent_provenance(
        request: ReevaluationRuntimeSubmissionRequest,
    ) -> bool:
        trigger = request.trigger_request
        expected = {
            "reevaluation_trigger_result_id": request.trigger_result_id,
            "reevaluation_trigger_boundary": trigger.source,
            "reevaluation_trigger_outcome": ReevaluationTriggerOutcome.EMITTED.value,
            "reevaluation_trigger_reason": ReevaluationTriggerReason.TRIGGER_EMITTED.value,
            "reevaluation_trigger_evaluated_at": trigger.requested_at.isoformat(),
            "reevaluation_trigger_type": trigger.trigger.value,
            "reevaluation_request_id": request.schedule_request_id,
            "reevaluation_result_id": request.schedule_result_id,
            "source_action_id": request.action_id,
            "source_context_id": request.context_id,
            "source_decision_id": request.decision_id or "",
            "source_correlation_id": request.correlation_id or "",
        }
        if request.correlation_id is None:
            return False
        if any(request.provenance.get(key) != value for key, value in expected.items()):
            return False
        hint = request.provenance.get("reevaluation_hint")
        return (
            hint is not None
            and bool(hint.strip())
            and trigger.reason == f"Scheduled expected change reached: {hint}"
        )

    def _result(
        self,
        request: ReevaluationRuntimeSubmissionRequest,
        *,
        submitted_at: datetime,
        outcome: ReevaluationRuntimeSubmissionOutcome,
        reason: ReevaluationRuntimeSubmissionReason,
        accepted_submission_ids: tuple[str, ...],
    ) -> ReevaluationRuntimeSubmissionResult:
        result_id = _derived_id(
            "reevaluation-runtime-submission-result-",
            {
                "accepted_submission_ids": accepted_submission_ids,
                "boundary_name": self.boundary_name,
                "outcome": outcome.value,
                "reason": reason.value,
                "submission_id": request.submission_id,
                "submitted_at": submitted_at.isoformat(),
            },
        )
        return ReevaluationRuntimeSubmissionResult(
            result_id=result_id,
            outcome=outcome,
            reason=reason,
            request=request,
            submitted_at=submitted_at,
            accepted_submission_ids=accepted_submission_ids,
            provenance={
                **dict(request.provenance),
                "reevaluation_submission_id": request.submission_id,
                "reevaluation_submission_result_id": result_id,
                "reevaluation_submission_boundary": self.boundary_name,
                "reevaluation_submission_outcome": outcome.value,
                "reevaluation_submission_reason": reason.value,
                "reevaluation_submission_submitted_at": submitted_at.isoformat(),
            },
        )

    @staticmethod
    def _normalize_accepted_ids(
        submission_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(submission_ids)
        if any(not submission_id.strip() for submission_id in normalized):
            raise ValueError("accepted submission IDs must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("accepted submission IDs must be unique")
        return tuple(sorted(normalized))
