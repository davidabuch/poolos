"""Canonical command-free operational-action pipeline for PoolOS.

This module turns one immutable orchestration instruction into one canonical
operational action request and one immutable pipeline result.  The pipeline
validates identity and route compatibility only; it never invokes a target,
performs scheduling, creates proposals, mutates plans, authorizes execution,
delivers commands, or actuates equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .operational_disposition_orchestrator import (
    OperationalAction,
    OperationalOrchestrationInstruction,
    OperationalTarget,
)


class OperationalActionPipelineStatus(str, Enum):
    """Outcome of command-free action validation and logical routing."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OperationalActionPipelineReason(str, Enum):
    """Stable machine-readable pipeline outcome reasons."""

    ROUTE_ACCEPTED = "route_accepted"
    ACTION_TARGET_MISMATCH = "action_target_mismatch"
    DUPLICATE_ACTION_ID = "duplicate_action_id"


_EXPECTED_TARGET_BY_ACTION: Mapping[OperationalAction, OperationalTarget] = (
    MappingProxyType(
        {
            OperationalAction.NO_ACTION: OperationalTarget.NONE,
            OperationalAction.REQUEST_REEVALUATION: (
                OperationalTarget.REEVALUATION_SCHEDULER
            ),
            OperationalAction.REQUEST_PROPOSAL: (
                OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY
            ),
            OperationalAction.RETAIN_PLAN: OperationalTarget.EXECUTION_PLAN_BOUNDARY,
            OperationalAction.REQUEST_PLAN_CANCELLATION: (
                OperationalTarget.EXECUTION_PLAN_BOUNDARY
            ),
            OperationalAction.REQUEST_PLAN_REPLACEMENT: (
                OperationalTarget.EXECUTION_PLAN_BOUNDARY
            ),
            OperationalAction.HALT: OperationalTarget.OPERATOR_REVIEW,
        }
    )
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class CanonicalOperationalAction:
    """Immutable canonical work request derived from one routing instruction."""

    action_id: str
    action: OperationalAction
    target: OperationalTarget
    context_id: str
    disposition: str
    reason_code: str
    reason: str
    decision_id: str | None = None
    plan_id: str | None = None
    reevaluation_hint: str | None = None
    correlation_id: str | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("action_id", self.action_id),
            ("context_id", self.context_id),
            ("disposition", self.disposition),
            ("reason_code", self.reason_code),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @classmethod
    def from_instruction(
        cls,
        instruction: OperationalOrchestrationInstruction,
        *,
        correlation_id: str | None = None,
    ) -> CanonicalOperationalAction:
        """Create one deterministic canonical action from an instruction."""

        identity_payload = {
            "action": instruction.action.value,
            "context_id": instruction.context_id,
            "decision_id": instruction.decision_id,
            "disposition": instruction.disposition.value,
            "plan_id": instruction.plan_id,
            "reason_code": instruction.reason_code,
            "reevaluation_hint": instruction.reevaluation_hint,
            "target": instruction.target.value,
        }
        action_id = "operational-action-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        diagnostics = {
            **dict(instruction.diagnostics),
            "operational_action_id": action_id,
            "operational_action_target": instruction.target.value,
        }
        return cls(
            action_id=action_id,
            action=instruction.action,
            target=instruction.target,
            context_id=instruction.context_id,
            disposition=instruction.disposition.value,
            reason_code=instruction.reason_code,
            reason=instruction.reason,
            decision_id=instruction.decision_id,
            plan_id=instruction.plan_id,
            reevaluation_hint=instruction.reevaluation_hint,
            correlation_id=correlation_id,
            diagnostics=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class OperationalActionPipelineResult:
    """Immutable result of command-free operational-action processing."""

    status: OperationalActionPipelineStatus
    reason: OperationalActionPipelineReason
    action: CanonicalOperationalAction
    routed_target: OperationalTarget
    accepted_action_ids: tuple[str, ...]
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        accepted_ids = tuple(self.accepted_action_ids)
        if any(not action_id.strip() for action_id in accepted_ids):
            raise ValueError("accepted action IDs must not be empty")
        if len(set(accepted_ids)) != len(accepted_ids):
            raise ValueError("accepted action IDs must be unique")
        if self.status is OperationalActionPipelineStatus.ACCEPTED:
            if self.action.action_id not in accepted_ids:
                raise ValueError("accepted result must record its action ID")
            if self.routed_target is not self.action.target:
                raise ValueError("accepted result must preserve the action target")
        elif (
            self.reason is not OperationalActionPipelineReason.DUPLICATE_ACTION_ID
            and self.action.action_id in accepted_ids
        ):
            raise ValueError(
                "non-duplicate rejection cannot record its action ID as accepted"
            )
        object.__setattr__(self, "accepted_action_ids", accepted_ids)
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class OperationalActionPipeline:
    """Validate and logically route canonical actions without invoking targets."""

    def process(
        self,
        action: CanonicalOperationalAction,
        *,
        accepted_action_ids: tuple[str, ...] = (),
    ) -> OperationalActionPipelineResult:
        """Return one immutable pipeline result with no external side effects."""

        prior_ids = tuple(accepted_action_ids)
        if action.action_id in prior_ids:
            return self._result(
                action=action,
                status=OperationalActionPipelineStatus.REJECTED,
                reason=OperationalActionPipelineReason.DUPLICATE_ACTION_ID,
                routed_target=OperationalTarget.NONE,
                accepted_action_ids=prior_ids,
            )

        expected_target = _EXPECTED_TARGET_BY_ACTION[action.action]
        if action.target is not expected_target:
            return self._result(
                action=action,
                status=OperationalActionPipelineStatus.REJECTED,
                reason=OperationalActionPipelineReason.ACTION_TARGET_MISMATCH,
                routed_target=OperationalTarget.NONE,
                accepted_action_ids=prior_ids,
            )

        return self._result(
            action=action,
            status=OperationalActionPipelineStatus.ACCEPTED,
            reason=OperationalActionPipelineReason.ROUTE_ACCEPTED,
            routed_target=action.target,
            accepted_action_ids=(*prior_ids, action.action_id),
        )

    @staticmethod
    def _result(
        *,
        action: CanonicalOperationalAction,
        status: OperationalActionPipelineStatus,
        reason: OperationalActionPipelineReason,
        routed_target: OperationalTarget,
        accepted_action_ids: tuple[str, ...],
    ) -> OperationalActionPipelineResult:
        diagnostics = {
            **dict(action.diagnostics),
            "pipeline_status": status.value,
            "pipeline_reason": reason.value,
            "routed_target": routed_target.value,
        }
        return OperationalActionPipelineResult(
            status=status,
            reason=reason,
            action=action,
            routed_target=routed_target,
            accepted_action_ids=accepted_action_ids,
            diagnostics=diagnostics,
        )
