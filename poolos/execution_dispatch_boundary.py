"""Deterministic, non-delivering dispatch preparation for scheduled plans.

Epic 10.16G converts one ready scheduled execution plan into immutable dispatch
request evidence. It performs no command translation, transport selection,
network operation, Home Assistant call, vendor call, delivery, verification, or
physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionPlan
from .execution_plan_scheduler import (
    ExecutionPlanScheduleDisposition,
    ExecutionPlanScheduleResult,
    ScheduledExecutionPlan,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = json.dumps(
        dict(sorted(payload.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


class ExecutionDispatchDisposition(str, Enum):
    """Outcome of one execution-dispatch boundary evaluation."""

    READY = "ready"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ExecutionDispatchReason(str, Enum):
    """Stable machine-readable dispatch-boundary outcome reasons."""

    DISPATCH_REQUEST_READY = "dispatch_request_ready"
    DISPATCH_DEFERRED = "dispatch_deferred"
    DISPATCH_CANCELLED = "dispatch_cancelled"
    SCHEDULE_NOT_READY = "schedule_not_ready"
    SCHEDULE_EVIDENCE_INVALID = "schedule_evidence_invalid"
    PLAN_IDENTITY_MISMATCH = "plan_identity_mismatch"
    DISPATCH_BEFORE_EXECUTION_TIME = "dispatch_before_execution_time"


@dataclass(frozen=True, slots=True)
class ExecutionDispatchBoundaryRequest:
    """Explicit dispatch-preparation evidence for one scheduled plan."""

    schedule_result: ExecutionPlanScheduleResult
    evaluated_at: datetime
    deferral_reasons: tuple[str, ...] = ()
    cancellation_reasons: tuple[str, ...] = ()
    dispatch_policy_version: str = "1"
    correlation_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        deferrals = tuple(self.deferral_reasons)
        cancellations = tuple(self.cancellation_reasons)
        if any(not value.strip() for value in deferrals):
            raise ValueError("deferral_reasons must not contain empty values")
        if any(not value.strip() for value in cancellations):
            raise ValueError("cancellation_reasons must not contain empty values")
        if len(set(deferrals)) != len(deferrals):
            raise ValueError("deferral_reasons must be unique")
        if len(set(cancellations)) != len(cancellations):
            raise ValueError("cancellation_reasons must be unique")
        if set(deferrals) & set(cancellations):
            raise ValueError("deferral and cancellation reasons must not overlap")
        if deferrals and cancellations:
            raise ValueError("dispatch cannot be deferred and cancelled together")
        if not self.dispatch_policy_version.strip():
            raise ValueError("dispatch_policy_version must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "deferral_reasons", deferrals)
        object.__setattr__(self, "cancellation_reasons", cancellations)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ExecutionDispatchRequest:
    """Immutable handoff request for future transport-independent dispatch."""

    dispatch_request_id: str
    schedule_id: str
    authorization_id: str
    plan: ExecutionPlan
    execute_at: datetime
    prepared_at: datetime
    correlation_id: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("dispatch_request_id", self.dispatch_request_id),
            ("schedule_id", self.schedule_id),
            ("authorization_id", self.authorization_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        _require_aware(self.execute_at, "execute_at")
        _require_aware(self.prepared_at, "prepared_at")
        if self.prepared_at < self.execute_at:
            raise ValueError("prepared_at cannot precede execute_at")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionDispatchBoundaryResult:
    """Immutable evidence from one dispatch-boundary evaluation."""

    result_id: str
    disposition: ExecutionDispatchDisposition
    reason: ExecutionDispatchReason
    evaluated_at: datetime
    schedule_result: ExecutionPlanScheduleResult
    dispatch_request: ExecutionDispatchRequest | None
    deferral_reasons: tuple[str, ...] = ()
    cancellation_reasons: tuple[str, ...] = ()
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.disposition is ExecutionDispatchDisposition.READY:
            if self.reason is not ExecutionDispatchReason.DISPATCH_REQUEST_READY:
                raise ValueError("ready result requires dispatch-request-ready reason")
            if self.dispatch_request is None:
                raise ValueError("ready result requires a dispatch request")
            if self.deferral_reasons or self.cancellation_reasons:
                raise ValueError("ready result cannot contain hold reasons")
        elif self.dispatch_request is not None:
            raise ValueError("non-ready result cannot contain a dispatch request")
        if self.disposition is ExecutionDispatchDisposition.DEFERRED:
            if not self.deferral_reasons:
                raise ValueError("deferred result requires deferral reasons")
        if self.disposition is ExecutionDispatchDisposition.CANCELLED:
            if not self.cancellation_reasons:
                raise ValueError("cancelled result requires cancellation reasons")
        object.__setattr__(self, "deferral_reasons", tuple(self.deferral_reasons))
        object.__setattr__(
            self, "cancellation_reasons", tuple(self.cancellation_reasons)
        )
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionDispatchBoundary:
    """Prepare immutable dispatch evidence without delivering any work."""

    boundary_name: str = "poolos.execution_dispatch_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self,
        request: ExecutionDispatchBoundaryRequest,
    ) -> ExecutionDispatchBoundaryResult:
        """Create one dispatch request only when scheduled work is due and valid."""

        schedule = request.schedule_result
        if schedule.disposition not in {
            ExecutionPlanScheduleDisposition.IMMEDIATE,
            ExecutionPlanScheduleDisposition.SCHEDULED,
        }:
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.REJECTED,
                reason=ExecutionDispatchReason.SCHEDULE_NOT_READY,
            )

        scheduled_plan = schedule.scheduled_plan
        if scheduled_plan is None:
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.REJECTED,
                reason=ExecutionDispatchReason.SCHEDULE_EVIDENCE_INVALID,
            )

        if not self._valid_schedule_evidence(schedule, scheduled_plan):
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.REJECTED,
                reason=ExecutionDispatchReason.SCHEDULE_EVIDENCE_INVALID,
            )

        plan = scheduled_plan.plan
        if plan.plan_id != scheduled_plan.provenance.get(
            "source_execution_plan_id", plan.plan_id
        ):
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.REJECTED,
                reason=ExecutionDispatchReason.PLAN_IDENTITY_MISMATCH,
            )

        if request.cancellation_reasons:
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.CANCELLED,
                reason=ExecutionDispatchReason.DISPATCH_CANCELLED,
                cancellation_reasons=request.cancellation_reasons,
            )

        if request.deferral_reasons:
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.DEFERRED,
                reason=ExecutionDispatchReason.DISPATCH_DEFERRED,
                deferral_reasons=request.deferral_reasons,
            )

        if request.evaluated_at < scheduled_plan.execute_at:
            return self._result(
                request,
                disposition=ExecutionDispatchDisposition.DEFERRED,
                reason=ExecutionDispatchReason.DISPATCH_BEFORE_EXECUTION_TIME,
                deferral_reasons=("execution_time_not_reached",),
            )

        dispatch_request_id = _derived_id(
            "execution-dispatch-request-",
            {
                "authorization_id": scheduled_plan.authorization_id,
                "boundary_name": self.boundary_name,
                "correlation_id": request.correlation_id or "",
                "dispatch_policy_version": request.dispatch_policy_version,
                "execute_at": scheduled_plan.execute_at.isoformat(),
                "plan_id": plan.plan_id,
                "schedule_id": scheduled_plan.schedule_id,
            },
        )
        dispatch_request = ExecutionDispatchRequest(
            dispatch_request_id=dispatch_request_id,
            schedule_id=scheduled_plan.schedule_id,
            authorization_id=scheduled_plan.authorization_id,
            plan=plan,
            execute_at=scheduled_plan.execute_at,
            prepared_at=request.evaluated_at,
            correlation_id=request.correlation_id,
            provenance={
                **dict(schedule.provenance),
                **dict(scheduled_plan.provenance),
                **dict(request.metadata),
                "execution_dispatch_boundary": self.boundary_name,
                "execution_dispatch_request_id": dispatch_request_id,
                "source_execution_plan_schedule_result_id": schedule.result_id,
                "source_execution_plan_schedule_id": scheduled_plan.schedule_id,
                "source_execution_plan_authorization_id": scheduled_plan.authorization_id,
                "source_execution_plan_id": plan.plan_id,
                "source_proposal_id": plan.proposal_id,
                "source_decision_id": plan.decision_id,
                "source_context_id": plan.context_id,
                "source_correlation_id": request.correlation_id or "",
            },
        )
        return self._result(
            request,
            disposition=ExecutionDispatchDisposition.READY,
            reason=ExecutionDispatchReason.DISPATCH_REQUEST_READY,
            dispatch_request=dispatch_request,
        )

    @staticmethod
    def _valid_schedule_evidence(
        schedule: ExecutionPlanScheduleResult,
        scheduled_plan: ScheduledExecutionPlan,
    ) -> bool:
        authorization = schedule.authorization_result
        return (
            scheduled_plan.plan is authorization.plan
            and scheduled_plan.authorization_id == authorization.authorization_id
            and scheduled_plan.disposition is schedule.disposition
            and scheduled_plan.schedule_id
            == schedule.provenance.get("execution_plan_schedule_id", scheduled_plan.schedule_id)
        )

    def _result(
        self,
        request: ExecutionDispatchBoundaryRequest,
        *,
        disposition: ExecutionDispatchDisposition,
        reason: ExecutionDispatchReason,
        dispatch_request: ExecutionDispatchRequest | None = None,
        deferral_reasons: tuple[str, ...] = (),
        cancellation_reasons: tuple[str, ...] = (),
    ) -> ExecutionDispatchBoundaryResult:
        schedule = request.schedule_result
        result_id = _derived_id(
            "execution-dispatch-boundary-result-",
            {
                "boundary_name": self.boundary_name,
                "cancellation_reasons": "|".join(cancellation_reasons),
                "deferral_reasons": "|".join(deferral_reasons),
                "dispatch_request_id": (
                    dispatch_request.dispatch_request_id
                    if dispatch_request is not None
                    else "none"
                ),
                "disposition": disposition.value,
                "reason": reason.value,
                "schedule_result_id": schedule.result_id,
            },
        )
        provenance = {
            **dict(schedule.provenance),
            **dict(request.metadata),
            **(
                dict(dispatch_request.provenance)
                if dispatch_request is not None
                else {}
            ),
            "execution_dispatch_boundary": self.boundary_name,
            "execution_dispatch_boundary_result_id": result_id,
            "execution_dispatch_disposition": disposition.value,
            "execution_dispatch_reason": reason.value,
            "execution_dispatch_request_id": (
                dispatch_request.dispatch_request_id
                if dispatch_request is not None
                else ""
            ),
            "deferral_reasons": ",".join(deferral_reasons),
            "cancellation_reasons": ",".join(cancellation_reasons),
        }
        return ExecutionDispatchBoundaryResult(
            result_id=result_id,
            disposition=disposition,
            reason=reason,
            evaluated_at=request.evaluated_at,
            schedule_result=schedule,
            dispatch_request=dispatch_request,
            deferral_reasons=deferral_reasons,
            cancellation_reasons=cancellation_reasons,
            provenance=provenance,
        )
