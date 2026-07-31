"""Command-free orchestration of one PoolOS decision evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from .decision_flight_recorder import DecisionFlightRecord
from .decision_planning import DecisionPlanResult, DecisionPlanningRequest, ExplainablePlanner
from .decision_stability import DecisionStabilityEngine, DecisionStabilityResult
from .evaluation_context import DecisionEvaluationContext
from .evaluation_triggers import CoalescedEvaluationTrigger
from .homeassistant.decision_intelligence import (
    HomeAssistantDecisionProjection,
    HomeAssistantDecisionProjector,
)
from .kernel import PoolKernel


class OrchestrationStatus(str, Enum):
    """Disposition of one orchestrator invocation."""

    COMPLETED = "completed"
    RETAINED = "retained"
    BLOCKED_CONTEXT = "blocked_context"


@dataclass(frozen=True, slots=True)
class DecisionOrchestrationRequest:
    """Inputs needed to evaluate one objective from one frozen context."""

    context: DecisionEvaluationContext
    planning: DecisionPlanningRequest
    active_record: Optional[DecisionFlightRecord] = None
    coalesced_trigger: Optional[CoalescedEvaluationTrigger] = None

    def __post_init__(self) -> None:
        contextual = self.context.goal(self.planning.objective.objective_id)
        if contextual != self.planning.objective:
            raise ValueError("planning objective must match the objective in the context")
        if (
            self.active_record is not None
            and self.context.previous_decision_id is not None
            and self.active_record.decision.decision_id
            != self.context.previous_decision_id
        ):
            raise ValueError("active record must match context previous_decision_id")
        if (
            self.coalesced_trigger is not None
            and self.coalesced_trigger.trigger is not self.context.trigger
        ):
            raise ValueError("coalesced trigger must match the context trigger")


@dataclass(frozen=True, slots=True)
class DecisionOrchestrationResult:
    """Complete command-free result from one supervisory evaluation."""

    status: OrchestrationStatus
    context_id: str
    trigger: str
    runtime_mode: str
    decision: Optional[DecisionPlanResult] = None
    active_record: Optional[DecisionFlightRecord] = None
    home_assistant: Optional[HomeAssistantDecisionProjection] = None
    stability: Optional[DecisionStabilityResult] = None
    blockers: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status in {OrchestrationStatus.COMPLETED, OrchestrationStatus.RETAINED}:
            if self.decision is None or self.stability is None:
                raise ValueError("evaluated orchestration requires decision and stability")
        if self.status is OrchestrationStatus.RETAINED:
            stability = self.stability
            if (
                self.active_record is None
                or stability is None
                or stability.decision_changed
            ):
                raise ValueError("retained orchestration requires unchanged active record")
        if self.status is OrchestrationStatus.BLOCKED_CONTEXT and not self.blockers:
            raise ValueError("blocked orchestration requires blockers")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class DecisionOrchestrator:
    """Validate context, plan, stabilize, record accepted changes, and project."""

    planner: ExplainablePlanner
    stability_engine: DecisionStabilityEngine = field(
        default_factory=DecisionStabilityEngine
    )
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
        trigger_count = (
            len(request.coalesced_trigger.requests)
            if request.coalesced_trigger is not None
            else 1
        )
        common = {
            "schema_version": str(context.schema_version),
            "goal_count": str(len(context.goals)),
            "policy_count": str(len(context.active_policy_ids)),
            "previous_decision_id": context.previous_decision_id or "none",
            "coalesced_trigger_count": str(trigger_count),
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
                "coalesced_trigger_count": str(trigger_count),
            },
        )

        unrecorded_planner = replace(self.planner, recorder=None)
        proposal = unrecorded_planner.create_plan(enriched, kernel)
        active_decision = (
            request.active_record.decision if request.active_record is not None else None
        )
        stability = self.stability_engine.evaluate(
            proposal.explanation,
            active_decision,
        )

        if not stability.decision_changed and request.active_record is not None:
            projection = self.projector.project(request.active_record)
            return DecisionOrchestrationResult(
                status=OrchestrationStatus.RETAINED,
                context_id=context.context_id,
                trigger=context.trigger.value,
                runtime_mode=context.runtime_mode.value,
                decision=proposal,
                active_record=request.active_record,
                home_assistant=projection,
                stability=stability,
                diagnostics={
                    **common,
                    "stability_disposition": stability.disposition.value,
                },
            )

        record = None
        if self.planner.recorder is not None:
            record = self.planner.recorder.record(
                plan_id=proposal.plan.plan_id,
                objective_id=proposal.plan.objective_id,
                decision=proposal.explanation,
                human=proposal.human,
                technical=proposal.technical,
                recorded_at=proposal.plan.created_at,
            )
        accepted = replace(proposal, flight_record=record)
        accepted_projection: Optional[HomeAssistantDecisionProjection] = None
        if record is not None:
            accepted_projection = self.projector.project(record)
        return DecisionOrchestrationResult(
            status=OrchestrationStatus.COMPLETED,
            context_id=context.context_id,
            trigger=context.trigger.value,
            runtime_mode=context.runtime_mode.value,
            decision=accepted,
            active_record=record,
            home_assistant=accepted_projection,
            stability=stability,
            diagnostics={
                **common,
                "stability_disposition": stability.disposition.value,
            },
        )
