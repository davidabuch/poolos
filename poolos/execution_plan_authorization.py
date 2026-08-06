"""Deterministic, command-free authorization of constructed execution plans.

Epic 10.16E evaluates one successfully constructed execution plan against
explicit caller-supplied authorization evidence. It produces immutable
AUTHORIZED, DEFERRED, or REJECTED evidence and performs no scheduling,
dispatch, translation, delivery, Home Assistant call, vendor call, or physical
actuation.
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
from .execution_plan_constructor import (
    ExecutionPlanConstructionResult,
    ExecutionPlanConstructionStatus,
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


class ExecutionPlanAuthorizationDisposition(str, Enum):
    """Whether a constructed plan may proceed toward future scheduling."""

    AUTHORIZED = "authorized"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class ExecutionPlanAuthorizationReason(str, Enum):
    """Stable machine-readable authorization outcome reasons."""

    PLAN_AUTHORIZED = "plan_authorized"
    PLAN_DEFERRED = "plan_deferred"
    PLAN_REJECTED = "plan_rejected"
    CONSTRUCTION_NOT_ACCEPTED = "construction_not_accepted"
    CONSTRUCTION_EVIDENCE_INVALID = "construction_evidence_invalid"
    PLAN_IDENTITY_MISMATCH = "plan_identity_mismatch"


@dataclass(frozen=True, slots=True)
class ExecutionPlanAuthorizationRequest:
    """Explicit policy evidence for one constructed execution plan."""

    construction_result: ExecutionPlanConstructionResult
    evaluated_at: datetime
    blocking_reasons: tuple[str, ...] = ()
    deferral_reasons: tuple[str, ...] = ()
    policy_version: str = "1"
    correlation_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        blockers = tuple(self.blocking_reasons)
        deferrals = tuple(self.deferral_reasons)
        if any(not value.strip() for value in blockers):
            raise ValueError("blocking_reasons must not contain empty values")
        if any(not value.strip() for value in deferrals):
            raise ValueError("deferral_reasons must not contain empty values")
        if len(set(blockers)) != len(blockers):
            raise ValueError("blocking_reasons must be unique")
        if len(set(deferrals)) != len(deferrals):
            raise ValueError("deferral_reasons must be unique")
        if set(blockers) & set(deferrals):
            raise ValueError("blocking and deferral reasons must not overlap")
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "blocking_reasons", blockers)
        object.__setattr__(self, "deferral_reasons", deferrals)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanAuthorizationResult:
    """Immutable evidence from one execution-plan authorization decision."""

    authorization_id: str
    disposition: ExecutionPlanAuthorizationDisposition
    reason: ExecutionPlanAuthorizationReason
    evaluated_at: datetime
    construction_result: ExecutionPlanConstructionResult
    plan: ExecutionPlan | None
    blocking_reasons: tuple[str, ...] = ()
    deferral_reasons: tuple[str, ...] = ()
    policy_version: str = "1"
    correlation_id: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.disposition is ExecutionPlanAuthorizationDisposition.AUTHORIZED:
            if self.reason is not ExecutionPlanAuthorizationReason.PLAN_AUTHORIZED:
                raise ValueError("authorized result requires plan-authorized reason")
            if self.plan is None:
                raise ValueError("authorized result requires a plan")
            if self.blocking_reasons or self.deferral_reasons:
                raise ValueError("authorized result cannot contain policy reasons")
        elif self.plan is not None:
            raise ValueError("non-authorized result cannot expose an authorized plan")
        if self.disposition is ExecutionPlanAuthorizationDisposition.REJECTED:
            if not self.blocking_reasons:
                raise ValueError("rejected result requires blocking reasons")
        if self.disposition is ExecutionPlanAuthorizationDisposition.DEFERRED:
            if not self.deferral_reasons:
                raise ValueError("deferred result requires deferral reasons")
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "deferral_reasons", tuple(self.deferral_reasons))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanAuthorizer:
    """Authorize, defer, or reject one constructed plan deterministically."""

    boundary_name: str = "poolos.execution_plan_authorization"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def authorize(
        self,
        request: ExecutionPlanAuthorizationRequest,
    ) -> ExecutionPlanAuthorizationResult:
        """Evaluate explicit policy evidence without scheduling or execution."""

        construction = request.construction_result
        if construction.status is not ExecutionPlanConstructionStatus.CONSTRUCTED:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.REJECTED,
                reason=ExecutionPlanAuthorizationReason.CONSTRUCTION_NOT_ACCEPTED,
                blocking_reasons=("construction_not_accepted",),
            )

        plan = construction.plan
        if plan is None or construction.build_result is None:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.REJECTED,
                reason=ExecutionPlanAuthorizationReason.CONSTRUCTION_EVIDENCE_INVALID,
                blocking_reasons=("construction_evidence_invalid",),
            )

        plan_request = construction.plan_boundary_result.plan_request
        if plan_request is None:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.REJECTED,
                reason=ExecutionPlanAuthorizationReason.CONSTRUCTION_EVIDENCE_INVALID,
                blocking_reasons=("missing_plan_request_evidence",),
            )

        if plan.context_id != plan_request.context_id or plan.decision_id != plan_request.decision_id:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.REJECTED,
                reason=ExecutionPlanAuthorizationReason.PLAN_IDENTITY_MISMATCH,
                blocking_reasons=("plan_identity_mismatch",),
            )

        if request.blocking_reasons:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.REJECTED,
                reason=ExecutionPlanAuthorizationReason.PLAN_REJECTED,
                blocking_reasons=request.blocking_reasons,
            )

        if request.deferral_reasons:
            return self._result(
                request,
                disposition=ExecutionPlanAuthorizationDisposition.DEFERRED,
                reason=ExecutionPlanAuthorizationReason.PLAN_DEFERRED,
                deferral_reasons=request.deferral_reasons,
            )

        return self._result(
            request,
            disposition=ExecutionPlanAuthorizationDisposition.AUTHORIZED,
            reason=ExecutionPlanAuthorizationReason.PLAN_AUTHORIZED,
            plan=plan,
        )

    def _result(
        self,
        request: ExecutionPlanAuthorizationRequest,
        *,
        disposition: ExecutionPlanAuthorizationDisposition,
        reason: ExecutionPlanAuthorizationReason,
        plan: ExecutionPlan | None = None,
        blocking_reasons: tuple[str, ...] = (),
        deferral_reasons: tuple[str, ...] = (),
    ) -> ExecutionPlanAuthorizationResult:
        construction = request.construction_result
        source_plan = construction.plan
        authorization_id = _derived_id(
            "execution-plan-authorization-",
            {
                "blocking_reasons": "|".join(blocking_reasons),
                "boundary_name": self.boundary_name,
                "construction_id": construction.construction_id,
                "deferral_reasons": "|".join(deferral_reasons),
                "disposition": disposition.value,
                "plan_id": source_plan.plan_id if source_plan else "none",
                "policy_version": request.policy_version,
                "reason": reason.value,
            },
        )
        provenance = {
            **dict(construction.provenance),
            **dict(request.metadata),
            "execution_plan_authorization_boundary": self.boundary_name,
            "execution_plan_authorization_id": authorization_id,
            "execution_plan_authorization_disposition": disposition.value,
            "execution_plan_authorization_reason": reason.value,
            "execution_plan_authorization_policy_version": request.policy_version,
            "source_execution_plan_construction_id": construction.construction_id,
            "source_execution_plan_id": source_plan.plan_id if source_plan else "",
            "source_proposal_id": source_plan.proposal_id if source_plan else "",
            "source_decision_id": source_plan.decision_id if source_plan else "",
            "source_context_id": source_plan.context_id if source_plan else "",
            "source_correlation_id": request.correlation_id or "",
            "blocking_reasons": ",".join(blocking_reasons),
            "deferral_reasons": ",".join(deferral_reasons),
        }
        return ExecutionPlanAuthorizationResult(
            authorization_id=authorization_id,
            disposition=disposition,
            reason=reason,
            evaluated_at=request.evaluated_at,
            construction_result=construction,
            plan=plan,
            blocking_reasons=blocking_reasons,
            deferral_reasons=deferral_reasons,
            policy_version=request.policy_version,
            correlation_id=request.correlation_id,
            provenance=provenance,
        )
