from datetime import datetime, timedelta, timezone

import pytest

from poolos.solar_control_policy import SolarEligibilityDisposition, SolarEligibilityInput, SolarEligibilityPolicy, SolarEligibilityTracker


NOW = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)


def observation(*, at: datetime = NOW, pool_active: bool = True, spa_active: bool = False, solar_active: bool = False, water: float | None = 86, collector: float | None = 93, target: float | None = 90) -> SolarEligibilityInput:
    return SolarEligibilityInput(at, pool_active, spa_active, solar_active, water, collector, target)


def test_default_policy_uses_immediate_activation_and_two_shutdown_holds() -> None:
    policy = SolarEligibilityPolicy()
    assert policy.deactivation_hold == timedelta(minutes=10)
    assert policy.target_satisfaction_hold == timedelta(minutes=10)
    assert policy.minimum_collector_temperature_f == 90


def test_physical_solar_eligibility_is_immediate_without_obsolete_hold() -> None:
    result = SolarEligibilityTracker().evaluate(observation())
    assert result.disposition is SolarEligibilityDisposition.ELIGIBLE
    assert result.eligible


def test_roof_minimum_and_differential_are_both_required() -> None:
    cold = SolarEligibilityTracker().evaluate(observation(water=52, collector=60))
    weak = SolarEligibilityTracker().evaluate(observation(collector=92.9))
    assert cold.reason_code == "collector_below_minimum"
    assert weak.reason_code == "activation_differential_insufficient"


def test_active_solar_differential_shutdown_requires_ten_continuous_minutes() -> None:
    tracker = SolarEligibilityTracker()
    first = tracker.evaluate(observation(solar_active=True, collector=92))
    ninth = tracker.evaluate(observation(at=NOW + timedelta(minutes=9), solar_active=True, collector=92))
    tenth = tracker.evaluate(observation(at=NOW + timedelta(minutes=10), solar_active=True, collector=92))
    assert first.eligible and ninth.eligible
    assert not tenth.eligible
    assert tenth.reason_code == "differential_low_sustained"


def test_differential_recovery_resets_shutdown_timer() -> None:
    tracker = SolarEligibilityTracker()
    tracker.evaluate(observation(solar_active=True, collector=92))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=9), solar_active=True, collector=94))
    restarted = tracker.evaluate(observation(at=NOW + timedelta(minutes=10), solar_active=True, collector=92))
    still_running = tracker.evaluate(observation(at=NOW + timedelta(minutes=19), solar_active=True, collector=92))
    assert restarted.eligible and still_running.eligible


def test_target_satisfaction_shutdown_requires_ten_continuous_minutes() -> None:
    tracker = SolarEligibilityTracker()
    first = tracker.evaluate(observation(solar_active=True, water=90, collector=100))
    tenth = tracker.evaluate(observation(at=NOW + timedelta(minutes=10), solar_active=True, water=90, collector=100))
    assert first.eligible
    assert not tenth.eligible
    assert tenth.reason_code == "target_satisfied_sustained"


def test_target_dip_resets_target_satisfaction_timer() -> None:
    tracker = SolarEligibilityTracker()
    tracker.evaluate(observation(solar_active=True, water=90, collector=100))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=9), solar_active=True, water=89.9, collector=100))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=10), solar_active=True, water=90, collector=100))
    assert tracker.evaluate(observation(at=NOW + timedelta(minutes=19), solar_active=True, water=90, collector=100)).eligible


def test_missing_or_nonchronological_evidence_fails_closed() -> None:
    tracker = SolarEligibilityTracker()
    assert not tracker.evaluate(observation(water=None)).eligible
    tracker.reset()
    tracker.evaluate(observation(at=NOW + timedelta(minutes=1)))
    with pytest.raises(ValueError, match="chronological"):
        tracker.evaluate(observation(at=NOW))


def test_assessment_is_command_disabled_and_has_no_pump_or_gpm_input() -> None:
    result = SolarEligibilityTracker().evaluate(observation())
    assert result.to_dict()["authority"] == "none"
    assert result.to_dict()["command_delivery_enabled"] is False
    assert "pump_gpm" not in SolarEligibilityInput.__dataclass_fields__
