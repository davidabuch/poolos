from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from poolos.filtration_policy import (
    FiltrationDisposition,
    DailyFiltrationDebt,
    FiltrationDebtLedger,
    FiltrationObligation,
    FiltrationPolicy,
    TemperatureFiltrationPolicy,
)
from poolos.operational_intent import OperationalIntentType
from poolos.pump_optimization import PumpOperationOptimizer, PumpOptimizationPolicy
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE, TimeOfUseTier


LOCAL = ZoneInfo("America/Los_Angeles")


def optimizer() -> PumpOperationOptimizer:
    return PumpOperationOptimizer(
        PumpOptimizationPolicy(
            minimum_rpm=1000,
            maximum_rpm=3200,
            rpm_step=100,
            intent_minimum_rpm={},
        )
    )


def test_high_peak_defers_flexible_filtration_without_erasing_obligation() -> None:
    obligation = FiltrationObligation(
        required_runtime=timedelta(hours=8),
        completed_runtime=timedelta(hours=5),
    )

    result = FiltrationPolicy(LADWP_INITIAL_PROFILE).evaluate(
        obligation,
        evaluated_at=datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL),
        safely_deferrable=True,
    )

    assert result.disposition is FiltrationDisposition.DEFERRED_TOU
    assert result.tou_tier is TimeOfUseTier.HIGH_PEAK
    assert result.remaining_runtime == timedelta(hours=3)
    assert result.intent is None
    assert result.next_suitable_at == datetime(2026, 8, 26, 17, 0, tzinfo=LOCAL)


def test_later_base_period_recommends_catchup_at_filtration_baseline() -> None:
    obligation = FiltrationObligation(timedelta(hours=8), timedelta(hours=5))

    result = FiltrationPolicy(LADWP_INITIAL_PROFILE).evaluate(
        obligation,
        evaluated_at=datetime(2026, 8, 26, 21, 0, tzinfo=LOCAL),
        safely_deferrable=True,
    )

    assert result.disposition is FiltrationDisposition.RUN_NOW
    assert result.intent is not None
    assert result.intent.intent_type is OperationalIntentType.MAINTAIN_CIRCULATION
    optimized = optimizer().optimize((result.intent,))
    assert optimized.recommended_rpm == 2600
    assert result.authority == "none"
    assert result.command_delivery_enabled is False


def test_completed_runtime_reduces_but_never_negates_obligation() -> None:
    obligation = FiltrationObligation(timedelta(hours=2))

    partial = obligation.record_completed(timedelta(minutes=30))
    complete = partial.record_completed(timedelta(hours=5))

    assert obligation.remaining_runtime == timedelta(hours=2)
    assert partial.remaining_runtime == timedelta(minutes=90)
    assert complete.remaining_runtime == timedelta(0)


def test_nondeferrable_obligation_runs_even_during_high_peak() -> None:
    result = FiltrationPolicy(LADWP_INITIAL_PROFILE).evaluate(
        FiltrationObligation(timedelta(hours=1)),
        evaluated_at=datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL),
        safely_deferrable=False,
    )

    assert result.disposition is FiltrationDisposition.RUN_NOW
    assert result.intent is not None


def test_higher_priority_operation_defers_filtration_with_debt_preserved() -> None:
    result = FiltrationPolicy(LADWP_INITIAL_PROFILE).evaluate(
        FiltrationObligation(timedelta(hours=1)),
        evaluated_at=datetime(2026, 8, 26, 11, 0, tzinfo=LOCAL),
        safely_deferrable=False,
        higher_priority_requirement=True,
    )

    assert result.disposition is FiltrationDisposition.DEFERRED_HIGHER_PRIORITY
    assert result.remaining_runtime == timedelta(hours=1)


def test_temperature_bands_define_initial_daily_targets_without_gpm() -> None:
    policy = TemperatureFiltrationPolicy()
    assert policy.target_for(70) == timedelta(hours=6)
    assert policy.target_for(75) == timedelta(hours=8)
    assert policy.target_for(83) == timedelta(hours=9)
    assert policy.target_for(88) == timedelta(hours=10)
    assert policy.target_for(89.9) == timedelta(hours=10)
    assert policy.target_for(90.0) == timedelta(hours=12)
    assert policy.target_for(91) == timedelta(hours=12)
    assert "pump_gpm" not in FiltrationDebtLedger.credit_circulation.__annotations__


@pytest.mark.parametrize(
    ("temperature", "hours"),
    (
        (70.0, 6),
        (70.1, 8),
        (80.0, 8),
        (80.1, 9),
        (85.0, 9),
        (85.1, 10),
        (89.9, 10),
        (90.0, 12),
        (90.1, 12),
    ),
)
def test_temperature_filtration_policy_exact_boundaries(
    temperature: float,
    hours: int,
) -> None:
    assert TemperatureFiltrationPolicy().target_for(temperature) == timedelta(
        hours=hours
    )


@pytest.mark.parametrize(
    ("rpm", "expected_credit"),
    (
        (799.9, timedelta(0)),
        (800, timedelta(minutes=30)),
        (1199.9, timedelta(minutes=30)),
        (1200, timedelta(minutes=40)),
        (1900.9, timedelta(minutes=40)),
        (1901, timedelta(hours=1)),
        (2600, timedelta(hours=1)),
    ),
)
def test_pool_circulation_credit_uses_exact_actual_rpm_bands(
    rpm: float,
    expected_credit: timedelta,
) -> None:
    ledger = FiltrationDebtLedger(
        (DailyFiltrationDebt(date(2026, 8, 26), timedelta(hours=2)),)
    )
    credited = ledger.credit_circulation(
        timedelta(hours=1),
        pool_routed_through_filter=True,
        pump_rpm=rpm,
    )
    assert credited.debts[0].credited_runtime == expected_credit


def test_spa_mode_earns_no_pool_filtration_credit() -> None:
    ledger = FiltrationDebtLedger((DailyFiltrationDebt(date(2026, 8, 26), timedelta(hours=2)),))
    assert (
        ledger.credit_circulation(
            timedelta(hours=1),
            pool_routed_through_filter=False,
            pump_rpm=3000,
        )
        is ledger
    )


def test_actual_rpm_not_outage_label_determines_credit() -> None:
    ledger = FiltrationDebtLedger((DailyFiltrationDebt(date(2026, 8, 26), timedelta(hours=3)),))
    reduced = ledger.credit_circulation(
        timedelta(minutes=90),
        pool_routed_through_filter=True,
        pump_rpm=1500,
    )
    full = ledger.credit_circulation(
        timedelta(minutes=90),
        pool_routed_through_filter=True,
        pump_rpm=2100,
    )
    assert reduced.remaining_runtime == timedelta(hours=2)
    assert full.remaining_runtime == timedelta(minutes=90)


def test_two_day_debt_persists_and_is_repaid_oldest_first() -> None:
    ledger = FiltrationDebtLedger(
        (
            DailyFiltrationDebt(date(2026, 8, 25), timedelta(hours=2)),
            DailyFiltrationDebt(date(2026, 8, 26), timedelta(hours=3)),
        )
    )
    credited = ledger.credit_circulation(
        timedelta(hours=2, minutes=30),
        pool_routed_through_filter=True,
        pump_rpm=2600,
    )
    assert credited.debts[0].remaining_runtime == timedelta(0)
    assert credited.debts[1].remaining_runtime == timedelta(hours=2, minutes=30)


def test_actual_overnight_work_reduces_debt_used_by_opportunistic_policy() -> None:
    ledger = FiltrationDebtLedger((DailyFiltrationDebt(date(2026, 8, 25), timedelta(hours=2)),))
    morning = ledger.credit_circulation(
        timedelta(hours=2),
        pool_routed_through_filter=True,
        pump_rpm=2600,
    )
    assert morning.remaining_runtime == timedelta(0)
