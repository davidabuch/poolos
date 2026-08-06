"""Deterministic, command-free execution-plan request boundary.

Epic 10.16C converts one accepted execution proposal request into immutable
execution-plan request evidence. It does not construct an execution plan,
authorize work, mutate runtime state, schedule execution, deliver commands,
call Home Assistant or vendors, or actuate equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_proposal_boundary import (
    ExecutionProposalBoundaryResult,
    ExecutionProposalBoundaryStatus,
)


class ExecutionPlanBoundaryStatus(str, Enum):
    """Outcome of one execution-plan boundary evaluation."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExecutionPlanBoundaryReason(str, Enum):
    """Stable machine-readable plan-boundary outcome reasons."""

    PLAN_REQUEST_ACCEPTED = "plan_request_accepted"
    PROPOSAL_NOT_ACCEPTED = "proposal_not_accepted"
    PROPOSAL_EVIDENCE_INVALID = "proposal_evidence_invalid"
    MISSING_PROPOSAL_REQUEST = "missing_proposal_request"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = _canonical_json(dict(sorted(payload.items())))
    return prefix + sha256(canonical.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ExecutionPlanRequest:
    """Immutable request for future execution-plan construction."""

    plan_request_id: str
    source_proposal_result_id: str
    proposal_request_id: str
    source_action_id: str
    context_id: str
    decision_id: str
    correlation_id: str | None = None
    reason_code: str = ""
    reason: str = ""
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("plan_request_id", self.plan_request_id),
            ("source_proposal_result_id", self.source_proposal_result_id),
            ("proposal_request_id", self.proposal_request_id),
            ("source_action_id", self.source_action_id),
            ("context_id", self.context_id),
            ("decision_id", self.decision_id),
            ("reason_code", self.reason_code),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanBoundaryResult:
    """Immutable evidence from one execution-plan boundary evaluation."""

    result_id: str
    status: ExecutionPlanBoundaryStatus
    reason: ExecutionPlanBoundaryReason
    proposal_result: ExecutionProposalBoundaryResult
    plan_request: ExecutionPlanRequest | None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        if self.status is ExecutionPlanBoundaryStatus.ACCEPTED:
            if self.reason is not ExecutionPlanBoundaryReason.PLAN_REQUEST_ACCEPTED:
                raise ValueError("accepted result requires plan-request-accepted reason")
            if self.plan_request is None:
                raise ValueError("accepted result requires a plan request")
            proposal_request = self.proposal_result.proposal_request
            if proposal_request is None:
                raise ValueError("accepted result requires proposal-request evidence")
            if (
                self.plan_request.source_proposal_result_id
                != self.proposal_result.result_id
            ):
                raise ValueError("plan request must preserve proposal result identity")
            if (
                self.plan_request.proposal_request_id
                != proposal_request.proposal_request_id
            ):
                raise ValueError("plan request must preserve proposal request identity")
            if self.plan_request.source_action_id != proposal_request.source_action_id:
                raise ValueError("plan request must preserve action identity")
            if self.plan_request.context_id != proposal_request.context_id:
                raise ValueError("plan request must preserve context identity")
            if self.plan_request.decision_id != proposal_request.decision_id:
                raise ValueError("plan request must preserve decision identity")
        elif self.plan_request is not None:
            raise ValueError("rejected result cannot contain a plan request")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionPlanBoundary:
    """Convert accepted proposal requests into immutable plan-request evidence."""

    boundary_name: str = "execution_plan_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self,
        proposal_result: ExecutionProposalBoundaryResult,
    ) -> ExecutionPlanBoundaryResult:
        """Evaluate one proposal result without constructing or executing a plan."""

        if proposal_result.status is not ExecutionProposalBoundaryStatus.ACCEPTED:
            return self._result(
                proposal_result,
                ExecutionPlanBoundaryReason.PROPOSAL_NOT_ACCEPTED,
                plan_request=None,
            )

        proposal_request = proposal_result.proposal_request
        if proposal_request is None:
            return self._result(
                proposal_result,
                ExecutionPlanBoundaryReason.MISSING_PROPOSAL_REQUEST,
                plan_request=None,
            )

        if (
            proposal_request.source_action_id
            != proposal_result.pipeline_result.action.action_id
            or proposal_request.context_id
            != proposal_result.pipeline_result.action.context_id
            or proposal_request.decision_id
            != proposal_result.pipeline_result.action.decision_id
        ):
            return self._result(
                proposal_result,
                ExecutionPlanBoundaryReason.PROPOSAL_EVIDENCE_INVALID,
                plan_request=None,
            )

        plan_request_id = _derived_id(
            "execution-plan-request-",
            {
                "boundary_name": self.boundary_name,
                "context_id": proposal_request.context_id,
                "correlation_id": proposal_request.correlation_id or "",
                "decision_id": proposal_request.decision_id,
                "proposal_request_id": proposal_request.proposal_request_id,
                "proposal_result_id": proposal_result.result_id,
                "source_action_id": proposal_request.source_action_id,
            },
        )
        plan_request = ExecutionPlanRequest(
            plan_request_id=plan_request_id,
            source_proposal_result_id=proposal_result.result_id,
            proposal_request_id=proposal_request.proposal_request_id,
            source_action_id=proposal_request.source_action_id,
            context_id=proposal_request.context_id,
            decision_id=proposal_request.decision_id,
            correlation_id=proposal_request.correlation_id,
            reason_code=proposal_request.reason_code,
            reason=proposal_request.reason,
            provenance={
                **dict(proposal_result.provenance),
                **dict(proposal_request.provenance),
                "execution_plan_boundary": self.boundary_name,
                "execution_plan_request_id": plan_request_id,
                "source_proposal_result_id": proposal_result.result_id,
                "source_proposal_request_id": proposal_request.proposal_request_id,
                "source_action_id": proposal_request.source_action_id,
                "source_context_id": proposal_request.context_id,
                "source_decision_id": proposal_request.decision_id,
                "source_correlation_id": proposal_request.correlation_id or "",
            },
        )
        return self._result(
            proposal_result,
            ExecutionPlanBoundaryReason.PLAN_REQUEST_ACCEPTED,
            plan_request=plan_request,
        )

    def _result(
        self,
        proposal_result: ExecutionProposalBoundaryResult,
        reason: ExecutionPlanBoundaryReason,
        *,
        plan_request: ExecutionPlanRequest | None,
    ) -> ExecutionPlanBoundaryResult:
        status = (
            ExecutionPlanBoundaryStatus.ACCEPTED
            if reason is ExecutionPlanBoundaryReason.PLAN_REQUEST_ACCEPTED
            else ExecutionPlanBoundaryStatus.REJECTED
        )
        result_id = _derived_id(
            "execution-plan-boundary-result-",
            {
                "boundary_name": self.boundary_name,
                "plan_request_id": (
                    plan_request.plan_request_id if plan_request else "none"
                ),
                "proposal_result_id": proposal_result.result_id,
                "reason": reason.value,
                "status": status.value,
            },
        )
        provenance = {
            **dict(proposal_result.provenance),
            **(dict(plan_request.provenance) if plan_request is not None else {}),
            "execution_plan_boundary": self.boundary_name,
            "execution_plan_boundary_result_id": result_id,
            "execution_plan_boundary_status": status.value,
            "execution_plan_boundary_reason": reason.value,
            "execution_plan_request_id": (
                plan_request.plan_request_id if plan_request else ""
            ),
        }
        return ExecutionPlanBoundaryResult(
            result_id=result_id,
            status=status,
            reason=reason,
            proposal_result=proposal_result,
            plan_request=plan_request,
            provenance=provenance,
        )
