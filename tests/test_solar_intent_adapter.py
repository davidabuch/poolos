from datetime import datetime, timedelta, timezone

from poolos.intent_arbitration import OperationalIntentArbitrator
from poolos.operational_intent import (
    OperationalIntent,
    OperationalIntentPriority,
    OperationalIntentSource,
    OperationalIntentType,
)
from poolos.solar_control_policy import (
    SolarEligibilityInput,
    SolarEligibilityTracker,
)
from poolos.solar_intent_adapter import (
    SolarEligibilityIntentAdapter,
    SolarIntentPolicy,
)


NOW = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)


def observation(
    *,
    at: datetime,
    collector: float = 93.0,
) -> SolarEligibilityInput:
    return SolarEligibilityInput(
        evaluated_at=at,
        pool_active=True,
        spa_active=False,
        solar_active=False,
        water_temperature_f=86.0,
        collector_temperature_f=collector,
        target_temperature_f=90.0,
    )


def eligible_assessment():
    tracker = SolarEligibilityTracker()
    tracker.evaluate(observation(at=NOW))
    return tracker.evaluate(
        observation(at=NOW + timedelta(minutes=10))
    )


def test_ineligible_assessment_produces_no_intent() -> None:
    assessment = SolarEligibilityTracker().evaluate(
        observation(at=NOW)
    )

    result = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert result is None


def test_eligible_assessment_creates_maximize_solar_intent() -> None:
    assessment = eligible_assessment()

    intent = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert intent is not None
    assert intent.intent_type is OperationalIntentType.MAXIMIZE_SOLAR
    assert intent.source is OperationalIntentSource.EQUIPMENT
    assert intent.priority is OperationalIntentPriority.NORMAL
    assert intent.requested_at == assessment.evaluated_at


def test_intent_is_short_lived() -> None:
    assessment = eligible_assessment()

    intent = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert intent is not None
    assert intent.expires_at == (
        assessment.evaluated_at + timedelta(minutes=2)
    )


def test_custom_expiry_is_supported() -> None:
    assessment = eligible_assessment()

    adapter = SolarEligibilityIntentAdapter(
        SolarIntentPolicy(expiry=timedelta(minutes=5))
    )
    intent = adapter.create_intent(assessment)

    assert intent is not None
    assert intent.expires_at == (
        assessment.evaluated_at + timedelta(minutes=5)
    )


def test_intent_preserves_thermal_evidence() -> None:
    assessment = eligible_assessment()

    intent = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert intent is not None

    criterion = next(
        item
        for item in intent.preconditions
        if item.code == "solar_thermally_eligible"
    )

    assert criterion.parameters["differential_f"] == 7.0


def test_intent_explicitly_denies_command_authority() -> None:
    assessment = eligible_assessment()

    intent = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert intent is not None

    criterion = next(
        item
        for item in intent.constraints
        if item.code == "command_authority_disabled"
    )

    assert criterion.parameters["enabled"] is True


def test_maximize_solar_can_coexist_with_circulation() -> None:
    assessment = eligible_assessment()

    solar = SolarEligibilityIntentAdapter().create_intent(assessment)
    assert solar is not None

    circulation = OperationalIntent(
        intent_type=OperationalIntentType.MAINTAIN_CIRCULATION,
        source=OperationalIntentSource.EQUIPMENT,
        priority=OperationalIntentPriority.NORMAL,
        description="Maintain pool circulation",
        requested_at=assessment.evaluated_at,
        source_reference="test-circulation",
    )

    result = OperationalIntentArbitrator().arbitrate(
        (circulation, solar),
        evaluated_at=assessment.evaluated_at,
    )

    assert set(result.selected_intent_ids) == {
        circulation.intent_id,
        solar.intent_id,
    }


def test_adapter_produces_no_command_or_execution_object() -> None:
    assessment = eligible_assessment()

    intent = SolarEligibilityIntentAdapter().create_intent(assessment)

    assert intent is not None
    assert not hasattr(intent, "command")
    assert not hasattr(intent, "commands")
    assert not hasattr(intent, "execution_plan")
    assert not hasattr(intent, "dispatch")
