from dataclasses import replace
from datetime import datetime, timedelta, timezone

from poolos.decision_intelligence import (
    AlternativeStatus,
    DecisionAlternative,
    DecisionExplanation,
    DecisionOutcome,
)
from poolos.decision_stability import (
    DecisionStabilityEngine,
    DecisionStabilityPolicy,
    StabilityDisposition,
)


BASE = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def decision(
    decision_id="d1",
    *,
    selected="heat",
    confidence=0.8,
    evaluated_at=BASE,
    goal="heat:pool",
):
    return DecisionExplanation(
        decision_id=decision_id,
        evaluated_at=evaluated_at,
        goal=goal,
        outcome=DecisionOutcome.SELECTED,
        selected_alternative_id=selected,
        confidence=confidence,
        evidence=(),
        checks=(),
        alternatives=(
            DecisionAlternative(
                alternative_id=selected,
                label=selected,
                status=AlternativeStatus.SELECTED,
                rank=1,
                score=confidence,
            ),
        ),
        summary="decision",
    )


def test_initial_decision_is_accepted():
    proposed = decision()
    result = DecisionStabilityEngine().evaluate(proposed)
    assert result.disposition is StabilityDisposition.INITIAL
    assert result.decision_changed


def test_equivalent_decision_is_retained_even_with_new_id():
    active = decision("active")
    proposed = replace(active, decision_id="proposal", confidence=0.95)
    result = DecisionStabilityEngine().evaluate(proposed, active)
    assert result.disposition is StabilityDisposition.RETAIN_EQUIVALENT
    assert not result.decision_changed
    assert result.active_decision_id == "active"


def test_minimum_lifetime_retains_materially_different_decision():
    active = decision("active")
    proposed = decision(
        "proposal",
        selected="wait",
        confidence=0.99,
        evaluated_at=BASE + timedelta(minutes=5),
    )
    engine = DecisionStabilityEngine(
        DecisionStabilityPolicy(minimum_lifetime=timedelta(minutes=30))
    )
    result = engine.evaluate(proposed, active)
    assert result.disposition is StabilityDisposition.RETAIN_MINIMUM_LIFETIME
    assert not result.decision_changed


def test_confidence_hysteresis_retains_small_gain():
    active = decision("active", confidence=0.80)
    proposed = decision(
        "proposal",
        selected="wait",
        confidence=0.84,
        evaluated_at=BASE + timedelta(hours=1),
    )
    engine = DecisionStabilityEngine(
        DecisionStabilityPolicy(confidence_hysteresis=0.05)
    )
    result = engine.evaluate(proposed, active)
    assert result.disposition is StabilityDisposition.RETAIN_CONFIDENCE_HYSTERESIS


def test_material_change_supersedes_after_thresholds():
    active = decision("active", confidence=0.70)
    proposed = decision(
        "proposal",
        selected="wait",
        confidence=0.90,
        evaluated_at=BASE + timedelta(hours=1),
    )
    engine = DecisionStabilityEngine(
        DecisionStabilityPolicy(
            minimum_lifetime=timedelta(minutes=30),
            confidence_hysteresis=0.10,
        )
    )
    result = engine.evaluate(proposed, active)
    assert result.disposition is StabilityDisposition.SUPERSEDE
    assert result.decision_changed


def test_policy_validation():
    for policy in (
        lambda: DecisionStabilityPolicy(minimum_lifetime=timedelta(seconds=-1)),
        lambda: DecisionStabilityPolicy(confidence_hysteresis=1.1),
    ):
        try:
            policy()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid policy should fail")
