"""Deterministic, command-free execution proposal request boundary.

Epic 10.16B converts one validated operational action targeting the execution
proposal boundary into immutable proposal-request evidence. It does not create
an execution plan, mutate runtime state, authorize work, schedule execution,
deliver commands, call Home Assistant or vendors, or actuate equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .operational_action_pipeline import (
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from .operational_disposition_orchestrator import OperationalAction, OperationalTarget


class ExecutionProposalBoundaryStatus(str, Enum):
    """Outcome of one execution-proposal boundary evaluation."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExecutionProposalBoundaryReason(str, Enum):
    """Stable machine-readable proposal-boundary outcome reasons."""

    PROPOSAL_REQUEST_ACCEPTED = "proposal_request_accepted"
    PIPELINE_NOT_ACCEPTED = "pipeline_not_accepted"
    PIPELINE_EVIDENCE_INVALID = "pipeline_evidence_invalid"
    UNSUPPORTED_ACTION = "unsupported_action"
    UNSUPPORTED_TARGET = "unsupported_target"
    MISSING_DECISION_ID = "missing_decision_id"
    UNEXPECTED_PLAN_ID = "unexpected_plan_id"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = _canonical_json(dict(sorted(payload.items())))
    return prefix + sha256(canonical.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ExecutionProposalRequest:
    """Immutable request for future execution-proposal construction."""

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
class ExecutionProposalBoundaryResult:
    """Immutable evidence from one proposal-boundary evaluation."""

    result_id: str
    status: ExecutionProposalBoundaryStatus
    reason: ExecutionProposalBoundaryReason
    pipeline_result: OperationalActionPipelineResult
    proposal_request: ExecutionProposalRequest | None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        if self.status is ExecutionProposalBoundaryStatus.ACCEPTED:
            if (
                self.reason
                is not ExecutionProposalBoundaryReason.PROPOSAL_REQUEST_ACCEPTED
            ):
                raise ValueError(
                    "accepted result requires proposal-request-accepted reason"
                )
            if self.proposal_request is None:
                raise ValueError(
                    "accepted result requires a proposal request"
                )
            action = self.pipeline_result.action
            if self.proposal_request.source_action_id != action.action_id:
                raise ValueError("proposal request must preserve action identity")
            if self.proposal_request.context_id != action.context_id:
                raise ValueError("proposal request must preserve context identity")
            if self.proposal_request.decision_id != action.decision_id:
                raise ValueError("proposal request must preserve decision identity")
        elif self.proposal_request is not None:
            raise ValueError("rejected result cannot contain a proposal request")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class ExecutionProposalBoundary:
    """Convert validated proposal actions into immutable request evidence."""

    boundary_name: str = "execution_proposal_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self,
        pipeline_result: OperationalActionPipelineResult,
    ) -> ExecutionProposalBoundaryResult:
        """Evaluate one pipeline result without creating or executing a plan."""

        rejection = self._rejection_reason(pipeline_result)
        if rejection is not None:
            return self._result(pipeline_result, rejection, proposal_request=None)

        action = pipeline_result.action
        decision_id = action.decision_id
        if decision_id is None:
            return self._result(
                pipeline_result,
                ExecutionProposalBoundaryReason.MISSING_DECISION_ID,
                proposal_request=None,
            )
        if action.plan_id is not None:
            return self._result(
                pipeline_result,
                ExecutionProposalBoundaryReason.UNEXPECTED_PLAN_ID,
                proposal_request=None,
            )

        proposal_request_id = _derived_id(
            "execution-proposal-request-",
            {
                "action_id": action.action_id,
                "boundary_name": self.boundary_name,
                "context_id": action.context_id,
                "correlation_id": action.correlation_id or "",
                "decision_id": decision_id,
                "reason_code": action.reason_code,
            },
        )
        request = ExecutionProposalRequest(
            proposal_request_id=proposal_request_id,
            source_action_id=action.action_id,
            context_id=action.context_id,
            decision_id=decision_id,
            correlation_id=action.correlation_id,
            reason_code=action.reason_code,
            reason=action.reason,
            provenance={
                **dict(action.diagnostics),
                **dict(pipeline_result.diagnostics),
                "execution_proposal_boundary": self.boundary_name,
                "execution_proposal_request_id": proposal_request_id,
                "source_action_id": action.action_id,
                "source_context_id": action.context_id,
                "source_decision_id": decision_id,
                "source_correlation_id": action.correlation_id or "",
            },
        )
        return self._result(
            pipeline_result,
            ExecutionProposalBoundaryReason.PROPOSAL_REQUEST_ACCEPTED,
            proposal_request=request,
        )

    def _rejection_reason(
        self, pipeline_result: OperationalActionPipelineResult
    ) -> ExecutionProposalBoundaryReason | None:
        if pipeline_result.status is not OperationalActionPipelineStatus.ACCEPTED:
            return ExecutionProposalBoundaryReason.PIPELINE_NOT_ACCEPTED
        action = pipeline_result.action
        if pipeline_result.reason is not OperationalActionPipelineReason.ROUTE_ACCEPTED:
            return ExecutionProposalBoundaryReason.PIPELINE_EVIDENCE_INVALID
        if action.action_id not in pipeline_result.accepted_action_ids:
            return ExecutionProposalBoundaryReason.PIPELINE_EVIDENCE_INVALID
        if action.action is not OperationalAction.REQUEST_PROPOSAL:
            return ExecutionProposalBoundaryReason.UNSUPPORTED_ACTION
        if action.target is not OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY:
            return ExecutionProposalBoundaryReason.UNSUPPORTED_TARGET
        if pipeline_result.routed_target is not action.target:
            return ExecutionProposalBoundaryReason.PIPELINE_EVIDENCE_INVALID
        if pipeline_result.boundary_name != self.boundary_name:
            return ExecutionProposalBoundaryReason.PIPELINE_EVIDENCE_INVALID
        return None

    def _result(
        self,
        pipeline_result: OperationalActionPipelineResult,
        reason: ExecutionProposalBoundaryReason,
        *,
        proposal_request: ExecutionProposalRequest | None,
    ) -> ExecutionProposalBoundaryResult:
        status = (
            ExecutionProposalBoundaryStatus.ACCEPTED
            if reason is ExecutionProposalBoundaryReason.PROPOSAL_REQUEST_ACCEPTED
            else ExecutionProposalBoundaryStatus.REJECTED
        )
        result_id = _derived_id(
            "execution-proposal-boundary-result-",
            {
                "action_id": pipeline_result.action.action_id,
                "boundary_name": self.boundary_name,
                "pipeline_reason": pipeline_result.reason.value,
                "pipeline_status": pipeline_result.status.value,
                "proposal_request_id": (
                    proposal_request.proposal_request_id if proposal_request else "none"
                ),
                "reason": reason.value,
                "status": status.value,
            },
        )
        provenance = {
            **dict(pipeline_result.diagnostics),
            "execution_proposal_boundary": self.boundary_name,
            "execution_proposal_boundary_result_id": result_id,
            "execution_proposal_boundary_status": status.value,
            "execution_proposal_boundary_reason": reason.value,
            "execution_proposal_request_id": (
                proposal_request.proposal_request_id if proposal_request else ""
            ),
        }
        return ExecutionProposalBoundaryResult(
            result_id=result_id,
            status=status,
            reason=reason,
            pipeline_result=pipeline_result,
            proposal_request=proposal_request,
            provenance=provenance,
        )
