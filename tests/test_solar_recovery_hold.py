from datetime import UTC, datetime, timedelta

from poolos.solar_recovery_hold import (
    SolarRecoveryDisposition,
    SolarRecoveryTracker,
)

NOW = datetime(2026, 9, 19, 20, 0, tzinfo=UTC)


def evaluate(
    tracker: SolarRecoveryTracker,
    *,
    minutes: int,
    roof: float,
    solar: bool,
):
    return tracker.evaluate(
        evaluated_at=NOW + timedelta(minutes=minutes),
        collector_temperature_f=roof,
        solar_active=solar,
        pool_active=True,
        pool_heating_demand=True,
    )


def test_midday_native_solar_off_starts_bounded_recovery_hold() -> None:
    tracker = SolarRecoveryTracker()
    evaluate(tracker, minutes=0, roof=110, solar=True)
    result = evaluate(tracker, minutes=1, roof=89, solar=False)

    assert result.disposition is SolarRecoveryDisposition.HOLD
    assert result.hold_active
    assert result.hold_until == NOW + timedelta(minutes=11)
    assert result.reason_code == "solar_native_off_recovery_hold_started"


def test_recovery_hold_expires_without_manufacturing_continuation() -> None:
    tracker = SolarRecoveryTracker()
    evaluate(tracker, minutes=0, roof=110, solar=True)
    evaluate(tracker, minutes=1, roof=89, solar=False)
    result = evaluate(tracker, minutes=11, roof=88, solar=False)

    assert result.disposition is SolarRecoveryDisposition.EXPIRED
    assert not result.hold_active
    assert result.hold_until is None


def test_yesterday_style_sustained_decline_skips_recovery_hold() -> None:
    tracker = SolarRecoveryTracker()
    evaluate(tracker, minutes=0, roof=101, solar=True)
    evaluate(tracker, minutes=10, roof=98, solar=True)
    evaluate(tracker, minutes=20, roof=93, solar=True)
    result = evaluate(tracker, minutes=30, roof=87, solar=False)

    assert result.disposition is SolarRecoveryDisposition.END_OF_DAY
    assert not result.hold_active
    assert result.reason_code == "solar_native_off_sustained_decline"
    assert result.trend_span_seconds == 1800
    assert result.trend_drop_f == 14
    assert result.declining_fraction == 1


def test_short_abrupt_cloud_drop_is_not_misclassified_as_end_of_day() -> None:
    tracker = SolarRecoveryTracker()
    evaluate(tracker, minutes=0, roof=110, solar=True)
    evaluate(tracker, minutes=5, roof=100, solar=True)
    result = evaluate(tracker, minutes=10, roof=89, solar=False)

    assert result.disposition is SolarRecoveryDisposition.HOLD
