from datetime import datetime, timedelta, timezone

import pytest

from poolos.intent_arbitration import (
    IntentArbitrationPolicy,
    IntentDisposition,
    OperationalIntentArbitrator,
)
from poolos.operational_intent import (
    OperationalIntent,
    OperationalIntentLifecycle,
    OperationalIntentPriority,
    OperationalIntentSafetyClass,
    OperationalIntentSource,
    OperationalIntentType,
)

NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


def intent(
    intent_type: OperationalIntentType,
    *,
    priority: OperationalIntentPriority = OperationalIntentPriority.NORMAL,
    source: OperationalIntentSource = OperationalIntentSource.OPERATOR,
    safety_class: OperationalIntentSafetyClass = OperationalIntentSafetyClass.NORMAL,
    lifecycle: OperationalIntentLifecycle = OperationalIntentLifecycle.REQUESTED,
    requested_at: datetime = NOW - timedelta(minutes=5),
    expires_at: datetime | None = None,
    supersedes_intent_id: str | None = None,
    reference: str | None = None,
) -> OperationalIntent:
    return OperationalIntent(
        intent_type=intent_type,
        source=source,
        priority=priority,
        description=f"Request {intent_type.value}",
        requested_at=requested_at,
        source_reference=reference or intent_type.value,
        safety_class=safety_class,
        lifecycle=lifecycle,
        expires_at=expires_at,
        supersedes_intent_id=supersedes_intent_id,
    )


def test_compatible_intents_are_selected_together() -> None:
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    solar = intent(OperationalIntentType.MAXIMIZE_SOLAR)
    result = OperationalIntentArbitrator().arbitrate((solar, circulation), evaluated_at=NOW)
    assert set(result.selected_intent_ids) == {circulation.intent_id, solar.intent_id}


def test_pool_and_spa_heat_are_mutually_exclusive() -> None:
    pool = intent(OperationalIntentType.HEAT_POOL, priority=OperationalIntentPriority.NORMAL)
    spa = intent(OperationalIntentType.HEAT_SPA, priority=OperationalIntentPriority.HIGH)
    result = OperationalIntentArbitrator().arbitrate((pool, spa), evaluated_at=NOW)
    assert result.selected == (spa,)
    decision = result.decision_for(pool.intent_id)
    assert decision.disposition is IntentDisposition.CONFLICT_SUPPRESSED
    assert decision.winning_intent_id == spa.intent_id


def test_equal_priority_conflict_uses_canonical_time_order() -> None:
    earlier = intent(OperationalIntentType.HEAT_POOL, requested_at=NOW - timedelta(minutes=10))
    later = intent(OperationalIntentType.HEAT_SPA, requested_at=NOW - timedelta(minutes=1))
    result = OperationalIntentArbitrator().arbitrate((later, earlier), evaluated_at=NOW)
    assert result.selected == (earlier,)


def test_freeze_protection_suppresses_energy_savings_and_quiet_hours() -> None:
    freeze = intent(
        OperationalIntentType.FREEZE_PROTECTION,
        priority=OperationalIntentPriority.SAFETY,
        source=OperationalIntentSource.SAFETY,
        safety_class=OperationalIntentSafetyClass.SAFETY_CRITICAL,
    )
    energy = intent(OperationalIntentType.MINIMIZE_ENERGY)
    quiet = intent(OperationalIntentType.QUIET_HOURS)
    result = OperationalIntentArbitrator().arbitrate((energy, quiet, freeze), evaluated_at=NOW)
    assert result.selected == (freeze,)
    assert result.decision_for(energy.intent_id).winning_intent_id == freeze.intent_id
    assert result.decision_for(quiet.intent_id).winning_intent_id == freeze.intent_id


def test_freeze_protection_can_coexist_with_circulation() -> None:
    freeze = intent(
        OperationalIntentType.FREEZE_PROTECTION,
        priority=OperationalIntentPriority.SAFETY,
        source=OperationalIntentSource.SAFETY,
        safety_class=OperationalIntentSafetyClass.SAFETY_CRITICAL,
    )
    circulation = intent(OperationalIntentType.MAINTAIN_CIRCULATION)
    result = OperationalIntentArbitrator().arbitrate((circulation, freeze), evaluated_at=NOW)
    assert result.selected == (freeze, circulation)


def test_terminal_lifecycle_is_ineligible() -> None:
    completed = intent(
        OperationalIntentType.MAINTAIN_CIRCULATION,
        lifecycle=OperationalIntentLifecycle.SATISFIED,
    )
    result = OperationalIntentArbitrator().arbitrate((completed,), evaluated_at=NOW)
    assert result.selected == ()
    assert result.decision_for(completed.intent_id).disposition is IntentDisposition.INELIGIBLE


def test_expired_intent_is_ineligible_without_mutating_lifecycle() -> None:
    expired = intent(
        OperationalIntentType.HEAT_POOL,
        requested_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(minutes=1),
    )
    result = OperationalIntentArbitrator().arbitrate((expired,), evaluated_at=NOW)
    assert result.selected == ()
    assert expired.lifecycle is OperationalIntentLifecycle.REQUESTED


def test_future_request_is_ineligible() -> None:
    future = intent(OperationalIntentType.HEAT_POOL, requested_at=NOW + timedelta(minutes=1))
    result = OperationalIntentArbitrator().arbitrate((future,), evaluated_at=NOW)
    assert result.decision_for(future.intent_id).disposition is IntentDisposition.INELIGIBLE


def test_eligible_superseding_intent_suppresses_prior_identity() -> None:
    old = intent(OperationalIntentType.HEAT_POOL, reference="old")
    new = intent(
        OperationalIntentType.HEAT_POOL,
        priority=OperationalIntentPriority.HIGH,
        requested_at=NOW - timedelta(minutes=1),
        supersedes_intent_id=old.intent_id,
        reference="new",
    )
    result = OperationalIntentArbitrator().arbitrate((old, new), evaluated_at=NOW)
    assert result.selected == (new,)
    assert result.decision_for(old.intent_id).disposition is IntentDisposition.SUPERSEDED
    assert result.decision_for(old.intent_id).winning_intent_id == new.intent_id


def test_ineligible_superseding_intent_does_not_suppress_prior_intent() -> None:
    old = intent(OperationalIntentType.HEAT_POOL, reference="old")
    future = intent(
        OperationalIntentType.HEAT_POOL,
        requested_at=NOW + timedelta(minutes=1),
        supersedes_intent_id=old.intent_id,
        reference="future",
    )
    result = OperationalIntentArbitrator().arbitrate((old, future), evaluated_at=NOW)
    assert result.selected == (old,)


def test_duplicate_intent_identity_fails_closed() -> None:
    item = intent(OperationalIntentType.HEAT_POOL)
    with pytest.raises(ValueError, match="duplicate"):
        OperationalIntentArbitrator().arbitrate((item, item), evaluated_at=NOW)


def test_naive_evaluation_time_fails_closed() -> None:
    item = intent(OperationalIntentType.HEAT_POOL)
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationalIntentArbitrator().arbitrate((item,), evaluated_at=datetime(2026, 8, 7))


def test_custom_policy_can_define_exclusive_group() -> None:
    policy = IntentArbitrationPolicy(
        exclusive_groups=(
            frozenset(
                {
                    OperationalIntentType.MAXIMIZE_SOLAR,
                    OperationalIntentType.MINIMIZE_ENERGY,
                }
            ),
        )
    )
    solar = intent(OperationalIntentType.MAXIMIZE_SOLAR, priority=OperationalIntentPriority.HIGH)
    energy = intent(OperationalIntentType.MINIMIZE_ENERGY)
    result = OperationalIntentArbitrator(policy).arbitrate((energy, solar), evaluated_at=NOW)
    assert result.selected == (solar,)


def test_policy_rejects_single_member_exclusive_group() -> None:
    with pytest.raises(ValueError, match="at least two"):
        IntentArbitrationPolicy(
            exclusive_groups=(frozenset({OperationalIntentType.HEAT_POOL}),)
        )


def test_explanations_cover_every_input_intent_in_canonical_order() -> None:
    high = intent(OperationalIntentType.HEAT_POOL, priority=OperationalIntentPriority.HIGH)
    low = intent(OperationalIntentType.MINIMIZE_ENERGY, priority=OperationalIntentPriority.LOW)
    result = OperationalIntentArbitrator().arbitrate((low, high), evaluated_at=NOW)
    assert len(result.explain()) == 2
    assert result.decisions[0].intent_id == high.intent_id
    assert "selected" in result.explain()[0]


def test_directional_suppression_can_override_canonical_priority() -> None:
    maintenance = intent(
        OperationalIntentType.MAINTENANCE_MODE,
        priority=OperationalIntentPriority.NORMAL,
    )
    heat = intent(
        OperationalIntentType.HEAT_POOL,
        priority=OperationalIntentPriority.HIGH,
    )
    result = OperationalIntentArbitrator().arbitrate((heat, maintenance), evaluated_at=NOW)
    assert result.selected == (maintenance,)
    assert result.decision_for(heat.intent_id).winning_intent_id == maintenance.intent_id
