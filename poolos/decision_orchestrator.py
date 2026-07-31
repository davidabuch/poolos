"""Command-free orchestration of one PoolOS decision evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from .decision_planning import DecisionPlanResult, DecisionPlanningRequest, ExplainablePlanner
from .evaluation_context import DecisionEvaluationContext
from .homeassistant.decision_intelligence import (
    HomeAssistantDecisionProjection,
    HomeAssistantDecisionProjector,
)
from .kernel import PoolKernel


class OrchestrationStatus(str, Enum):
    """Disposition of one orchestrator invocation."""

    COMPLETED = "completed"
    BLOCKED_CONTEXT = "blocked_context"


@dataclass(frozen=True, slots=True)
class DecisionOrchestrationRequest:
    """Inputs needed to evaluate one objective from one frozen context."""

    context: DecisionEvaluationContext
    planning: DecisionPlanningRequest

    def __post_init__(self) -> None:
        contextual = self.context.goal(self.planning.objective.objective_id)
        if contextual != self.planning.objective:
            raise ValueError("planning objective must match the objective in the context")


@dataclass(frozen=True, slots=True)
class DecisionOrchestrationResult:
    """Complete command-free result from one supervisory evaluation."""

    status: OrchestrationStatus
    context_id: str
    trigger: str
    runtime_mode: str
    decision: Optional[DecisionPlanResult] = None
    home_assistant: Optional[HomeAssistantDecisionProjection] = None
    blockers: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status is OrchestrationStatus.COMPLETED and self.decision is None:
            raise ValueError("completed orchestration requires a decision")
        if self.status is OrchestrationStatus.BLOCKED_CONTEXT and not self.blockers:
            raise ValueError("blocked orchestration requires blockers")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class DecisionOrchestrator:
    """Validate context, invoke explainable planning, record, and project."""

    planner: ExplainablePlanner
    projector: HomeAssistantDecisionProjector = field(
        default_factory=HomeAssistantDecisionProjector
    )

    def evaluate(
        self,
        request: DecisionOrchestrationRequest,
        kernel: PoolKernel,
    ) -> DecisionOrchestrationResult:
        """Run one deterministic, non-actuating supervisory evaluation."""

        context = request.context
        common = {
            "schema_version": str(context.schema_version),
            "goal_count": str(len(context.goals)),
            "policy_count": str(len(context.active_policy_ids)),
            "previous_decision_id": context.previous_decision_id or "none",
        }
        if not context.planning_allowed:
            return DecisionOrchestrationResult(
                status=OrchestrationStatus.BLOCKED_CONTEXT,
                context_id=context.context_id,
                trigger=context.trigger.value,
                runtime_mode=context.runtime_mode.value,
                blockers=context.blockers,
                diagnostics=common,
            )

        planning = request.planning
        enriched = DecisionPlanningRequest(
            objective=planning.objective,
            candidates=planning.candidates,
            evidence=planning.evidence,
            checks=planning.checks,
            summary=planning.summary,
            next_change=planning.next_change,
            confidence=planning.confidence,
            metadata={
                **dict(planning.metadata),
                "evaluation_context_id": context.context_id,
                "evaluation_trigger": context.trigger.value,
                "runtime_mode": context.runtime_mode.value,
                "context_schema_version": str(context.schema_version),
                "previous_decision_id": context.previous_decision_id or "none",
            },
        )
        decision = self.planner.create_plan(enriched, kernel)
        projection = None
        if decision.flight_record is not None:
            projection = self.projector.project(decision.flight_record)
        return DecisionOrchestrationResult(
            status=OrchestrationStatus.COMPLETED,
            context_id=context.context_id,
            trigger=context.trigger.value,
            runtime_mode=context.runtime_mode.value,
            decision=decision,
            home_assistant=projection,
            diagnostics=common,
        )
