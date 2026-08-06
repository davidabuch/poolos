"""Deterministic construction of one canonical authorized execution plan.

Epic 10.16D validates accepted execution-plan request evidence and delegates
plan construction to the existing deterministic execution-plan builder. The
constructor does not authorize proposals, schedule work, mutate runtime state,
deliver commands, call Home Assistant or vendors, or actuate equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionPlan
from .execution_plan_boundary import (
    ExecutionPlanBoundaryResult,
    ExecutionPlanBoundaryStatus,
)
from .execution_plans import (
    DeterministicExecutionPlanBuilder,
    ExecutionPlanBuildRequest,
    ExecutionPlanBuildResult,
    PlanBuildDisposition,
)


class ExecutionPlanConstructionStatus(str, Enum):
    """Outcome of one canonical execution-plan construction attempt."""

    CONSTRUCTED = "constructed"
    REJECTED = "rejected"


class ExecutionPlanConstructionReason(str, Enum):
    """Stable machine-readable construction outcome reasons."""

    PLAN_CONSTRUCTED = "plan_constructed"
    PLAN_REQUEST_NOT_ACCEPTED = "plan_request_not_accepted"
    PLAN_REQUEST_EVIDENCE_INVALID = "plan_request_evidence_invalid"
    BUILD_REQUEST_MISMATCH = "build_request_mismatch"
    BUILDER_REJECTED = "builder_rejected"


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = json.dumps(
        dict(sorted(payload.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ExecutionPlanConstructionResult:
    """Immutable evidence from one execution-plan construction attempt."""

    construction_id: str
    status: ExecutionPlanConstructionStatus
    reason: ExecutionPlanConstructionReason
    plan_boundary_result: ExecutionPlanBoundaryResult
    build_result: ExecutionPlanBuildResult | None
    plan: ExecutionPlan | None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.construction_id.strip():
            raise ValueError("construction_id must not be empty")
        if self.status is ExecutionPlanConstructionStatus.CONSTRUCTED:
            if self.reason is not ExecutionPlanConstructionReason.PLAN_CONSTRUCTED:
                raise ValueError("constructed result requires plan-constructed reason")
            if self.build_result is None or self.plan is None:
                raise ValueError("constructed result requires build evidence and a plan")
            if self.build_result.disposition is not PlanBuildDisposition.BUILT:
                raise ValueError("constructed result requires a built build result")
            if self.build_result.plan is not self.plan:
                raise ValueError("constructed result must preserve the built plan")
            plan_request = self.plan_boundary_result.plan_request
            if plan_request is None:
                raise ValueError("constructed result requires plan-request evidence")
            if self.plan.decision_id != plan_request.decision_id:
                raise ValueError("constructed plan must preserve decision identity")
            if self.plan.context_id != plan_request.context_id:
                raise ValueError("constructed plan must preserve context identity")
        elif self.plan is not None:
            raise ValueError("rejected result cannot contain a plan")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanConstructor:
    """Validate plan-request evidence and delegate deterministic construction."""

    builder: DeterministicExecutionPlanBuilder = field(
        default_factory=DeterministicExecutionPlanBuilder
    )
    boundary_name: str = "poolos.execution_plan_constructor"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def construct(
        self,
        plan_boundary_result: ExecutionPlanBoundaryResult,
        build_request: ExecutionPlanBuildRequest,
    ) -> ExecutionPlanConstructionResult:
        """Construct one authorized canonical plan without executing it."""

        if plan_boundary_result.status is not ExecutionPlanBoundaryStatus.ACCEPTED:
            return self._result(
                plan_boundary_result,
                reason=ExecutionPlanConstructionReason.PLAN_REQUEST_NOT_ACCEPTED,
                build_result=None,
                plan=None,
            )

        plan_request = plan_boundary_result.plan_request
        if plan_request is None:
            return self._result(
                plan_boundary_result,
                reason=ExecutionPlanConstructionReason.PLAN_REQUEST_EVIDENCE_INVALID,
                build_result=None,
                plan=None,
            )

        proposal = build_request.proposal
        source_proposal_request_id = proposal.metadata.get(
            "source_proposal_request_id"
        )
        if (
            plan_request.context_id != proposal.context_id
            or plan_request.decision_id != proposal.decision_id
            or source_proposal_request_id != plan_request.proposal_request_id
        ):
            return self._result(
                plan_boundary_result,
                reason=ExecutionPlanConstructionReason.BUILD_REQUEST_MISMATCH,
                build_result=None,
                plan=None,
            )

        build_result = self.builder.build(build_request)
        if (
            build_result.disposition is not PlanBuildDisposition.BUILT
            or build_result.plan is None
        ):
            return self._result(
                plan_boundary_result,
                reason=ExecutionPlanConstructionReason.BUILDER_REJECTED,
                build_result=build_result,
                plan=None,
            )

        return self._result(
            plan_boundary_result,
            reason=ExecutionPlanConstructionReason.PLAN_CONSTRUCTED,
            build_result=build_result,
            plan=build_result.plan,
        )

    def _result(
        self,
        plan_boundary_result: ExecutionPlanBoundaryResult,
        *,
        reason: ExecutionPlanConstructionReason,
        build_result: ExecutionPlanBuildResult | None,
        plan: ExecutionPlan | None,
    ) -> ExecutionPlanConstructionResult:
        status = (
            ExecutionPlanConstructionStatus.CONSTRUCTED
            if reason is ExecutionPlanConstructionReason.PLAN_CONSTRUCTED
            else ExecutionPlanConstructionStatus.REJECTED
        )
        plan_request = plan_boundary_result.plan_request
        construction_id = _derived_id(
            "execution-plan-construction-",
            {
                "boundary_name": self.boundary_name,
                "build_authorization_id": (
                    build_result.authorization_id if build_result else "none"
                ),
                "build_proposal_id": build_result.proposal_id if build_result else "none",
                "plan_boundary_result_id": plan_boundary_result.result_id,
                "plan_id": plan.plan_id if plan else "none",
                "plan_request_id": (
                    plan_request.plan_request_id if plan_request else "none"
                ),
                "reason": reason.value,
                "status": status.value,
            },
        )
        provenance = {
            **dict(plan_boundary_result.provenance),
            "execution_plan_constructor": self.boundary_name,
            "execution_plan_construction_id": construction_id,
            "execution_plan_construction_status": status.value,
            "execution_plan_construction_reason": reason.value,
            "execution_plan_id": plan.plan_id if plan else "",
            "source_plan_boundary_result_id": plan_boundary_result.result_id,
            "source_plan_request_id": plan_request.plan_request_id if plan_request else "",
            "source_proposal_id": build_result.proposal_id if build_result else "",
            "source_authorization_id": (
                build_result.authorization_id if build_result else ""
            ),
            "builder_reasons": (
                ",".join(build_result.reasons) if build_result else ""
            ),
        }
        return ExecutionPlanConstructionResult(
            construction_id=construction_id,
            status=status,
            reason=reason,
            plan_boundary_result=plan_boundary_result,
            build_result=build_result,
            plan=plan,
            provenance=provenance,
        )
