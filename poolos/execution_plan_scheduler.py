"""Deterministic, non-dispatching scheduling of authorized execution plans.

Epic 10.16F converts one authorized execution-plan result into immutable
immediate, scheduled, or deferred scheduling evidence. It reads no clock,
starts no timer, persists no work, dispatches no plan, translates no operation,
calls no integration or vendor, and actuates no equipment.
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
from .execution_plan_authorization import (
    ExecutionPlanAuthorizationDisposition,
    ExecutionPlanAuthorizationResult,
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


class ExecutionPlanScheduleDisposition(str, Enum):
    """Outcome of one deterministic execution-plan scheduling evaluation."""

    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class ExecutionPlanScheduleReason(str, Enum):
    """Stable machine-readable scheduling outcome reasons."""

    PLAN_READY_IMMEDIATELY = "plan_ready_immediately"
    PLAN_SCHEDULED = "plan_scheduled"
    PLAN_DEFERRED = "plan_deferred"
    AUTHORIZATION_NOT_ACCEPTED = "authorization_not_accepted"
    AUTHORIZATION_EVIDENCE_INVALID = "authorization_evidence_invalid"
    PLAN_IDENTITY_MISMATCH = "plan_identity_mismatch"
    EXECUTION_TIME_IN_PAST = "execution_time_in_past"


@dataclass(frozen=True, slots=True)
class ExecutionPlanScheduleRequest:
    """Explicit timing evidence for one authorized execution plan."""

    authorization_result: ExecutionPlanAuthorizationResult
    evaluated_at: datetime
    execute_at: datetime | None = None
    deferral_reasons: tuple[str, ...] = ()
    schedule_policy_version: str = "1"
    correlation_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.execute_at is not None:
            _require_aware(self.execute_at, "execute_at")
        deferrals = tuple(self.deferral_reasons)
        if any(not value.strip() for value in deferrals):
            raise ValueError("deferral_reasons must not contain empty values")
        if len(set(deferrals)) != len(deferrals):
            raise ValueError("deferral_reasons must be unique")
        if deferrals and self.execute_at is not None:
            raise ValueError("deferred scheduling cannot define execute_at")
        if not self.schedule_policy_version.strip():
            raise ValueError("schedule_policy_version must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "deferral_reasons", deferrals)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ScheduledExecutionPlan:
    """Immutable timing assignment for an authorized execution plan."""

    schedule_id: str
    authorization_id: str
    plan: ExecutionPlan
    execute_at: datetime
    disposition: ExecutionPlanScheduleDisposition
    correlation_id: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.schedule_id.strip():
            raise ValueError("schedule_id must not be empty")
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be empty")
        _require_aware(self.execute_at, "execute_at")
        if self.disposition not in {
            ExecutionPlanScheduleDisposition.IMMEDIATE,
            ExecutionPlanScheduleDisposition.SCHEDULED,
        }:
            raise ValueError("scheduled plan requires immediate or scheduled disposition")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanScheduleResult:
    """Immutable evidence from one scheduling evaluation."""

    result_id: str
    disposition: ExecutionPlanScheduleDisposition
    reason: ExecutionPlanScheduleReason
    evaluated_at: datetime
    authorization_result: ExecutionPlanAuthorizationResult
    scheduled_plan: ScheduledExecutionPlan | None
    deferral_reasons: tuple[str, ...] = ()
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.disposition in {
            ExecutionPlanScheduleDisposition.IMMEDIATE,
            ExecutionPlanScheduleDisposition.SCHEDULED,
        }:
            if self.scheduled_plan is None:
                raise ValueError("ready scheduling result requires a scheduled plan")
            if self.scheduled_plan.disposition is not self.disposition:
                raise ValueError("scheduled plan disposition must match result disposition")
            if self.deferral_reasons:
                raise ValueError("ready scheduling result cannot contain deferral reasons")
        elif self.scheduled_plan is not None:
            raise ValueError("deferred or rejected result cannot contain a scheduled plan")
        if self.disposition is ExecutionPlanScheduleDisposition.DEFERRED:
            if not self.deferral_reasons:
                raise ValueError("deferred result requires deferral reasons")
        object.__setattr__(self, "deferral_reasons", tuple(self.deferral_reasons))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanScheduler:
    """Assign deterministic timing without dispatching or persisting plans."""

    boundary_name: str = "poolos.execution_plan_scheduler"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def schedule(self, request: ExecutionPlanScheduleRequest) -> ExecutionPlanScheduleResult:
        """Return immutable schedule evidence without starting any work."""

        authorization = request.authorization_result
        if authorization.disposition is not ExecutionPlanAuthorizationDisposition.AUTHORIZED:
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.REJECTED,
                reason=ExecutionPlanScheduleReason.AUTHORIZATION_NOT_ACCEPTED,
            )

        plan = authorization.plan
        if plan is None:
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.REJECTED,
                reason=ExecutionPlanScheduleReason.AUTHORIZATION_EVIDENCE_INVALID,
            )

        construction_plan = authorization.construction_result.plan
        if construction_plan is None or construction_plan is not plan:
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.REJECTED,
                reason=ExecutionPlanScheduleReason.AUTHORIZATION_EVIDENCE_INVALID,
            )
        if plan.plan_id != authorization.provenance.get("source_execution_plan_id", plan.plan_id):
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.REJECTED,
                reason=ExecutionPlanScheduleReason.PLAN_IDENTITY_MISMATCH,
            )

        if request.deferral_reasons:
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.DEFERRED,
                reason=ExecutionPlanScheduleReason.PLAN_DEFERRED,
                deferral_reasons=request.deferral_reasons,
            )

        execute_at = request.execute_at or request.evaluated_at
        if execute_at < request.evaluated_at:
            return self._result(
                request,
                disposition=ExecutionPlanScheduleDisposition.REJECTED,
                reason=ExecutionPlanScheduleReason.EXECUTION_TIME_IN_PAST,
            )

        disposition = (
            ExecutionPlanScheduleDisposition.IMMEDIATE
            if execute_at == request.evaluated_at
            else ExecutionPlanScheduleDisposition.SCHEDULED
        )
        reason = (
            ExecutionPlanScheduleReason.PLAN_READY_IMMEDIATELY
            if disposition is ExecutionPlanScheduleDisposition.IMMEDIATE
            else ExecutionPlanScheduleReason.PLAN_SCHEDULED
        )
        schedule_id = _derived_id(
            "execution-plan-schedule-",
            {
                "authorization_id": authorization.authorization_id,
                "boundary_name": self.boundary_name,
                "correlation_id": request.correlation_id or "",
                "disposition": disposition.value,
                "execute_at": execute_at.isoformat(),
                "plan_id": plan.plan_id,
                "policy_version": request.schedule_policy_version,
            },
        )
        scheduled_plan = ScheduledExecutionPlan(
            schedule_id=schedule_id,
            authorization_id=authorization.authorization_id,
            plan=plan,
            execute_at=execute_at,
            disposition=disposition,
            correlation_id=request.correlation_id,
            provenance={
                **dict(authorization.provenance),
                **dict(request.metadata),
                "execution_plan_scheduler": self.boundary_name,
                "execution_plan_schedule_id": schedule_id,
                "execution_plan_schedule_disposition": disposition.value,
                "execution_plan_execute_at": execute_at.isoformat(),
                "source_execution_plan_authorization_id": authorization.authorization_id,
                "source_execution_plan_id": plan.plan_id,
                "source_proposal_id": plan.proposal_id,
                "source_decision_id": plan.decision_id,
                "source_context_id": plan.context_id,
                "source_correlation_id": request.correlation_id or "",
            },
        )
        return self._result(
            request,
            disposition=disposition,
            reason=reason,
            scheduled_plan=scheduled_plan,
        )

    def _result(
        self,
        request: ExecutionPlanScheduleRequest,
        *,
        disposition: ExecutionPlanScheduleDisposition,
        reason: ExecutionPlanScheduleReason,
        scheduled_plan: ScheduledExecutionPlan | None = None,
        deferral_reasons: tuple[str, ...] = (),
    ) -> ExecutionPlanScheduleResult:
        authorization = request.authorization_result
        result_id = _derived_id(
            "execution-plan-schedule-result-",
            {
                "authorization_id": authorization.authorization_id,
                "boundary_name": self.boundary_name,
                "deferral_reasons": "|".join(deferral_reasons),
                "disposition": disposition.value,
                "reason": reason.value,
                "schedule_id": scheduled_plan.schedule_id if scheduled_plan else "none",
            },
        )
        provenance = {
            **dict(authorization.provenance),
            **dict(request.metadata),
            **(dict(scheduled_plan.provenance) if scheduled_plan is not None else {}),
            "execution_plan_scheduler": self.boundary_name,
            "execution_plan_schedule_result_id": result_id,
            "execution_plan_schedule_disposition": disposition.value,
            "execution_plan_schedule_reason": reason.value,
            "execution_plan_schedule_id": (
                scheduled_plan.schedule_id if scheduled_plan is not None else ""
            ),
            "deferral_reasons": ",".join(deferral_reasons),
        }
        return ExecutionPlanScheduleResult(
            result_id=result_id,
            disposition=disposition,
            reason=reason,
            evaluated_at=request.evaluated_at,
            authorization_result=authorization,
            scheduled_plan=scheduled_plan,
            deferral_reasons=deferral_reasons,
            provenance=provenance,
        )
