from datetime import datetime, timedelta, timezone

import pytest

from poolos.solar_control_policy import (
    SolarEligibilityDisposition,
    SolarEligibilityInput,
    SolarEligibilityPolicy,
    SolarEligibilityTracker,
)


NOW = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)


def observation(
    *,
    at: datetime = NOW,
    pool_active: bool = True,
    spa_active: bool = False,
    solar_active: bool = False,
    water: float | None = 86.0,
    collector: float | None = 93.0,
    target: float | None = 90.0,
) -> SolarEligibilityInput:
    return SolarEligibilityInput(
        evaluated_at=at,
        pool_active=pool_active,
        spa_active=spa_active,
        solar_active=solar_active,
        water_temperature_f=water,
        collector_temperature_f=collector,
        target_temperature_f=target,
    )


def test_default_policy_matches_learned_pool_installation() -> None:
    policy = SolarEligibilityPolicy()

    assert policy.activation_differential_f == 7.0
    assert policy.deactivation_differential_f == 7.0
    assert policy.activation_hold == timedelta(minutes=10)


def test_pool_must_be_circulating() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(pool_active=False)
    )

    assert result.disposition is SolarEligibilityDisposition.BLOCKED
    assert not result.eligible


def test_spa_takeover_blocks_pool_solar() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(spa_active=True)
    )

    assert result.disposition is SolarEligibilityDisposition.BLOCKED
    assert not result.eligible


def test_target_reached_blocks_solar() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(water=90.0, target=90.0)
    )

    assert result.disposition is SolarEligibilityDisposition.BLOCKED
    assert not result.eligible


def test_below_seven_degree_differential_is_blocked() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(collector=92.9)
    )

    assert result.disposition is SolarEligibilityDisposition.BLOCKED
    assert not result.eligible
    assert result.differential_f == pytest.approx(6.9)


def test_exactly_seven_degrees_starts_qualification() -> None:
    result = SolarEligibilityTracker().evaluate(observation())

    assert result.disposition is SolarEligibilityDisposition.QUALIFYING
    assert not result.eligible
    assert result.qualifying_since == NOW
    assert result.qualifying_seconds == 0.0


def test_nine_minutes_is_not_yet_eligible() -> None:
    tracker = SolarEligibilityTracker()

    tracker.evaluate(observation())
    result = tracker.evaluate(
        observation(at=NOW + timedelta(minutes=9))
    )

    assert result.disposition is SolarEligibilityDisposition.QUALIFYING
    assert not result.eligible
    assert result.qualifying_seconds == 9 * 60


def test_ten_continuous_minutes_becomes_eligible() -> None:
    tracker = SolarEligibilityTracker()

    tracker.evaluate(observation())
    result = tracker.evaluate(
        observation(at=NOW + timedelta(minutes=10))
    )

    assert result.disposition is SolarEligibilityDisposition.ELIGIBLE
    assert result.eligible
    assert result.qualifying_seconds == 10 * 60


def test_drop_below_threshold_resets_qualification_timer() -> None:
    tracker = SolarEligibilityTracker()

    tracker.evaluate(observation())
    tracker.evaluate(
        observation(
            at=NOW + timedelta(minutes=9),
            collector=92.0,
        )
    )
    result = tracker.evaluate(
        observation(at=NOW + timedelta(minutes=10))
    )

    assert result.disposition is SolarEligibilityDisposition.QUALIFYING
    assert not result.eligible
    assert result.qualifying_since == NOW + timedelta(minutes=10)
    assert result.qualifying_seconds == 0.0


def test_fresh_ten_minutes_required_after_reset() -> None:
    tracker = SolarEligibilityTracker()

    tracker.evaluate(observation())
    tracker.evaluate(
        observation(
            at=NOW + timedelta(minutes=5),
            collector=92.0,
        )
    )
    tracker.evaluate(
        observation(at=NOW + timedelta(minutes=6))
    )
    result = tracker.evaluate(
        observation(at=NOW + timedelta(minutes=16))
    )

    assert result.disposition is SolarEligibilityDisposition.ELIGIBLE
    assert result.eligible


def test_active_solar_does_not_reapply_ten_minute_activation_delay() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(solar_active=True)
    )

    assert result.disposition is SolarEligibilityDisposition.ELIGIBLE
    assert result.eligible


def test_active_solar_becomes_thermally_ineligible_below_seven() -> None:
    result = SolarEligibilityTracker().evaluate(
        observation(
            solar_active=True,
            collector=92.0,
        )
    )

    assert result.disposition is SolarEligibilityDisposition.BLOCKED
    assert not result.eligible
    assert result.differential_f == 6.0


def test_missing_temperature_telemetry_fails_closed() -> None:
    tracker = SolarEligibilityTracker()

    for item in (
        observation(water=None),
        observation(collector=None),
        observation(target=None),
    ):
        tracker.reset()
        result = tracker.evaluate(item)
        assert result.disposition is SolarEligibilityDisposition.BLOCKED
        assert not result.eligible


def test_assessment_is_explicitly_non_authoritative() -> None:
    payload = SolarEligibilityTracker().evaluate(
        observation()
    ).to_dict()

    assert payload["authority"] == "none"
    assert payload["command_delivery_enabled"] is False


def test_pump_rpm_is_not_part_of_solar_eligibility_input() -> None:
    fields = SolarEligibilityInput.__dataclass_fields__

    assert "pump_rpm" not in fields
    assert "pump_power" not in fields


def test_naive_evaluation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        observation(
            at=datetime(2026, 8, 26, 8, 0),
        )


def test_nonchronological_observation_is_rejected() -> None:
    tracker = SolarEligibilityTracker()

    tracker.evaluate(
        observation(at=NOW + timedelta(minutes=1))
    )

    with pytest.raises(ValueError, match="chronological"):
        tracker.evaluate(observation(at=NOW))


def test_invalid_policy_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        SolarEligibilityPolicy(
            activation_hold=timedelta(seconds=-1)
        )

    with pytest.raises(ValueError):
        SolarEligibilityPolicy(
            activation_differential_f=float("nan")
        )


def test_tracker_produces_no_command_or_execution_object() -> None:
    result = SolarEligibilityTracker().evaluate(observation())

    assert not hasattr(result, "command")
    assert not hasattr(result, "commands")
    assert not hasattr(result, "execution_plan")
    assert not hasattr(result, "dispatch")
