"""Command-free orchestration of operational disposition recommendations.

The orchestrator in this module consumes one immutable
:class:`OperationalEvaluationResult` and converts it into one immutable routing
instruction. It does not invoke the routed subsystem and performs no scheduling,
proposal generation, plan mutation, authorization, delivery, or actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
)


class OperationalAction(str, Enum):
    """Next command-free action implied by an operational disposition."""

    NO_ACTION = "no_action"
    REQUEST_REEVALUATION = "request_reevaluation"
    REQUEST_PROPOSAL = "request_proposal"
    RETAIN_PLAN = "retain_plan"
    REQUEST_PLAN_CANCELLATION = "request_plan_cancellation"
    REQUEST_PLAN_REPLACEMENT = "request_plan_replacement"
    HALT = "halt"


class OperationalTarget(str, Enum):
    """Logical subsystem that may consume an orchestration instruction."""

    NONE = "none"
    REEVALUATION_SCHEDULER = "reevaluation_scheduler"
    EXECUTION_PROPOSAL_BOUNDARY = "execution_proposal_boundary"
    EXECUTION_PLAN_BOUNDARY = "execution_plan_boundary"
    OPERATOR_REVIEW = "operator_review"


_ACTION_BY_DISPOSITION: Mapping[
    OperationalDisposition,
    tuple[OperationalAction, OperationalTarget],
] = MappingProxyType(
    {
        OperationalDisposition.WAIT: (
            OperationalAction.NO_ACTION,
            OperationalTarget.NONE,
        ),
        OperationalDisposition.SCHEDULE_REEVALUATION: (
            OperationalAction.REQUEST_REEVALUATION,
            OperationalTarget.REEVALUATION_SCHEDULER,
        ),
        OperationalDisposition.SUBMIT_NEW_PLAN: (
            OperationalAction.REQUEST_PROPOSAL,
            OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        ),
        OperationalDisposition.KEEP_EXISTING_PLAN: (
            OperationalAction.RETAIN_PLAN,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        OperationalDisposition.CANCEL_EXISTING_PLAN: (
            OperationalAction.REQUEST_PLAN_CANCELLATION,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        OperationalDisposition.REPLACE_EXISTING_PLAN: (
            OperationalAction.REQUEST_PLAN_REPLACEMENT,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        OperationalDisposition.BLOCK: (
            OperationalAction.HALT,
            OperationalTarget.OPERATOR_REVIEW,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class OperationalOrchestrationInstruction:
    """Immutable, non-actuating instruction for the next subsystem boundary."""

    action: OperationalAction
    target: OperationalTarget
    context_id: str
    disposition: OperationalDisposition
    reason_code: str
    reason: str
    decision_id: str | None = None
    plan_id: str | None = None
    reevaluation_hint: str | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        if not self.reason_code.strip():
            raise ValueError("reason_code must not be empty")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")

        if self.action is OperationalAction.REQUEST_REEVALUATION:
            if self.reevaluation_hint is None:
                raise ValueError("reevaluation instruction requires a hint")
        elif self.reevaluation_hint is not None:
            raise ValueError("only reevaluation instructions may contain a hint")

        if self.action is OperationalAction.REQUEST_PROPOSAL:
            if self.decision_id is None:
                raise ValueError("proposal instruction requires decision_id")
            if self.plan_id is not None:
                raise ValueError("new proposal instruction cannot identify a plan")

        if self.action in {
            OperationalAction.RETAIN_PLAN,
            OperationalAction.REQUEST_PLAN_CANCELLATION,
            OperationalAction.REQUEST_PLAN_REPLACEMENT,
        } and self.plan_id is None:
            raise ValueError(f"{self.action.value} requires plan_id")

        if self.action is OperationalAction.REQUEST_PLAN_REPLACEMENT:
            if self.decision_id is None:
                raise ValueError("plan replacement requires decision_id")

        if self.action is OperationalAction.NO_ACTION:
            if self.target is not OperationalTarget.NONE:
                raise ValueError("no-action instruction must target none")
        elif self.target is OperationalTarget.NONE:
            raise ValueError("actionable instruction must identify a target")

        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class OperationalDispositionOrchestrator:
    """Convert one disposition result into one deterministic routing instruction."""

    def orchestrate(
        self,
        result: OperationalEvaluationResult,
    ) -> OperationalOrchestrationInstruction:
        """Return a command-free next-action instruction without invoking it."""

        action, target = _ACTION_BY_DISPOSITION[result.disposition]
        reevaluation_hint = (
            result.reevaluation_hint
            if action is OperationalAction.REQUEST_REEVALUATION
            else None
        )
        diagnostics = {
            **dict(result.diagnostics),
            "operational_disposition": result.disposition.value,
            "operational_action": action.value,
            "operational_target": target.value,
        }
        return OperationalOrchestrationInstruction(
            action=action,
            target=target,
            context_id=result.context_id,
            disposition=result.disposition,
            reason_code=result.reason_code.value,
            reason=result.reason,
            decision_id=result.decision_id,
            plan_id=result.plan_id,
            reevaluation_hint=reevaluation_hint,
            diagnostics=diagnostics,
        )
