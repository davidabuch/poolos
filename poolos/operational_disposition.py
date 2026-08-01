"""Deterministic operational disposition boundary for PoolOS.

This module converts one accepted supervisory decision plus a minimal summary of
current execution state into one immutable recommendation. It is deliberately
command-free: it does not build, authorize, submit, cancel, replace, or execute
plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .decision_intelligence import DecisionOutcome
from .decision_orchestrator import DecisionOrchestrationResult, OrchestrationStatus
from .execution_models import ExecutionLifecycleStatus


class OperationalDisposition(str, Enum):
    """Recommended relationship between accepted intent and execution state."""

    WAIT = "wait"
    SCHEDULE_REEVALUATION = "schedule_reevaluation"
    SUBMIT_NEW_PLAN = "submit_new_plan"
    KEEP_EXISTING_PLAN = "keep_existing_plan"
    CANCEL_EXISTING_PLAN = "cancel_existing_plan"
    REPLACE_EXISTING_PLAN = "replace_existing_plan"
    BLOCK = "block"


class OperationalReasonCode(str, Enum):
    """Stable machine-readable reason for an operational disposition."""

    CONTEXT_BLOCKED = "context_blocked"
    DECISION_BLOCKED = "decision_blocked"
    NO_ACTION_REQUIRED = "no_action_required"
    REEVALUATION_HINT_AVAILABLE = "reevaluation_hint_available"
    SELECTED_WITHOUT_PLAN = "selected_without_plan"
    EXISTING_PLAN_MATCHES_DECISION = "existing_plan_matches_decision"
    SELECTED_DECISION_CHANGED = "selected_decision_changed"
    ACTIVE_PLAN_NO_LONGER_REQUIRED = "active_plan_no_longer_required"
    ACTIVE_PLAN_NOT_CANCELLABLE = "active_plan_not_cancellable"
    ACTIVE_PLAN_NOT_REPLACEABLE = "active_plan_not_replaceable"


_ACTIVE_PLAN_STATUSES = frozenset(
    {
        ExecutionLifecycleStatus.PENDING,
        ExecutionLifecycleStatus.AUTHORIZED,
        ExecutionLifecycleStatus.PLANNED,
        ExecutionLifecycleStatus.EXECUTING,
    }
)


@dataclass(frozen=True, slots=True)
class OperationalDecisionSnapshot:
    """Minimal accepted-decision view supplied to operational disposition."""

    context_id: str
    orchestration_status: OrchestrationStatus
    decision_id: str | None = None
    outcome: DecisionOutcome | None = None
    selected_alternative_id: str | None = None
    next_change: str | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        if self.orchestration_status is OrchestrationStatus.BLOCKED_CONTEXT:
            if not self.blockers:
                raise ValueError("blocked context requires blockers")
            if self.decision_id is not None or self.outcome is not None:
                raise ValueError("blocked context cannot contain an accepted decision")
            return
        if self.decision_id is None or not self.decision_id.strip():
            raise ValueError("evaluated orchestration requires decision_id")
        if self.outcome is None:
            raise ValueError("evaluated orchestration requires outcome")
        if self.outcome is DecisionOutcome.SELECTED:
            if self.selected_alternative_id is None:
                raise ValueError("selected decision requires selected_alternative_id")
        elif self.selected_alternative_id is not None:
            raise ValueError("non-selected decision cannot identify an alternative")

    @classmethod
    def from_orchestration(
        cls,
        result: DecisionOrchestrationResult,
    ) -> OperationalDecisionSnapshot:
        """Create a stable snapshot from the decision accepted by orchestration."""

        if result.status is OrchestrationStatus.BLOCKED_CONTEXT:
            return cls(
                context_id=result.context_id,
                orchestration_status=result.status,
                blockers=result.blockers,
            )

        if result.status is OrchestrationStatus.RETAINED:
            if result.active_record is None:
                raise ValueError("retained orchestration requires an active record")
            explanation = result.active_record.decision
        else:
            if result.decision is None:
                raise ValueError("completed orchestration requires a decision")
            explanation = result.decision.explanation

        return cls(
            context_id=result.context_id,
            orchestration_status=result.status,
            decision_id=explanation.decision_id,
            outcome=explanation.outcome,
            selected_alternative_id=explanation.selected_alternative_id,
            next_change=explanation.next_change,
            blockers=tuple(check.reason for check in explanation.blocking_checks),
        )


@dataclass(frozen=True, slots=True)
class OperationalPlanSummary:
    """Minimal non-actuating summary of the currently active execution plan."""

    plan_id: str
    decision_id: str
    status: ExecutionLifecycleStatus
    cancellable: bool = True
    replaceable: bool = True

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must not be empty")
        if not self.decision_id.strip():
            raise ValueError("decision_id must not be empty")
        if self.status not in _ACTIVE_PLAN_STATUSES:
            raise ValueError("current plan summary requires an active plan status")
        if self.replaceable and not self.cancellable:
            raise ValueError("replaceable plans must also be cancellable")


@dataclass(frozen=True, slots=True)
class OperationalEvaluationRequest:
    """Inputs required for one deterministic disposition evaluation."""

    decision: OperationalDecisionSnapshot
    current_plan: OperationalPlanSummary | None = None


@dataclass(frozen=True, slots=True)
class OperationalEvaluationResult:
    """Immutable command-free recommendation for execution-plan handling."""

    disposition: OperationalDisposition
    reason_code: OperationalReasonCode
    reason: str
    context_id: str
    decision_id: str | None = None
    plan_id: str | None = None
    reevaluation_hint: str | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        plan_required = self.disposition in {
            OperationalDisposition.KEEP_EXISTING_PLAN,
            OperationalDisposition.CANCEL_EXISTING_PLAN,
            OperationalDisposition.REPLACE_EXISTING_PLAN,
        }
        if plan_required and self.plan_id is None:
            raise ValueError(f"{self.disposition.value} requires plan_id")
        if self.disposition is OperationalDisposition.SCHEDULE_REEVALUATION:
            if self.reevaluation_hint is None:
                raise ValueError("scheduled reevaluation requires a hint")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class OperationalDispositionEngine:
    """Compare accepted intent with active execution state without side effects."""

    def evaluate(self, request: OperationalEvaluationRequest) -> OperationalEvaluationResult:
        """Return exactly one deterministic operational recommendation."""

        decision = request.decision
        plan = request.current_plan
        common = {
            "orchestration_status": decision.orchestration_status.value,
            "decision_outcome": decision.outcome.value if decision.outcome else "none",
            "selected_alternative_id": decision.selected_alternative_id or "none",
            "current_plan_status": plan.status.value if plan else "none",
            "current_plan_decision_id": plan.decision_id if plan else "none",
        }

        if decision.orchestration_status is OrchestrationStatus.BLOCKED_CONTEXT:
            return self._result(
                decision,
                plan,
                OperationalDisposition.BLOCK,
                OperationalReasonCode.CONTEXT_BLOCKED,
                "Operational action is blocked because the evaluation context is invalid",
                common,
            )

        if decision.outcome is DecisionOutcome.BLOCKED:
            return self._result(
                decision,
                plan,
                OperationalDisposition.BLOCK,
                OperationalReasonCode.DECISION_BLOCKED,
                "Operational action is blocked by the accepted decision",
                common,
            )

        if decision.outcome is DecisionOutcome.SELECTED:
            if plan is None:
                return self._result(
                    decision,
                    plan,
                    OperationalDisposition.SUBMIT_NEW_PLAN,
                    OperationalReasonCode.SELECTED_WITHOUT_PLAN,
                    "The accepted decision selected an action and no active plan exists",
                    common,
                )
            if plan.decision_id == decision.decision_id:
                return self._result(
                    decision,
                    plan,
                    OperationalDisposition.KEEP_EXISTING_PLAN,
                    OperationalReasonCode.EXISTING_PLAN_MATCHES_DECISION,
                    "The active plan already represents the accepted decision",
                    common,
                )
            if plan.replaceable:
                return self._result(
                    decision,
                    plan,
                    OperationalDisposition.REPLACE_EXISTING_PLAN,
                    OperationalReasonCode.SELECTED_DECISION_CHANGED,
                    "The accepted decision changed and the active plan may be replaced",
                    common,
                )
            return self._result(
                decision,
                plan,
                OperationalDisposition.BLOCK,
                OperationalReasonCode.ACTIVE_PLAN_NOT_REPLACEABLE,
                "The accepted decision changed but the active plan is not replaceable",
                common,
            )

        if plan is not None:
            if plan.cancellable:
                return self._result(
                    decision,
                    plan,
                    OperationalDisposition.CANCEL_EXISTING_PLAN,
                    OperationalReasonCode.ACTIVE_PLAN_NO_LONGER_REQUIRED,
                    "The accepted decision no longer requires the active plan",
                    common,
                )
            return self._result(
                decision,
                plan,
                OperationalDisposition.BLOCK,
                OperationalReasonCode.ACTIVE_PLAN_NOT_CANCELLABLE,
                (
                    "The accepted decision no longer requires the active plan, "
                    "but it cannot be cancelled"
                ),
                common,
            )

        if decision.next_change is not None:
            return self._result(
                decision,
                plan,
                OperationalDisposition.SCHEDULE_REEVALUATION,
                OperationalReasonCode.REEVALUATION_HINT_AVAILABLE,
                "No execution plan is required now, and the decision identifies a future change",
                common,
                reevaluation_hint=decision.next_change,
            )

        return self._result(
            decision,
            plan,
            OperationalDisposition.WAIT,
            OperationalReasonCode.NO_ACTION_REQUIRED,
            "No execution plan or scheduled reevaluation is currently required",
            common,
        )

    @staticmethod
    def _result(
        decision: OperationalDecisionSnapshot,
        plan: OperationalPlanSummary | None,
        disposition: OperationalDisposition,
        reason_code: OperationalReasonCode,
        reason: str,
        diagnostics: Mapping[str, str],
        *,
        reevaluation_hint: str | None = None,
    ) -> OperationalEvaluationResult:
        return OperationalEvaluationResult(
            disposition=disposition,
            reason_code=reason_code,
            reason=reason,
            context_id=decision.context_id,
            decision_id=decision.decision_id,
            plan_id=plan.plan_id if plan else None,
            reevaluation_hint=reevaluation_hint,
            diagnostics=diagnostics,
        )
