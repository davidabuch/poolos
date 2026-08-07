"""Read-only end-to-end operational intelligence composition for PoolOS.

This module composes intent arbitration, pump optimization, and operator
recommendation generation into one deterministic advisory pipeline. It creates
no commands and has no execution or Home Assistant service-call capability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .intent_arbitration import IntentArbitrationResult, OperationalIntentArbitrator
from .operational_intent import OperationalIntent
from .operator_recommendation import OperatorRecommendation, OperatorRecommendationBuilder
from .pump_optimization import PumpOperationOptimizer, PumpOptimizationResult


@dataclass(frozen=True, slots=True)
class OperationalIntelligenceResult:
    """Immutable evidence produced by one advisory evaluation."""

    arbitration: IntentArbitrationResult
    optimization: PumpOptimizationResult
    recommendation: OperatorRecommendation

    @property
    def selected_intent_ids(self) -> tuple[str, ...]:
        return self.arbitration.selected_intent_ids

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluated_at": self.arbitration.evaluated_at.isoformat(),
            "selected_intent_ids": list(self.selected_intent_ids),
            "arbitration": {
                "selected_intent_ids": list(self.arbitration.selected_intent_ids),
                "explanation": list(self.arbitration.explain()),
            },
            "optimization": {
                "disposition": self.optimization.disposition.value,
                "recommended_rpm": self.optimization.recommended_rpm,
                "selected_intent_ids": list(self.optimization.selected_intent_ids),
                "rationale": list(self.optimization.explain()),
            },
            "recommendation": self.recommendation.to_dict(),
            "authority": "none",
            "command_delivery_enabled": False,
        }


class OperationalIntelligencePipeline:
    """Compose the 11.2A-D layers without crossing an execution boundary."""

    def __init__(
        self,
        optimizer: PumpOperationOptimizer,
        *,
        arbitrator: OperationalIntentArbitrator | None = None,
        recommendation_builder: OperatorRecommendationBuilder | None = None,
    ) -> None:
        self._arbitrator = arbitrator or OperationalIntentArbitrator()
        self._optimizer = optimizer
        self._recommendation_builder = recommendation_builder or OperatorRecommendationBuilder()

    def evaluate(
        self,
        intents: tuple[OperationalIntent, ...],
        *,
        evaluated_at: datetime,
    ) -> OperationalIntelligenceResult:
        arbitration = self._arbitrator.arbitrate(intents, evaluated_at=evaluated_at)
        optimization = self._optimizer.optimize(arbitration.selected)
        recommendation = self._recommendation_builder.build(arbitration.selected, optimization)
        return OperationalIntelligenceResult(arbitration, optimization, recommendation)
