"""Deterministic, in-memory scheduling boundary for PoolOS reevaluation.

This module consumes immutable deferred downstream receipts and records future
reevaluation requests.  It uses caller-supplied time, performs no evaluation or
execution itself, and has no hardware, vendor, transport, or Home Assistant
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .downstream_operational_action_adapter import (
    DownstreamOperationalActionOutcome,
    DownstreamOperationalActionReason,
    DownstreamOperationalActionReceipt,
)
from .operational_action_pipeline import (
    OperationalActionPipelineReason,
    OperationalActionPipelineStatus,
)
from .operational_disposition_orchestrator import OperationalAction, OperationalTarget


class ReevaluationScheduleOutcome(str, Enum):
    """Outcome of one deterministic reevaluation scheduling operation."""

    SCHEDULED = "scheduled"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    CANCELLED = "cancelled"


class ReevaluationScheduleReason(str, Enum):
    """Stable machine-readable scheduling result reasons."""

    SCHEDULE_ACCEPTED = "schedule_accepted"
    RECEIPT_NOT_DEFERRED = "receipt_not_deferred"
    RECEIPT_ROUTE_INVALID = "receipt_route_invalid"
    SCHEDULE_TIME_INVALID = "schedule_time_invalid"
    REQUEST_ALREADY_SCHEDULED = "request_already_scheduled"
    REQUEST_NOT_SCHEDULED = "request_not_scheduled"
    CANCELLATION_PRECEDES_SCHEDULE = "cancellation_precedes_schedule"
    CANCELLED_BY_REQUEST = "cancelled_by_request"
    REQUEST_ALREADY_CANCELLED = "request_already_cancelled"


_OUTCOME_BY_REASON: Mapping[
    ReevaluationScheduleReason,
    ReevaluationScheduleOutcome,
] = MappingProxyType(
    {
        ReevaluationScheduleReason.SCHEDULE_ACCEPTED: (
            ReevaluationScheduleOutcome.SCHEDULED
        ),
        ReevaluationScheduleReason.RECEIPT_NOT_DEFERRED: (
            ReevaluationScheduleOutcome.REJECTED
        ),
        ReevaluationScheduleReason.RECEIPT_ROUTE_INVALID: (
            ReevaluationScheduleOutcome.REJECTED
        ),
        ReevaluationScheduleReason.SCHEDULE_TIME_INVALID: (
            ReevaluationScheduleOutcome.REJECTED
        ),
        ReevaluationScheduleReason.REQUEST_ALREADY_SCHEDULED: (
            ReevaluationScheduleOutcome.DUPLICATE
        ),
        ReevaluationScheduleReason.REQUEST_NOT_SCHEDULED: (
            ReevaluationScheduleOutcome.REJECTED
        ),
        ReevaluationScheduleReason.CANCELLATION_PRECEDES_SCHEDULE: (
            ReevaluationScheduleOutcome.REJECTED
        ),
        ReevaluationScheduleReason.CANCELLED_BY_REQUEST: (
            ReevaluationScheduleOutcome.CANCELLED
        ),
        ReevaluationScheduleReason.REQUEST_ALREADY_CANCELLED: (
            ReevaluationScheduleOutcome.DUPLICATE
        ),
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReevaluationScheduleRequest:
    """Immutable request to record one future reevaluation."""

    receipt: DownstreamOperationalActionReceipt
    requested_at: datetime
    scheduled_for: datetime
    request_id: str = field(init=False)
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.scheduled_for, "scheduled_for")
        identity_payload = {
            "action_id": self.receipt.action_id,
            "receipt_id": self.receipt.receipt_id,
            "reevaluation_hint": self.receipt.pipeline_result.action.reevaluation_hint,
            "requested_at": self.requested_at.isoformat(),
            "scheduled_for": self.scheduled_for.isoformat(),
        }
        request_id = "reevaluation-request-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def action_id(self) -> str:
        """Return the canonical operational-action identity."""

        return self.receipt.action_id

    @property
    def context_id(self) -> str:
        """Return the source operational-context identity."""

        return self.receipt.context_id

    @property
    def decision_id(self) -> str | None:
        """Return the source decision identity when one exists."""

        return self.receipt.decision_id

    @property
    def correlation_id(self) -> str | None:
        """Return the source correlation identity when one exists."""

        return self.receipt.correlation_id


@dataclass(frozen=True, slots=True)
class ReevaluationScheduleResult:
    """Immutable evidence for one scheduling or cancellation operation."""

    result_id: str
    outcome: ReevaluationScheduleOutcome
    reason: ReevaluationScheduleReason
    request: ReevaluationScheduleRequest
    processed_at: datetime
    cancellation_reason: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        _require_aware(self.processed_at, "processed_at")
        if _OUTCOME_BY_REASON[self.reason] is not self.outcome:
            raise ValueError("schedule reason must match its outcome")
        if self.outcome is ReevaluationScheduleOutcome.CANCELLED:
            if self.cancellation_reason is None or not self.cancellation_reason.strip():
                raise ValueError("cancelled result requires a cancellation reason")
        elif self.cancellation_reason is not None:
            raise ValueError("only cancelled results may include a cancellation reason")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def request_id(self) -> str:
        return self.request.request_id

    @property
    def scheduled_for(self) -> datetime:
        return self.request.scheduled_for


@dataclass(slots=True)
class DeterministicReevaluationScheduler:
    """Record and cancel reevaluations without invoking an evaluation runtime."""

    scheduler_name: str = "poolos.deterministic_reevaluation_scheduler"
    _records: dict[str, ReevaluationScheduleResult] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.scheduler_name.strip():
            raise ValueError("scheduler_name must not be empty")

    def schedule(
        self,
        request: ReevaluationScheduleRequest,
        *,
        processed_at: datetime,
    ) -> ReevaluationScheduleResult:
        """Record one valid future reevaluation or return fail-closed evidence."""

        _require_aware(processed_at, "processed_at")
        existing = self._records.get(request.request_id)
        if existing is not None:
            return self._result(
                request,
                processed_at=processed_at,
                outcome=ReevaluationScheduleOutcome.DUPLICATE,
                reason=(
                    ReevaluationScheduleReason.REQUEST_ALREADY_CANCELLED
                    if existing.outcome is ReevaluationScheduleOutcome.CANCELLED
                    else ReevaluationScheduleReason.REQUEST_ALREADY_SCHEDULED
                ),
            )

        receipt_reason = self._validate_receipt(request.receipt)
        if receipt_reason is not None:
            return self._result(
                request,
                processed_at=processed_at,
                outcome=ReevaluationScheduleOutcome.REJECTED,
                reason=receipt_reason,
            )

        if (
            processed_at < request.requested_at
            or request.scheduled_for < request.requested_at
            or request.scheduled_for < processed_at
        ):
            return self._result(
                request,
                processed_at=processed_at,
                outcome=ReevaluationScheduleOutcome.REJECTED,
                reason=ReevaluationScheduleReason.SCHEDULE_TIME_INVALID,
            )

        result = self._result(
            request,
            processed_at=processed_at,
            outcome=ReevaluationScheduleOutcome.SCHEDULED,
            reason=ReevaluationScheduleReason.SCHEDULE_ACCEPTED,
        )
        self._records[request.request_id] = result
        return result

    def cancel(
        self,
        request: ReevaluationScheduleRequest,
        *,
        cancelled_at: datetime,
        cancellation_reason: str,
    ) -> ReevaluationScheduleResult:
        """Cancel one existing request without triggering or evaluating it."""

        _require_aware(cancelled_at, "cancelled_at")
        if not cancellation_reason.strip():
            raise ValueError("cancellation_reason must not be empty")
        existing = self._records.get(request.request_id)
        if existing is None:
            return self._result(
                request,
                processed_at=cancelled_at,
                outcome=ReevaluationScheduleOutcome.REJECTED,
                reason=ReevaluationScheduleReason.REQUEST_NOT_SCHEDULED,
            )
        if existing.outcome is ReevaluationScheduleOutcome.CANCELLED:
            return self._result(
                request,
                processed_at=cancelled_at,
                outcome=ReevaluationScheduleOutcome.DUPLICATE,
                reason=ReevaluationScheduleReason.REQUEST_ALREADY_CANCELLED,
            )
        if cancelled_at < existing.processed_at:
            return self._result(
                request,
                processed_at=cancelled_at,
                outcome=ReevaluationScheduleOutcome.REJECTED,
                reason=ReevaluationScheduleReason.CANCELLATION_PRECEDES_SCHEDULE,
            )
        result = self._result(
            request,
            processed_at=cancelled_at,
            outcome=ReevaluationScheduleOutcome.CANCELLED,
            reason=ReevaluationScheduleReason.CANCELLED_BY_REQUEST,
            cancellation_reason=cancellation_reason,
        )
        self._records[request.request_id] = result
        return result

    def get(self, request_id: str) -> ReevaluationScheduleResult | None:
        """Return the latest immutable record for a request identity."""

        if not request_id.strip():
            raise ValueError("request_id must not be empty")
        return self._records.get(request_id)

    @property
    def records(self) -> tuple[ReevaluationScheduleResult, ...]:
        """Return current records in deterministic request-identity order."""

        return tuple(self._records[key] for key in sorted(self._records))

    @staticmethod
    def _validate_receipt(
        receipt: DownstreamOperationalActionReceipt,
    ) -> ReevaluationScheduleReason | None:
        if (
            receipt.outcome is not DownstreamOperationalActionOutcome.DEFERRED
            or receipt.reason
            is not DownstreamOperationalActionReason.REEVALUATION_DEFERRED
        ):
            return ReevaluationScheduleReason.RECEIPT_NOT_DEFERRED

        pipeline_result = receipt.pipeline_result
        action = pipeline_result.action
        if (
            pipeline_result.status is not OperationalActionPipelineStatus.ACCEPTED
            or pipeline_result.reason
            is not OperationalActionPipelineReason.ROUTE_ACCEPTED
            or action.action_id not in pipeline_result.accepted_action_ids
            or pipeline_result.routed_target
            is not OperationalTarget.REEVALUATION_SCHEDULER
            or pipeline_result.boundary_name != "reevaluation_scheduler"
            or action.action is not OperationalAction.REQUEST_REEVALUATION
            or action.target is not OperationalTarget.REEVALUATION_SCHEDULER
            or action.reevaluation_hint is None
            or not action.reevaluation_hint.strip()
        ):
            return ReevaluationScheduleReason.RECEIPT_ROUTE_INVALID
        return None

    def _result(
        self,
        request: ReevaluationScheduleRequest,
        *,
        processed_at: datetime,
        outcome: ReevaluationScheduleOutcome,
        reason: ReevaluationScheduleReason,
        cancellation_reason: str | None = None,
    ) -> ReevaluationScheduleResult:
        identity_payload = {
            "cancellation_reason": cancellation_reason,
            "outcome": outcome.value,
            "processed_at": processed_at.isoformat(),
            "reason": reason.value,
            "request_id": request.request_id,
            "scheduler_name": self.scheduler_name,
        }
        result_id = "reevaluation-schedule-result-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        action = request.receipt.pipeline_result.action
        provenance = {
            **dict(request.receipt.provenance),
            **dict(request.provenance),
            "reevaluation_request_id": request.request_id,
            "reevaluation_result_id": result_id,
            "reevaluation_schedule_outcome": outcome.value,
            "reevaluation_schedule_reason": reason.value,
            "reevaluation_scheduler": self.scheduler_name,
            "reevaluation_requested_at": request.requested_at.isoformat(),
            "reevaluation_scheduled_for": request.scheduled_for.isoformat(),
            "reevaluation_processed_at": processed_at.isoformat(),
            "reevaluation_hint": action.reevaluation_hint or "",
        }
        return ReevaluationScheduleResult(
            result_id=result_id,
            outcome=outcome,
            reason=reason,
            request=request,
            processed_at=processed_at,
            cancellation_reason=cancellation_reason,
            provenance=provenance,
        )
