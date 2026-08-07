from datetime import datetime, timedelta, timezone

from poolos.operational_intelligence import OperationalIntelligencePipeline
from poolos.operational_intent import (
    OperationalIntent,
    OperationalIntentPriority,
    OperationalIntentSafetyClass,
    OperationalIntentSource,
    OperationalIntentType,
)
from poolos.operator_recommendation import OperatorRecommendationStatus
from poolos.pump_optimization import PumpOperationOptimizer, PumpOptimizationPolicy

NOW = datetime(2026, 8, 7, 4, 30, tzinfo=timezone.utc)


def intent(
    kind: OperationalIntentType,
    *,
    priority: OperationalIntentPriority = OperationalIntentPriority.NORMAL,
    source: OperationalIntentSource = OperationalIntentSource.OPERATOR,
    safety_class: OperationalIntentSafetyClass = OperationalIntentSafetyClass.NORMAL,
) -> OperationalIntent:
    return OperationalIntent(
        intent_type=kind,
        source=source,
        priority=priority,
        description=kind.value,
        requested_at=NOW - timedelta(minutes=5),
        source_reference=kind.value,
        safety_class=safety_class,
    )


def pipeline(*, maximum_rpm: int = 3000) -> OperationalIntelligencePipeline:
    policy = PumpOptimizationPolicy(
        minimum_rpm=1000,
        maximum_rpm=maximum_rpm,
        rpm_step=250,
        intent_minimum_rpm={
            OperationalIntentType.MAINTAIN_CIRCULATION: 1250,
            OperationalIntentType.HEAT_POOL: 2000,
            OperationalIntentType.HEAT_SPA: 2250,
            OperationalIntentType.MAXIMIZE_SOLAR: 1750,
            OperationalIntentType.FREEZE_PROTECTION: 1500,
        },
    )
    return OperationalIntelligencePipeline(PumpOperationOptimizer(policy))


def test_intent_to_recommendation_vertical_slice_preserves_provenance() -> None:
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    solar = intent(OperationalIntentType.MAXIMIZE_SOLAR)
    result = pipeline().evaluate((solar, circulation), evaluated_at=NOW)
    assert set(result.selected_intent_ids) == {circulation.intent_id, solar.intent_id}
    assert result.optimization.selected_intent_ids == result.selected_intent_ids
    assert result.recommendation.selected_intent_ids == result.selected_intent_ids
    assert result.recommendation.recommended_pump_rpm == 1750


def test_pipeline_is_deterministic_for_equivalent_input_order() -> None:
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    solar = intent(OperationalIntentType.MAXIMIZE_SOLAR)
    first = pipeline().evaluate((circulation, solar), evaluated_at=NOW)
    second = pipeline().evaluate((solar, circulation), evaluated_at=NOW)
    assert first.recommendation.recommendation_id == second.recommendation.recommendation_id
    assert first.to_dict() == second.to_dict()


def test_arbitration_suppression_is_reflected_downstream() -> None:
    freeze = intent(
        OperationalIntentType.FREEZE_PROTECTION,
        priority=OperationalIntentPriority.SAFETY,
        source=OperationalIntentSource.SAFETY,
        safety_class=OperationalIntentSafetyClass.SAFETY_CRITICAL,
    )
    energy = intent(OperationalIntentType.MINIMIZE_ENERGY)
    result = pipeline().evaluate((energy, freeze), evaluated_at=NOW)
    assert result.selected_intent_ids == (freeze.intent_id,)
    assert result.optimization.recommended_rpm == 1500
    assert energy.intent_id not in result.recommendation.selected_intent_ids


def test_no_pump_requirement_produces_no_action_recommendation() -> None:
    manual = intent(OperationalIntentType.MANUAL_OPERATOR_REQUEST)
    result = pipeline().evaluate((manual,), evaluated_at=NOW)
    assert result.recommendation.status is OperatorRecommendationStatus.NO_ACTION
    assert result.recommendation.recommended_pump_rpm is None


def test_infeasible_optimization_produces_blocked_recommendation() -> None:
    heating = intent(OperationalIntentType.HEAT_POOL)
    result = pipeline(maximum_rpm=1500).evaluate((heating,), evaluated_at=NOW)
    assert result.recommendation.status is OperatorRecommendationStatus.BLOCKED
    assert result.recommendation.recommended_pump_rpm is None


def test_serialized_evidence_is_explicitly_non_authoritative() -> None:
    result = pipeline().evaluate(
        (intent(OperationalIntentType.MAINTAIN_CIRCULATION),), evaluated_at=NOW
    )
    payload = result.to_dict()
    assert payload["authority"] == "none"
    assert payload["command_delivery_enabled"] is False
    recommendation = payload["recommendation"]
    assert isinstance(recommendation, dict)
    assert recommendation["authority"] == "none"
    assert recommendation["command_delivery_enabled"] is False


def test_explanation_continuity_survives_entire_pipeline() -> None:
    heating = intent(OperationalIntentType.HEAT_POOL)
    result = pipeline().evaluate((heating,), evaluated_at=NOW)
    payload = result.to_dict()
    arbitration = payload["arbitration"]
    optimization = payload["optimization"]
    recommendation = payload["recommendation"]
    assert isinstance(arbitration, dict)
    assert isinstance(optimization, dict)
    assert isinstance(recommendation, dict)
    assert arbitration["explanation"]
    assert optimization["rationale"]
    assert recommendation["rationale"] == optimization["rationale"]


def test_pipeline_result_contains_no_command_or_execution_object() -> None:
    result = pipeline().evaluate(
        (intent(OperationalIntentType.MAINTAIN_CIRCULATION),), evaluated_at=NOW
    )
    assert not hasattr(result, "command")
    assert not hasattr(result, "execution_plan")
    assert not hasattr(result, "dispatch")
