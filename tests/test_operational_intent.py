from datetime import datetime, timedelta, timezone
import json

import pytest

from poolos.operational_intent import (
    IntentCriterion,
    OperationalIntent,
    OperationalIntentLifecycle,
    OperationalIntentPriority,
    OperationalIntentSafetyClass,
    OperationalIntentSource,
    OperationalIntentType,
    canonical_intent_order,
)

NOW = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)


def make_intent(**overrides: object) -> OperationalIntent:
    values = {
        "intent_type": OperationalIntentType.HEAT_POOL,
        "source": OperationalIntentSource.OPERATOR,
        "priority": OperationalIntentPriority.HIGH,
        "description": "Heat the pool to the operator target",
        "requested_at": NOW,
        "source_reference": "operator-request-1",
        "success_criteria": (
            IntentCriterion("target_reached", "Pool temperature reached target", {"target_f": 85}),
        ),
        "constraints": (
            IntentCriterion("prefer_solar", "Prefer available solar heat", {"enabled": True}),
        ),
        "explanation_template": "{description} from {source} at {priority} priority",
    }
    values.update(overrides)
    return OperationalIntent(**values)  # type: ignore[arg-type]


def test_identity_is_deterministic_and_ignores_lifecycle() -> None:
    first = make_intent()
    second = make_intent()
    active = first.transition_to(OperationalIntentLifecycle.ACTIVE)
    assert first.intent_id == second.intent_id == active.intent_id


def test_material_change_changes_identity() -> None:
    assert make_intent().intent_id != make_intent(description="Heat pool to 86 F").intent_id


def test_serialization_round_trip_is_canonical() -> None:
    original = make_intent(expires_at=NOW + timedelta(hours=2))
    restored = OperationalIntent.from_json(original.to_json())
    assert restored == original
    assert restored.to_json() == original.to_json()
    assert json.loads(original.to_json())["intent_id"] == original.intent_id


def test_tampered_identity_is_rejected() -> None:
    payload = make_intent().to_dict()
    payload["intent_id"] = "operational-intent-tampered"
    with pytest.raises(ValueError, match="intent_id"):
        OperationalIntent.from_dict(payload)


def test_criteria_are_immutable_and_canonical() -> None:
    criterion = IntentCriterion("limit", "Limit pump", {"max_rpm": 2500, "enabled": True})
    with pytest.raises(TypeError):
        criterion.parameters["max_rpm"] = 3000  # type: ignore[index]
    assert criterion.to_dict()["parameters"] == {"enabled": True, "max_rpm": 2500}


def test_duplicate_criterion_codes_are_rejected() -> None:
    duplicate = IntentCriterion("same", "Duplicate")
    with pytest.raises(ValueError, match="duplicate"):
        make_intent(constraints=(duplicate, duplicate))


def test_naive_timestamps_and_bad_expiry_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_intent(requested_at=datetime(2026, 8, 6, 12, 0))
    with pytest.raises(ValueError, match="after requested_at"):
        make_intent(expires_at=NOW)


def test_safety_source_requires_safety_priority_and_classification() -> None:
    with pytest.raises(ValueError, match="safety-source"):
        make_intent(source=OperationalIntentSource.SAFETY)
    safety = make_intent(
        intent_type=OperationalIntentType.FREEZE_PROTECTION,
        source=OperationalIntentSource.SAFETY,
        priority=OperationalIntentPriority.SAFETY,
        safety_class=OperationalIntentSafetyClass.SAFETY_CRITICAL,
    )
    assert safety.priority is OperationalIntentPriority.SAFETY


def test_lifecycle_transitions_are_fail_closed() -> None:
    requested = make_intent()
    active = requested.transition_to(OperationalIntentLifecycle.ACTIVE)
    satisfied = active.transition_to(OperationalIntentLifecycle.SATISFIED)
    assert satisfied.lifecycle is OperationalIntentLifecycle.SATISFIED
    with pytest.raises(ValueError, match="invalid"):
        satisfied.transition_to(OperationalIntentLifecycle.ACTIVE)


def test_canonical_order_is_priority_then_time_then_identity() -> None:
    normal = make_intent(priority=OperationalIntentPriority.NORMAL)
    critical_later = make_intent(
        priority=OperationalIntentPriority.CRITICAL,
        requested_at=NOW + timedelta(minutes=1),
        source_reference="later",
    )
    critical_earlier = make_intent(
        priority=OperationalIntentPriority.CRITICAL,
        requested_at=NOW - timedelta(minutes=1),
        source_reference="earlier",
    )
    assert canonical_intent_order((normal, critical_later, critical_earlier)) == (
        critical_earlier,
        critical_later,
        normal,
    )


def test_explanation_is_rendered_from_canonical_metadata() -> None:
    text = make_intent().explain()
    assert "operator" in text
    assert "high priority" in text


def test_unknown_explanation_placeholder_is_rejected() -> None:
    intent = make_intent(explanation_template="{unknown}")
    with pytest.raises(ValueError, match="unknown explanation placeholder"):
        intent.explain()
