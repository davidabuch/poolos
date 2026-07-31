"""Planner integration for ranked, explainable, and recorded decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, Optional

from .alternative_ranking import (
    AlternativeCandidate,
    AlternativeRankingEngine,
    RankingResult,
)
from .decision_flight_recorder import DecisionFlightRecord, DecisionRecorder
from .decision_intelligence import (
    AlternativeStatus,
    CheckStatus,
    DecisionCheck,
    DecisionEvidence,
    DecisionExplanation,
    DecisionOutcome,
)
from .human_explanation import HumanExplanationRenderer, HumanReadableExplanation
from .kernel import PoolKernel
from .planning import Plan, PlanObjective, Planner
from .technical_explanation import TechnicalExplanation, TechnicalExplanationRenderer


@dataclass(frozen=True, slots=True)
class DecisionPlanningRequest:
    """Inputs needed to create and explain one planner decision."""

    objective: PlanObjective
    candidates: tuple[AlternativeCandidate, ...]
    evidence: tuple[DecisionEvidence, ...] = ()
    checks: tuple[DecisionCheck, ...] = ()
    summary: Optional[str] = None
    next_change: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.summary is not None and not self.summary.strip():
            raise ValueError("summary must not be empty when supplied")
        if self.next_change is not None and not self.next_change.strip():
            raise ValueError("next_change must not be empty when supplied")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DecisionPlanResult:
    """Complete output from explainable planning."""

    plan: Plan
    ranking: RankingResult
    explanation: DecisionExplanation
    human: HumanReadableExplanation
    technical: TechnicalExplanation
    flight_record: Optional[DecisionFlightRecord] = None


@dataclass(frozen=True, slots=True)
class ExplainablePlanner:
    """Create plans, rank alternatives, explain the result, and optionally record it."""

    planner: Planner
    ranking_engine: AlternativeRankingEngine
    human_renderer: HumanExplanationRenderer = field(
        default_factory=HumanExplanationRenderer
    )
    technical_renderer: TechnicalExplanationRenderer = field(
        default_factory=TechnicalExplanationRenderer
    )
    recorder: Optional[DecisionRecorder] = None

    @staticmethod
    def _outcome(
        ranking: RankingResult,
        checks: tuple[DecisionCheck, ...],
    ) -> DecisionOutcome:
        blocking = any(
            check.blocking and check.status in {CheckStatus.FAILED, CheckStatus.UNKNOWN}
            for check in checks
        )
        if blocking:
            return DecisionOutcome.BLOCKED
        if ranking.selected is not None:
            return DecisionOutcome.SELECTED
        if ranking.ranked:
            return DecisionOutcome.DEFERRED
        return DecisionOutcome.NO_ACTION

    @staticmethod
    def _summary(outcome: DecisionOutcome, ranking: RankingResult) -> str:
        selected = ranking.selected
        if outcome is DecisionOutcome.SELECTED and selected is not None:
            return f"Selected {selected.candidate.label} for execution"
        if outcome is DecisionOutcome.BLOCKED:
            return "Planning decision is blocked"
        if outcome is DecisionOutcome.DEFERRED:
            return "No feasible planning alternative is currently available"
        return "No planning action is required"

    @staticmethod
    def _confidence(
        requested: Optional[float],
        outcome: DecisionOutcome,
        ranking: RankingResult,
    ) -> float:
        if requested is not None:
            return requested
        if outcome is DecisionOutcome.SELECTED and ranking.selected is not None:
            return ranking.selected.score
        return 0.0

    def create_plan(
        self,
        request: DecisionPlanningRequest,
        kernel: PoolKernel,
    ) -> DecisionPlanResult:
        """Create one immutable plan and its complete explanation graph."""

        plan = self.planner.create_plan(request.objective, kernel)
        ranking = self.ranking_engine.rank(request.candidates)
        outcome = self._outcome(ranking, request.checks)
        selected_id = (
            ranking.selected_alternative_id
            if outcome is DecisionOutcome.SELECTED
            else None
        )
        alternatives = ranking.decision_alternatives
        if outcome is not DecisionOutcome.SELECTED:
            alternatives = tuple(
                replace(
                    alternative,
                    status=(
                        AlternativeStatus.FEASIBLE
                        if alternative.status is AlternativeStatus.SELECTED
                        else alternative.status
                    ),
                )
                for alternative in alternatives
            )
        explanation = DecisionExplanation(
            decision_id=plan.plan_id,
            evaluated_at=plan.created_at,
            goal=(
                f"{request.objective.objective_type.value}:"
                f"{request.objective.body_id}"
            ),
            outcome=outcome,
            selected_alternative_id=selected_id,
            confidence=self._confidence(request.confidence, outcome, ranking),
            evidence=request.evidence,
            checks=request.checks,
            alternatives=alternatives,
            summary=request.summary or self._summary(outcome, ranking),
            next_change=request.next_change,
            metadata={
                **dict(request.metadata),
                "plan_id": plan.plan_id,
                "objective_id": plan.objective_id,
                "plan_revision": str(plan.revision),
            },
        )
        human = self.human_renderer.render(explanation)
        technical = self.technical_renderer.render(explanation)
        flight_record = None
        if self.recorder is not None:
            flight_record = self.recorder.record(
                plan_id=plan.plan_id,
                objective_id=plan.objective_id,
                decision=explanation,
                human=human,
                technical=technical,
                recorded_at=plan.created_at,
            )
        return DecisionPlanResult(
            plan=plan,
            ranking=ranking,
            explanation=explanation,
            human=human,
            technical=technical,
            flight_record=flight_record,
        )
