from datetime import datetime, timezone

import pytest

from poolos.operational_intent import (
    IntentCriterion,
    OperationalIntent,
    OperationalIntentPriority,
    OperationalIntentSource,
    OperationalIntentType,
)
from poolos.pump_optimization import (
    PumpOperationOptimizer,
    PumpOptimizationDisposition,
    PumpOptimizationPolicy,
)

NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def policy(**overrides: object) -> PumpOptimizationPolicy:
    values: dict[str, object] = {
        "minimum_rpm": 1000,
        "maximum_rpm": 3000,
        "rpm_step": 250,
        "intent_minimum_rpm": {
            OperationalIntentType.MAINTAIN_CIRCULATION: 1250,
            OperationalIntentType.MAINTAIN_SANITATION: 1500,
            OperationalIntentType.HEAT_POOL: 2000,
            OperationalIntentType.HEAT_SPA: 2250,
            OperationalIntentType.MAXIMIZE_SOLAR: 1750,
            OperationalIntentType.FREEZE_PROTECTION: 1500,
        },
    }
    values.update(overrides)
    return PumpOptimizationPolicy(**values)  # type: ignore[arg-type]


def intent(
    intent_type: OperationalIntentType,
    *,
    constraints: tuple[IntentCriterion, ...] = (),
) -> OperationalIntent:
    return OperationalIntent(
        intent_type=intent_type,
        source=OperationalIntentSource.OPERATOR,
        priority=OperationalIntentPriority.NORMAL,
        description=intent_type.value,
        requested_at=NOW,
        source_reference=intent_type.value,
        constraints=constraints,
    )


def rpm_constraint(code: str, rpm: object) -> IntentCriterion:
    return IntentCriterion(code, code, {"rpm": rpm})


def test_policy_requires_positive_minimum() -> None:
    with pytest.raises(ValueError, match="minimum_rpm"):
        policy(minimum_rpm=0)


def test_policy_rejects_inverted_envelope() -> None:
    with pytest.raises(ValueError, match="maximum_rpm"):
        policy(minimum_rpm=3000, maximum_rpm=2000)


def test_policy_requires_positive_step() -> None:
    with pytest.raises(ValueError, match="rpm_step"):
        policy(rpm_step=0)


def test_candidates_include_non_aligned_maximum() -> None:
    assert policy(maximum_rpm=3100).candidates()[-1] == 3100


def test_circulation_selects_lowest_feasible_candidate() -> None:
    result = PumpOperationOptimizer(policy()).optimize(
        (intent(OperationalIntentType.MAINTAIN_CIRCULATION),)
    )
    assert result.disposition is PumpOptimizationDisposition.RECOMMENDED
    assert result.recommended_rpm == 1250


def test_multiple_intents_use_strictest_minimum() -> None:
    result = PumpOperationOptimizer(policy()).optimize(
        (
            intent(OperationalIntentType.MAINTAIN_CIRCULATION),
            intent(OperationalIntentType.HEAT_POOL),
        )
    )
    assert result.required_minimum_rpm == 2000
    assert result.recommended_rpm == 2000


def test_solar_requirement_can_coexist_with_circulation() -> None:
    result = PumpOperationOptimizer(policy()).optimize(
        (
            intent(OperationalIntentType.MAINTAIN_CIRCULATION),
            intent(OperationalIntentType.MAXIMIZE_SOLAR),
        )
    )
    assert result.recommended_rpm == 1750


def test_explicit_minimum_can_raise_requirement() -> None:
    constrained = intent(
        OperationalIntentType.MAINTAIN_CIRCULATION,
        constraints=(rpm_constraint("minimum_pump_rpm", 1900),),
    )
    result = PumpOperationOptimizer(policy()).optimize((constrained,))
    assert result.required_minimum_rpm == 1900
    assert result.recommended_rpm == 2000


def test_explicit_maximum_limits_candidate_envelope() -> None:
    constrained = intent(
        OperationalIntentType.HEAT_POOL,
        constraints=(rpm_constraint("maximum_pump_rpm", 2300),),
    )
    result = PumpOperationOptimizer(policy()).optimize((constrained,))
    assert result.permitted_maximum_rpm == 2300
    assert result.recommended_rpm == 2000


def test_conflicting_constraints_are_infeasible_without_fallback() -> None:
    constrained = intent(
        OperationalIntentType.HEAT_POOL,
        constraints=(rpm_constraint("maximum_pump_rpm", 1800),),
    )
    result = PumpOperationOptimizer(policy()).optimize((constrained,))
    assert result.disposition is PumpOptimizationDisposition.INFEASIBLE
    assert result.recommended_rpm is None


def test_requirement_above_hardware_maximum_is_infeasible() -> None:
    result = PumpOperationOptimizer(
        policy(intent_minimum_rpm={OperationalIntentType.HEAT_POOL: 3500})
    ).optimize((intent(OperationalIntentType.HEAT_POOL),))
    assert result.disposition is PumpOptimizationDisposition.INFEASIBLE


def test_unmapped_intent_requires_no_pump_operation() -> None:
    result = PumpOperationOptimizer(policy()).optimize(
        (intent(OperationalIntentType.MANUAL_OPERATOR_REQUEST),)
    )
    assert result.disposition is PumpOptimizationDisposition.NO_OPERATION_REQUIRED
    assert result.recommended_rpm is None
    assert result.candidates == ()


def test_explicit_minimum_can_make_unmapped_intent_pump_relevant() -> None:
    constrained = intent(
        OperationalIntentType.MANUAL_OPERATOR_REQUEST,
        constraints=(rpm_constraint("minimum_pump_rpm", 1600),),
    )
    result = PumpOperationOptimizer(policy()).optimize((constrained,))
    assert result.recommended_rpm == 1750


def test_invalid_constraint_type_is_rejected() -> None:
    constrained = intent(
        OperationalIntentType.MAINTAIN_CIRCULATION,
        constraints=(rpm_constraint("minimum_pump_rpm", "1800"),),
    )
    with pytest.raises(ValueError, match="integer rpm"):
        PumpOperationOptimizer(policy()).optimize((constrained,))


def test_boolean_constraint_is_not_treated_as_integer() -> None:
    constrained = intent(
        OperationalIntentType.MAINTAIN_CIRCULATION,
        constraints=(rpm_constraint("minimum_pump_rpm", True),),
    )
    with pytest.raises(ValueError, match="integer rpm"):
        PumpOperationOptimizer(policy()).optimize((constrained,))


def test_duplicate_intent_identity_is_rejected() -> None:
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    with pytest.raises(ValueError, match="duplicate"):
        PumpOperationOptimizer(policy()).optimize((circulation, circulation))


def test_energy_index_increases_with_rpm() -> None:
    result = PumpOperationOptimizer(policy()).optimize(
        (intent(OperationalIntentType.MAINTAIN_CIRCULATION),)
    )
    assert [item.energy_index for item in result.candidates] == sorted(
        item.energy_index for item in result.candidates
    )


def test_result_preserves_selected_intent_provenance() -> None:
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    result = PumpOperationOptimizer(policy()).optimize((circulation,))
    assert result.selected_intent_ids == (circulation.intent_id,)
    assert str(result.recommended_rpm) in " ".join(result.explain())
