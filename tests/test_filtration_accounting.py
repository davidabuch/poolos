from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationDisposition,
    FiltrationObservation,
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
    outage: bool = False,
) -> FiltrationObservation:
    return FiltrationObservation(
        observed_at=at,
        pool_active=pool_active,
        spa_active=spa_active,
        pump_rpm=rpm,
        water_temperature_f=temperature,
        circulation_evidence_usable=circulation_usable,
        temperature_evidence_usable=temperature_usable,
        confirmed_grid_outage=outage,
    )


def test_ten_hour_daily_requirement_and_exact_shadow_day_accounting() -> None:
    tracker = accounting()
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    initial = tracker.observe(observation(start, pool_active=True, rpm=2600))
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
    tracker.observe(observation(start, spa_active=True, rpm=3000))
    result = tracker.observe(
        observation(start + timedelta(hours=2), spa_active=False, rpm=0)
    )

    assert result is not None
    assert result.credited_runtime == timedelta(0)
    assert result.remaining_runtime == timedelta(hours=10)


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
    deferred = tracker.observe(observation(high_peak))
    later = tracker.observe(observation(high_peak.replace(hour=17)))

    assert deferred is not None
    assert deferred.disposition is FiltrationDisposition.DEFERRED_TOU
    assert deferred.tou_tier is TimeOfUseTier.HIGH_PEAK
    assert deferred.remaining_runtime == timedelta(hours=10)
    assert deferred.next_suitable_at == high_peak.replace(hour=17)
    assert later is not None and later.disposition is FiltrationDisposition.RUN_NOW
    assert later.remaining_runtime == timedelta(hours=10)
    assert later.ordinary_filtration_rpm == 2600


def test_higher_priority_operation_defers_but_does_not_erase_debt() -> None:
    tracker = accounting()
    at = datetime(2026, 8, 28, 11, 0, tzinfo=LOCAL)
    result = tracker.observe(
        observation(at),
        higher_priority_requirement=True,
    )

    assert result is not None
    assert result.disposition is FiltrationDisposition.DEFERRED_HIGHER_PRIORITY
    assert result.remaining_runtime == timedelta(hours=10)


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


def test_midnight_rollover_retains_prior_debt_and_repays_oldest_first() -> None:
    tracker = accounting()
    before = datetime(2026, 8, 28, 23, 30, tzinfo=LOCAL)
    tracker.observe(observation(before, pool_active=True, rpm=2600))
    after = tracker.observe(
        observation(before + timedelta(hours=1), pool_active=False)
    )

    assert after is not None
    assert after.obligation_day.isoformat() == "2026-08-29"
    assert after.carried_prior_day_debt == timedelta(hours=9)
    assert after.required_runtime == timedelta(hours=10)
    assert after.credited_runtime == timedelta(0)
    assert after.total_remaining_runtime == timedelta(hours=19)
    assert tuple(item.isoformat() for item in after.debt_days) == (
        "2026-08-28",
        "2026-08-29",
    )


def test_two_day_retention_is_bounded_to_previous_and_current_day() -> None:
    tracker = accounting()
    first = datetime(2026, 8, 27, 8, 0, tzinfo=LOCAL)
    tracker.observe(observation(first))
    tracker.observe(observation(first + timedelta(days=1)))
    current = tracker.observe(observation(first + timedelta(days=2)))

    assert current is not None
    assert tuple(item.isoformat() for item in current.debt_days) == (
        "2026-08-28",
        "2026-08-29",
    )


def test_dst_fallback_credit_uses_absolute_elapsed_time() -> None:
    tracker = accounting()
    first = datetime(2026, 11, 1, 1, 30, tzinfo=LOCAL, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=LOCAL, fold=1)
    tracker.observe(observation(first, pool_active=True, rpm=2600))
    result = tracker.observe(observation(second, pool_active=False))

    assert result is not None
    assert result.credited_runtime == timedelta(hours=1)


def test_missing_temperature_exposes_unavailable_instead_of_satisfied() -> None:
    tracker = accounting()
    at = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    result = tracker.observe(
        observation(at, temperature_usable=False)
    )

    assert result is not None
    assert result.disposition is FiltrationDisposition.EVIDENCE_UNAVAILABLE
    assert result.reason_code == "daily_requirement_temperature_unavailable"
    assert result.command_delivery_enabled is False
    assert result.authority == "none"
