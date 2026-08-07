from datetime import datetime, timezone

import pytest

from poolos.operational_intent import OperationalIntent, OperationalIntentPriority, OperationalIntentSource, OperationalIntentType
from poolos.operator_recommendation import OperatorRecommendationBuilder, OperatorRecommendationStatus
from poolos.pump_optimization import PumpOperationOptimizer, PumpOptimizationPolicy

NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def intent(kind: OperationalIntentType) -> OperationalIntent:
    return OperationalIntent(intent_type=kind, source=OperationalIntentSource.OPERATOR, priority=OperationalIntentPriority.NORMAL, description=kind.value, requested_at=NOW, source_reference=kind.value)


def optimizer() -> PumpOperationOptimizer:
    return PumpOperationOptimizer(PumpOptimizationPolicy(minimum_rpm=1000, maximum_rpm=3000, rpm_step=250, intent_minimum_rpm={OperationalIntentType.MAINTAIN_CIRCULATION: 1250, OperationalIntentType.HEAT_POOL: 2000}))


def test_recommendation_exposes_selected_rpm_without_command() -> None:
    selected = (intent(OperationalIntentType.HEAT_POOL),)
    recommendation = OperatorRecommendationBuilder().build(selected, optimizer().optimize(selected))
    assert recommendation.status is OperatorRecommendationStatus.RECOMMENDED
    assert recommendation.recommended_pump_rpm == 2000
    assert recommendation.summary == "Recommend pump operation at 2000 RPM."
    assert recommendation.to_dict()["command_delivery_enabled"] is False
    assert recommendation.to_dict()["authority"] == "none"


def test_no_operation_becomes_no_action() -> None:
    selected = (intent(OperationalIntentType.MANUAL_OPERATOR_REQUEST),)
    recommendation = OperatorRecommendationBuilder().build(selected, optimizer().optimize(selected))
    assert recommendation.status is OperatorRecommendationStatus.NO_ACTION
    assert recommendation.recommended_pump_rpm is None


def test_infeasible_becomes_blocked() -> None:
    selected = (intent(OperationalIntentType.HEAT_POOL),)
    impossible = PumpOperationOptimizer(PumpOptimizationPolicy(minimum_rpm=1000, maximum_rpm=1500, rpm_step=250, intent_minimum_rpm={OperationalIntentType.HEAT_POOL: 2000}))
    recommendation = OperatorRecommendationBuilder().build(selected, impossible.optimize(selected))
    assert recommendation.status is OperatorRecommendationStatus.BLOCKED
    assert recommendation.recommended_pump_rpm is None
    assert "infeasible" in recommendation.expected_effect.lower()


def test_recommendation_identity_is_deterministic() -> None:
    selected = (intent(OperationalIntentType.MAINTAIN_CIRCULATION),)
    result = optimizer().optimize(selected)
    builder = OperatorRecommendationBuilder()
    assert builder.build(selected, result).recommendation_id == builder.build(selected, result).recommendation_id


def test_provenance_mismatch_is_rejected() -> None:
    circulation = (intent(OperationalIntentType.MAINTAIN_CIRCULATION),)
    heating = (intent(OperationalIntentType.HEAT_POOL),)
    with pytest.raises(ValueError, match="provenance"):
        OperatorRecommendationBuilder().build(circulation, optimizer().optimize(heating))


def test_constraints_and_expected_effect_are_explainable() -> None:
    selected = (intent(OperationalIntentType.HEAT_POOL),)
    recommendation = OperatorRecommendationBuilder().build(selected, optimizer().optimize(selected))
    assert recommendation.constraints == ("Minimum required pump speed: 2000 RPM.", "Maximum permitted pump speed: 3000 RPM.")
    assert "lowest feasible" in recommendation.expected_effect
    assert recommendation.confidence == "deterministic"
