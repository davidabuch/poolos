from datetime import date, timedelta

from poolos.filtration_policy import DailyFiltrationDebt, FiltrationDebtLedger


def ledger() -> FiltrationDebtLedger:
    return FiltrationDebtLedger(
        (DailyFiltrationDebt(date(2026, 9, 27), timedelta(hours=8)),)
    )


def test_pool_sanitation_rpm_receives_full_existing_filtration_credit() -> None:
    credited = ledger().credit_circulation(
        timedelta(hours=1),
        pool_routed_through_filter=True,
        pump_rpm=3200,
    )
    assert credited.debts[0].credited_runtime == timedelta(hours=1)


def test_hot_tub_sanitation_does_not_receive_pool_filtration_credit() -> None:
    credited = ledger().credit_circulation(
        timedelta(hours=1),
        pool_routed_through_filter=False,
        pump_rpm=3200,
    )
    assert credited.debts[0].credited_runtime == timedelta(0)
