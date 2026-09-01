from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationCreditBand,
    FiltrationDisposition,
    FiltrationObservation,
    FiltrationOperationalDayPolicy,
    PoolTemperatureValidationState,
)
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE, TimeOfUseTier


LOCAL = ZoneInfo("America/Los_Angeles")


def accounting() -> FiltrationAccountingTracker:
    return FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)


def observation(
    at: datetime,
    *,
    pool_active: bool = False,
    spa_active: bool = False,
    rpm: int = 0,
    temperature: float = 88.0,
    circulation_usable: bool = True,
    temperature_usable: bool = True,
) -> FiltrationObservation:
    return FiltrationObservation(
        observed_at=at,
        pool_active=pool_active,
        spa_active=spa_active,
        pump_rpm=rpm,
        water_temperature_f=temperature,
        circulation_evidence_usable=circulation_usable,
        temperature_evidence_usable=temperature_usable,
    )


def test_ten_hour_daily_requirement_and_exact_shadow_day_accounting() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600))
    initial = tracker.observe(
        observation(start + timedelta(minutes=2), pool_active=True, rpm=2600)
    )
    result = tracker.observe(
        observation(start + timedelta(hours=8, minutes=11), pool_active=False)
    )

    assert initial is not None and initial.required_runtime == timedelta(hours=10)
    assert result is not None
    assert result.credited_runtime == timedelta(hours=8, minutes=11)
    assert result.remaining_runtime == timedelta(hours=1, minutes=49)
    assert result.total_remaining_runtime == timedelta(hours=1, minutes=49)


def test_duplicate_and_out_of_order_observations_never_double_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600))
    credited = tracker.observe(
        observation(start + timedelta(hours=1), pool_active=True, rpm=2600)
    )
    duplicate = tracker.observe(
        observation(start + timedelta(hours=1), pool_active=True, rpm=2600)
    )
    regressive = tracker.observe(
        observation(start + timedelta(minutes=30), pool_active=True, rpm=2600)
    )

    assert credited is not None and credited.credited_runtime == timedelta(hours=1)
    assert duplicate is not None and duplicate.credited_runtime == timedelta(hours=1)
    assert regressive is not None and regressive.credited_runtime == timedelta(hours=1)
    assert regressive.temporal_regressions_ignored == 1


def test_spa_only_operation_earns_no_pool_filtration_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(start - timedelta(minutes=3), pool_active=True, rpm=2600)
    )
    baseline = tracker.observe(
        observation(start - timedelta(minutes=1), pool_active=True, rpm=2600)
    )
    tracker.observe(observation(start, spa_active=True, rpm=3000))
    result = tracker.observe(
        observation(start + timedelta(hours=2), spa_active=False, rpm=0)
    )

    assert baseline is not None
    assert result is not None
    assert sum(
        (item.credited_runtime for item in tracker.ledger.debts),
        timedelta(0),
    ) == timedelta(minutes=3)
    assert result.credited_runtime == timedelta(0)
    assert result.total_remaining_runtime == timedelta(hours=15, minutes=57)


def test_unusable_evidence_breaks_credit_continuity_fail_closed() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600))
    stale = tracker.observe(
        observation(
            start + timedelta(hours=1),
            pool_active=True,
            rpm=2600,
            circulation_usable=False,
        )
    )
    recovered = tracker.observe(
        observation(start + timedelta(hours=2), pool_active=True, rpm=2600)
    )

    assert stale is not None and stale.credited_runtime == timedelta(0)
    assert recovered is not None and recovered.credited_runtime == timedelta(0)


def test_high_peak_deferral_preserves_debt_and_later_window_runs_at_2600() -> None:
    tracker = accounting()
    high_peak = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(high_peak - timedelta(minutes=3), pool_active=True, rpm=2600)
    )
    tracker.observe(
        observation(high_peak - timedelta(minutes=1), pool_active=True, rpm=2600)
    )
    deferred = tracker.observe(observation(high_peak))
    later = tracker.observe(observation(high_peak.replace(hour=17)))

    assert deferred is not None
    assert deferred.disposition is FiltrationDisposition.DEFERRED_TOU
    assert deferred.tou_tier is TimeOfUseTier.HIGH_PEAK
    assert deferred.remaining_runtime == timedelta(hours=9, minutes=57)
    assert deferred.next_suitable_at == high_peak.replace(hour=17)
    assert later is not None and later.disposition is FiltrationDisposition.RUN_NOW
    assert later.remaining_runtime == timedelta(hours=9, minutes=57)
    assert later.ordinary_filtration_rpm == 2600


def test_higher_priority_operation_defers_but_does_not_erase_debt() -> None:
    tracker = accounting()
    at = datetime(2026, 8, 28, 11, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(at - timedelta(minutes=3), pool_active=True, rpm=2600)
    )
    tracker.observe(
        observation(at - timedelta(minutes=1), pool_active=True, rpm=2600)
    )
    result = tracker.observe(
        observation(at),
        higher_priority_requirement=True,
    )

    assert result is not None
    assert result.disposition is FiltrationDisposition.DEFERRED_HIGHER_PRIORITY
    assert result.remaining_runtime == timedelta(hours=9, minutes=57)


def test_restore_replays_history_but_never_credits_the_restart_gap() -> None:
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    restored = accounting()
    snapshot = restored.restore(
        (
            observation(start, pool_active=True, rpm=2600),
            observation(start + timedelta(hours=1), pool_active=True, rpm=2600),
        )
    )
    after_restart = restored.observe(
        observation(start + timedelta(hours=3), pool_active=True, rpm=2600)
    )
    continued = restored.observe(
        observation(start + timedelta(hours=3, minutes=30), pool_active=False)
    )

    assert snapshot is not None and snapshot.credited_runtime == timedelta(hours=1)
    assert snapshot.restored_from_history
    assert after_restart is not None
    assert after_restart.credited_runtime == timedelta(hours=1)
    assert continued is not None
    assert continued.credited_runtime == timedelta(hours=1, minutes=30)


def test_restore_live_overlap_credits_only_time_after_replay_high_water() -> None:
    high_water = datetime(2026, 8, 28, 13, 47, 40, tzinfo=LOCAL)
    tracker = accounting()
    restored = tracker.restore(
        (
            observation(high_water - timedelta(hours=1), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )

    overlap = tracker.observe(
        observation(high_water - timedelta(seconds=5), pool_active=True, rpm=2600)
    )
    continued = tracker.observe(
        observation(high_water + timedelta(seconds=25), pool_active=True, rpm=2600)
    )

    assert restored is not None
    assert restored.credited_runtime == timedelta(hours=1)
    assert overlap is not None
    assert overlap.credited_runtime == timedelta(hours=1)
    assert overlap.temporal_regressions_ignored == 0
    assert continued is not None
    assert continued.credited_runtime == timedelta(hours=1, seconds=25)
    assert continued.temporal_regressions_ignored == 0


def test_restore_live_large_gap_uses_first_live_sample_as_zero_credit_baseline() -> None:
    high_water = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker = accounting()
    tracker.restore(
        (
            observation(high_water - timedelta(minutes=2), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )

    baseline = tracker.observe(
        observation(high_water + timedelta(minutes=10), pool_active=True, rpm=2600)
    )
    continued = tracker.observe(
        observation(
            high_water + timedelta(minutes=10, seconds=30),
            pool_active=True,
            rpm=2600,
        )
    )

    assert baseline is not None and baseline.credited_runtime == timedelta(minutes=2)
    assert continued is not None
    assert continued.credited_runtime == timedelta(minutes=2, seconds=30)


def test_restore_live_nonoverlap_does_not_credit_short_restart_gap() -> None:
    high_water = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker = accounting()
    tracker.restore(
        (
            observation(high_water - timedelta(minutes=2), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )

    tracker.observe(
        observation(high_water + timedelta(seconds=10), pool_active=True, rpm=2600)
    )
    continued = tracker.observe(
        observation(high_water + timedelta(seconds=40), pool_active=True, rpm=2600)
    )

    assert continued is not None
    assert continued.credited_runtime == timedelta(minutes=2, seconds=30)


def test_equal_restore_live_timestamp_is_idempotent_then_credits_forward() -> None:
    high_water = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker = accounting()
    tracker.restore(
        (
            observation(high_water - timedelta(minutes=2), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )

    equal = tracker.observe(observation(high_water, pool_active=True, rpm=2600))
    continued = tracker.observe(
        observation(high_water + timedelta(seconds=30), pool_active=True, rpm=2600)
    )

    assert equal is not None and equal.credited_runtime == timedelta(minutes=2)
    assert equal.temporal_regressions_ignored == 0
    assert continued is not None
    assert continued.credited_runtime == timedelta(minutes=2, seconds=30)


def test_true_regression_after_restore_live_handoff_remains_rejected() -> None:
    high_water = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker = accounting()
    tracker.restore(
        (
            observation(high_water - timedelta(minutes=2), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )
    tracker.observe(
        observation(high_water + timedelta(minutes=10), pool_active=True, rpm=2600)
    )
    accepted = tracker.observe(
        observation(
            high_water + timedelta(minutes=10, seconds=30),
            pool_active=True,
            rpm=2600,
        )
    )
    regressive = tracker.observe(
        observation(
            high_water + timedelta(minutes=10, seconds=20),
            pool_active=True,
            rpm=2600,
        )
    )

    assert accepted is not None
    assert accepted.credited_runtime == timedelta(minutes=2, seconds=30)
    assert regressive is not None
    assert regressive.credited_runtime == timedelta(minutes=2, seconds=30)
    assert regressive.temporal_regressions_ignored == 1


def test_duplicate_after_restore_live_handoff_remains_idempotent() -> None:
    high_water = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)
    tracker = accounting()
    tracker.restore(
        (
            observation(high_water - timedelta(minutes=2), pool_active=True, rpm=2600),
            observation(high_water, pool_active=True, rpm=2600),
        )
    )
    baseline_at = high_water + timedelta(minutes=10)
    tracker.observe(observation(baseline_at, pool_active=True, rpm=2600))
    accepted = tracker.observe(
        observation(baseline_at + timedelta(seconds=30), pool_active=True, rpm=2600)
    )
    duplicate = tracker.observe(
        observation(baseline_at + timedelta(seconds=30), pool_active=True, rpm=2600)
    )

    assert accepted is not None
    assert duplicate is not None
    assert duplicate.credited_runtime == accepted.credited_runtime
    assert duplicate.temporal_regressions_ignored == 0


def test_midnight_remains_within_the_same_operational_day() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 28, 23, 30, tzinfo=LOCAL)
    tracker.observe(
        observation(before - timedelta(minutes=2), pool_active=True, rpm=2600)
    )
    tracker.observe(observation(before, pool_active=True, rpm=2600))
    after = tracker.observe(
        observation(before + timedelta(hours=1), pool_active=False)
    )

    assert after is not None
    assert after.obligation_day.isoformat() == "2026-08-28"
    assert after.carried_prior_day_debt == timedelta(0)
    assert after.required_runtime == timedelta(hours=10)
    assert after.credited_runtime == timedelta(hours=1, minutes=2)
    assert after.total_remaining_runtime == timedelta(hours=8, minutes=58)
    assert tuple(item.isoformat() for item in after.debt_days) == ("2026-08-28",)


def test_two_day_retention_is_bounded_to_previous_and_current_day() -> None:
    tracker = accounting()
    first = datetime(2026, 8, 27, 8, 0, tzinfo=LOCAL)
    current = None
    for offset in range(3):
        start = first + timedelta(days=offset)
        tracker.observe(observation(start, pool_active=True, rpm=2600))
        current = tracker.observe(
            observation(start + timedelta(minutes=2), pool_active=True, rpm=2600)
        )
        tracker.observe(observation(start + timedelta(minutes=3)))

    assert current is not None
    assert tuple(item.isoformat() for item in current.debt_days) == (
        "2026-08-28",
        "2026-08-29",
    )


def test_dst_fallback_credit_uses_absolute_elapsed_time() -> None:
    tracker = accounting()
    first = datetime(2026, 11, 1, 1, 30, tzinfo=LOCAL, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=LOCAL, fold=1)
    tracker.observe(
        observation(first - timedelta(minutes=2), pool_active=True, rpm=2600)
    )
    tracker.observe(observation(first, pool_active=True, rpm=2600))
    result = tracker.observe(observation(second, pool_active=False))

    assert result is not None
    assert result.credited_runtime == timedelta(hours=1, minutes=2)


def test_missing_temperature_preserves_minimum_debt_and_reports_validation_state() -> None:
    tracker = accounting()
    at = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(
            at,
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )
    result = tracker.observe(
        observation(
            at + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )

    assert result is not None
    assert result.disposition is FiltrationDisposition.CREDITING
    assert result.reason_code == "filtration_crediting_active_pool_circulation"
    assert result.required_runtime == timedelta(hours=6)
    assert result.temperature_validation_state is (
        PoolTemperatureValidationState.AWAITING_USABLE_TEMPERATURE
    )
    assert result.command_delivery_enabled is False
    assert result.authority == "none"


def test_daily_requirement_increases_with_validated_daily_maximum() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)

    tracker.observe(observation(start, pool_active=True, rpm=2600, temperature=86))
    established = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=86,
        )
    )
    increased = tracker.observe(
        observation(
            start + timedelta(minutes=3),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )

    assert established is not None
    assert established.required_runtime == timedelta(hours=10)
    assert increased is not None
    assert increased.required_runtime == timedelta(hours=12)


def test_pool_temperature_waits_for_hydraulic_stabilization_after_spa() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)

    tracker.observe(
        observation(start, spa_active=True, rpm=3000, temperature=100)
    )
    tracker.observe(
        observation(
            start + timedelta(seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    before_stable = tracker.observe(
        observation(
            start + timedelta(minutes=2, seconds=29),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    stable = tracker.observe(
        observation(
            start + timedelta(minutes=2, seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert before_stable is not None
    assert before_stable.required_runtime == timedelta(hours=6)
    assert stable is not None
    assert stable.required_runtime == timedelta(hours=10)


def test_daily_maximum_never_decreases_and_preserves_existing_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600, temperature=86))
    tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=86,
        )
    )
    increased = tracker.observe(
        observation(
            start + timedelta(hours=6),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )
    cooler = tracker.observe(
        observation(
            start + timedelta(hours=6, minutes=1),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert increased is not None
    assert increased.required_runtime == timedelta(hours=12)
    assert increased.credited_runtime == timedelta(hours=6)
    assert increased.highest_validated_pool_temperature_f == 90
    assert cooler is not None
    assert cooler.required_runtime == timedelta(hours=12)
    assert cooler.highest_validated_pool_temperature_f == 90


def test_satisfied_ten_hour_day_reopens_exactly_two_hours_at_validated_90() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600, temperature=86))
    tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=86,
        )
    )
    reopened = tracker.observe(
        observation(
            start + timedelta(hours=10),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )

    assert reopened is not None
    assert reopened.required_runtime == timedelta(hours=12)
    assert reopened.credited_runtime == timedelta(hours=10)
    assert reopened.remaining_runtime == timedelta(hours=2)


def test_temperature_stabilization_resets_when_pool_route_breaks() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600, temperature=100))
    broken = tracker.observe(
        observation(start + timedelta(minutes=1, seconds=59), temperature=100)
    )
    tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    not_yet_stable = tracker.observe(
        observation(
            start + timedelta(minutes=3, seconds=59),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    stable = tracker.observe(
        observation(
            start + timedelta(minutes=4),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert broken is not None
    assert broken.temperature_validation_state is (
        PoolTemperatureValidationState.AWAITING_POOL_CIRCULATION
    )
    assert not_yet_stable is not None
    assert not_yet_stable.required_runtime == timedelta(hours=6)
    assert stable is not None
    assert stable.required_runtime == timedelta(hours=10)
    assert stable.highest_validated_pool_temperature_f == 87


def test_stable_route_waits_for_usable_temperature_without_restarting_window() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(
            start,
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )
    unavailable = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )
    validated = tracker.observe(
        observation(
            start + timedelta(minutes=2, seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=88,
        )
    )

    assert unavailable is not None
    assert unavailable.temperature_validation_state is (
        PoolTemperatureValidationState.AWAITING_USABLE_TEMPERATURE
    )
    assert validated is not None
    assert validated.required_runtime == timedelta(hours=10)
    assert validated.credited_runtime == timedelta(minutes=2, seconds=30)


def test_temperature_validation_requires_positive_rpm_and_spa_inactive() -> None:
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    for invalid in (
        {"pool_active": True, "rpm": 0},
        {"pool_active": True, "spa_active": True, "rpm": 3000},
        {"pool_active": True, "rpm": 2600, "circulation_usable": False},
    ):
        tracker = accounting()
        tracker.observe(observation(start, temperature=100, **invalid))
        result = tracker.observe(
            observation(start + timedelta(minutes=3), temperature=100, **invalid)
        )
        assert result is not None
        assert result.required_runtime == timedelta(hours=6)
        assert result.highest_validated_pool_temperature_f is None


def test_first_two_stabilization_minutes_still_earn_filtration_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=2600, temperature=88))
    pending = tracker.observe(
        observation(
            start + timedelta(minutes=1),
            pool_active=True,
            rpm=2600,
            temperature=88,
        )
    )
    established = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=88,
        )
    )

    assert pending is not None
    assert pending.currently_earning_credit is True
    assert pending.credited_runtime == timedelta(minutes=1)
    assert established is not None
    assert established.credited_runtime == timedelta(minutes=2)


def test_continuous_stabilization_crosses_midnight_within_operational_day() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 28, 23, 55, tzinfo=LOCAL)
    tracker.observe(observation(before, pool_active=True, rpm=2600, temperature=86))
    previous_day = tracker.observe(
        observation(
            before + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=86,
        )
    )
    new_day = tracker.observe(
        observation(
            before + timedelta(minutes=6),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )

    assert previous_day is not None
    assert previous_day.highest_validated_pool_temperature_f == 86
    assert new_day is not None
    assert new_day.obligation_day.isoformat() == "2026-08-28"
    assert new_day.highest_validated_pool_temperature_f == 90
    assert new_day.required_runtime == timedelta(hours=12)


def test_pool_off_at_midnight_preserves_same_operational_day_temperature() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 28, 23, 55, tzinfo=LOCAL)
    tracker.observe(observation(before, pool_active=True, rpm=2600, temperature=90))
    tracker.observe(
        observation(
            before + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )
    after = tracker.observe(
        observation(before + timedelta(minutes=6), temperature=90)
    )

    assert after is not None
    assert after.obligation_day.isoformat() == "2026-08-28"
    assert after.required_runtime == timedelta(hours=12)
    assert after.highest_validated_pool_temperature_f == 90


def test_restore_reconstructs_stabilization_and_rejects_temperature_mutation() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    restored = tracker.restore(
        (
            observation(start, pool_active=True, rpm=2600, temperature=100),
            observation(
                start + timedelta(minutes=1),
                pool_active=True,
                rpm=2600,
                temperature=100,
            ),
        )
    )
    overlap = tracker.observe(
        observation(
            start + timedelta(minutes=1),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    validated = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )
    duplicate = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    regressive = tracker.observe(
        observation(
            start + timedelta(minutes=1, seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )

    assert restored is not None
    assert overlap is not None
    assert validated is not None
    assert validated.highest_validated_pool_temperature_f == 87
    assert duplicate is not None
    assert duplicate.highest_validated_pool_temperature_f == 87
    assert regressive is not None
    assert regressive.highest_validated_pool_temperature_f == 87
    assert regressive.temporal_regressions_ignored == 1


def test_restart_gap_requires_fresh_temperature_stabilization_without_gap_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    tracker.restore(
        (
            observation(start, pool_active=True, rpm=2600, temperature=100),
            observation(
                start + timedelta(minutes=1),
                pool_active=True,
                rpm=2600,
                temperature=100,
            ),
        )
    )
    live_start = start + timedelta(minutes=10)
    tracker.observe(
        observation(live_start, pool_active=True, rpm=2600, temperature=100)
    )
    not_stable = tracker.observe(
        observation(
            live_start + timedelta(minutes=1, seconds=59),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    stable = tracker.observe(
        observation(
            live_start + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert not_stable is not None
    assert not_stable.required_runtime == timedelta(hours=6)
    assert stable is not None
    assert stable.highest_validated_pool_temperature_f == 87
    assert stable.credited_runtime == timedelta(minutes=3)


def test_spa_at_midnight_requires_new_pool_stabilization() -> None:
    tracker = accounting()
    midnight = datetime(2026, 8, 29, 0, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(
            midnight - timedelta(minutes=1),
            spa_active=True,
            rpm=3000,
            temperature=100,
        )
    )
    tracker.observe(
        observation(midnight, spa_active=True, rpm=3000, temperature=100)
    )
    tracker.observe(
        observation(
            midnight + timedelta(seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    early = tracker.observe(
        observation(
            midnight + timedelta(minutes=2, seconds=29),
            pool_active=True,
            rpm=2600,
            temperature=100,
        )
    )
    stable = tracker.observe(
        observation(
            midnight + timedelta(minutes=2, seconds=30),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert early is not None
    assert early.required_runtime == timedelta(hours=6)
    assert stable is not None
    assert stable.required_runtime == timedelta(hours=10)
    assert stable.highest_validated_pool_temperature_f == 87


def test_operational_day_has_six_hour_minimum_before_temperature_validation() -> None:
    tracker = accounting()
    at = datetime(2026, 8, 31, 9, 0, tzinfo=LOCAL)

    result = tracker.observe(
        observation(at, temperature_usable=False)
    )

    assert result is not None
    assert result.obligation_day.isoformat() == "2026-08-31"
    assert result.required_runtime == timedelta(hours=6)
    assert result.highest_validated_pool_temperature_f is None


def test_midnight_does_not_roll_filtration_operational_day() -> None:
    tracker = accounting()
    before_midnight = datetime(2026, 8, 31, 23, 59, tzinfo=LOCAL)
    after_midnight = before_midnight + timedelta(minutes=2)

    tracker.observe(observation(before_midnight, temperature_usable=False))
    result = tracker.observe(observation(after_midnight, temperature_usable=False))

    assert result is not None
    assert result.obligation_day.isoformat() == "2026-08-31"
    assert result.required_runtime == timedelta(hours=6)


def test_actual_rpm_alone_owns_effective_filtration_credit() -> None:
    start = datetime(2026, 8, 31, 9, 0, tzinfo=LOCAL)

    normal = accounting()
    normal.observe(observation(start, pool_active=True, rpm=1500))
    normal_result = normal.observe(
        observation(start + timedelta(hours=1), pool_active=True, rpm=1500)
    )

    high_rpm = accounting()
    high_rpm.observe(observation(start, pool_active=True, rpm=2100))
    high_rpm_result = high_rpm.observe(
        observation(
            start + timedelta(hours=1),
            pool_active=True,
            rpm=2100,
        )
    )

    assert normal_result is not None
    assert normal_result.credited_runtime == timedelta(minutes=40)
    assert high_rpm_result is not None
    assert high_rpm_result.credited_runtime == timedelta(hours=1)


def test_positive_sub_800_rpm_stabilizes_temperature_but_earns_zero_credit() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 31, 9, 0, tzinfo=LOCAL)
    tracker.observe(
        observation(start, pool_active=True, rpm=799, temperature=90)
    )
    result = tracker.observe(
        observation(
            start + timedelta(minutes=2),
            pool_active=True,
            rpm=799,
            temperature=90,
        )
    )

    assert result is not None
    assert result.temperature_validation_state is (
        PoolTemperatureValidationState.VALIDATED
    )
    assert result.required_runtime == timedelta(hours=12)
    assert result.credited_runtime == timedelta(0)
    assert result.currently_earning_credit is False


def test_exact_0800_boundary_rolls_once_and_repays_oldest_first() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 31, 7, 59, tzinfo=LOCAL)
    tracker.observe(
        observation(
            before,
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )
    result = tracker.observe(
        observation(
            before + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature_usable=False,
        )
    )

    assert result is not None
    assert result.obligation_day.isoformat() == "2026-08-31"
    assert result.required_runtime == timedelta(hours=6)
    assert result.credited_runtime == timedelta(0)
    assert result.carried_prior_day_debt == timedelta(hours=5, minutes=58)
    assert tuple(item.isoformat() for item in result.debt_days) == (
        "2026-08-30",
        "2026-08-31",
    )


def test_operational_day_boundary_is_dst_safe_local_wall_time() -> None:
    policy = FiltrationOperationalDayPolicy()
    spring_day = datetime(2026, 3, 7, 8, tzinfo=LOCAL).date()
    fall_day = datetime(2026, 10, 31, 8, tzinfo=LOCAL).date()

    spring_start = policy.starts_at(spring_day, LOCAL)
    spring_end = policy.next_boundary_after(spring_day, LOCAL)
    fall_start = policy.starts_at(fall_day, LOCAL)
    fall_end = policy.next_boundary_after(fall_day, LOCAL)

    assert spring_start.hour == spring_end.hour == 8
    assert fall_start.hour == fall_end.hour == 8
    assert (
        spring_end.astimezone(ZoneInfo("UTC"))
        - spring_start.astimezone(ZoneInfo("UTC"))
    ) == timedelta(hours=23)
    assert (
        fall_end.astimezone(ZoneInfo("UTC"))
        - fall_start.astimezone(ZoneInfo("UTC"))
    ) == timedelta(hours=25)


def test_daily_maximum_resets_at_0800_not_midnight() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 31, 7, 55, tzinfo=LOCAL)
    tracker.observe(
        observation(before, pool_active=True, rpm=2600, temperature=90)
    )
    prior = tracker.observe(
        observation(
            before + timedelta(minutes=2),
            pool_active=True,
            rpm=2600,
            temperature=90,
        )
    )
    current = tracker.observe(
        observation(
            datetime(2026, 8, 31, 8, 0, tzinfo=LOCAL),
            pool_active=True,
            rpm=2600,
            temperature=87,
        )
    )

    assert prior is not None
    assert prior.obligation_day.isoformat() == "2026-08-30"
    assert prior.required_runtime == timedelta(hours=12)
    assert current is not None
    assert current.obligation_day.isoformat() == "2026-08-31"
    assert current.required_runtime == timedelta(hours=10)
    assert current.highest_validated_pool_temperature_f == 87


def test_credit_diagnostics_expose_actual_rpm_factor_band_and_boundary() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 31, 8, tzinfo=LOCAL)
    tracker.observe(observation(start, pool_active=True, rpm=1500))
    result = tracker.observe(
        observation(start + timedelta(minutes=3), pool_active=True, rpm=1500)
    )

    assert result is not None
    diagnostics = result.diagnostics()
    assert diagnostics["observed_pump_rpm"] == 1500
    assert diagnostics["filtration_credit_factor_ratio"] == "2/3"
    assert diagnostics["filtration_credit_band"] == (
        FiltrationCreditBand.REDUCED_MEDIUM.value
    )
    assert diagnostics["operational_day_started_at"].startswith("2026-08-31T08:00")
    assert diagnostics["next_operational_day_boundary"].startswith(
        "2026-09-01T08:00"
    )


def test_established_timeline_materializes_one_wholly_missed_operational_day() -> None:
    tracker = accounting()
    tracker.observe(
        observation(
            datetime(2026, 8, 31, 7, 0, tzinfo=LOCAL),
            temperature_usable=False,
        )
    )
    result = tracker.observe(
        observation(
            datetime(2026, 9, 1, 9, 0, tzinfo=LOCAL),
            temperature_usable=False,
        )
    )

    assert result is not None
    assert tuple(item.isoformat() for item in result.debt_days) == (
        "2026-08-31",
        "2026-09-01",
    )
    missed, current = tracker.ledger.debts
    assert missed.required_runtime == timedelta(hours=6)
    assert missed.credited_runtime == timedelta(0)
    assert missed.highest_validated_pool_temperature_f is None
    assert current.required_runtime == timedelta(hours=6)


def test_first_ever_observation_does_not_invent_pre_accounting_debt() -> None:
    tracker = accounting()
    result = tracker.observe(
        observation(
            datetime(2026, 9, 1, 9, 0, tzinfo=LOCAL),
            temperature_usable=False,
        )
    )

    assert result is not None
    assert tuple(item.isoformat() for item in result.debt_days) == ("2026-09-01",)
    assert result.carried_prior_day_debt == timedelta(0)


def test_multi_day_gap_remains_bounded_and_recovery_repays_oldest_first() -> None:
    tracker = accounting()
    tracker.observe(
        observation(
            datetime(2026, 8, 27, 9, 0, tzinfo=LOCAL),
            temperature_usable=False,
        )
    )
    recovered_at = datetime(2026, 9, 1, 9, 0, tzinfo=LOCAL)
    tracker.observe(observation(recovered_at, pool_active=True, rpm=2600))
    result = tracker.observe(
        observation(
            recovered_at + timedelta(hours=1),
            pool_active=True,
            rpm=2600,
        )
    )

    assert result is not None
    assert tuple(item.isoformat() for item in result.debt_days) == (
        "2026-08-31",
        "2026-09-01",
    )
    prior, current = tracker.ledger.debts
    assert prior.credited_runtime == timedelta(hours=1)
    assert prior.remaining_runtime == timedelta(hours=5)
    assert current.credited_runtime == timedelta(0)


def test_cross_0800_after_prior_satisfaction_credits_new_day_once() -> None:
    for rpm, elapsed, expected in (
        (2600, timedelta(hours=6), timedelta(minutes=1)),
        (1500, timedelta(hours=9), timedelta(seconds=40)),
    ):
        tracker = accounting()
        before_boundary = datetime(2026, 9, 1, 7, 59, 30, tzinfo=LOCAL)
        tracker.observe(
            observation(
                before_boundary - elapsed,
                pool_active=True,
                rpm=rpm,
                temperature_usable=False,
            )
        )
        satisfied = tracker.observe(
            observation(
                before_boundary,
                pool_active=True,
                rpm=rpm,
                temperature_usable=False,
            )
        )
        result = tracker.observe(
            observation(
                before_boundary + timedelta(minutes=1),
                pool_active=True,
                rpm=rpm,
                temperature_usable=False,
            )
        )

        assert satisfied is not None
        assert satisfied.remaining_runtime == timedelta(0)
        assert result is not None
        assert result.obligation_day.isoformat() == "2026-09-01"
        assert result.credited_runtime == expected
        assert len(tracker.ledger.debts) == 2


def test_restore_live_gap_materializes_missed_day_without_gap_credit() -> None:
    tracker = accounting()
    replayed_at = datetime(2026, 8, 31, 7, 0, tzinfo=LOCAL)
    tracker.restore(
        (observation(replayed_at, pool_active=True, rpm=2600),)
    )
    live_at = datetime(2026, 9, 1, 9, 0, tzinfo=LOCAL)
    baseline = tracker.observe(
        observation(live_at, pool_active=True, rpm=2600)
    )

    assert baseline is not None
    assert tuple(item.isoformat() for item in baseline.debt_days) == (
        "2026-08-31",
        "2026-09-01",
    )
    assert sum(
        (item.credited_runtime for item in tracker.ledger.debts),
        timedelta(0),
    ) == timedelta(0)
