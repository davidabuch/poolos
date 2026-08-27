"""Command-free daily filtration obligation and TOU scheduling policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from .operating_baselines import (
    PumpOperatingBaselines,
    command_disabled_criterion,
    pump_baseline_criterion,
)
from .operational_intent import (
    IntentCriterion,
    OperationalIntent,
    OperationalIntentPriority,
    OperationalIntentSource,
    OperationalIntentType,
)
from .time_of_use_policy import TimeOfUseProfile, TimeOfUseTier


@dataclass(frozen=True, slots=True)
class FiltrationObligation:
    """Explicit daily runtime work; deferment never erases remaining work."""

    required_runtime: timedelta
    completed_runtime: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.required_runtime < timedelta(0):
            raise ValueError("required_runtime must not be negative")
        if self.completed_runtime < timedelta(0):
            raise ValueError("completed_runtime must not be negative")

    @property
    def remaining_runtime(self) -> timedelta:
        return max(timedelta(0), self.required_runtime - self.completed_runtime)

    def record_completed(self, runtime: timedelta) -> FiltrationObligation:
        if runtime < timedelta(0):
            raise ValueError("completed runtime increment must not be negative")
        return FiltrationObligation(
            required_runtime=self.required_runtime,
            completed_runtime=min(
                self.required_runtime,
                self.completed_runtime + runtime,
            ),
        )


@dataclass(frozen=True, slots=True)
class FiltrationTargetBand:
    maximum_temperature_f: float | None
    required_runtime: timedelta


@dataclass(frozen=True, slots=True)
class TemperatureFiltrationPolicy:
    """Initial configurable daily runtime targets using trusted water temperature."""

    bands: tuple[FiltrationTargetBand, ...] = (
        FiltrationTargetBand(70.0, timedelta(hours=6)),
        FiltrationTargetBand(80.0, timedelta(hours=8)),
        FiltrationTargetBand(85.0, timedelta(hours=9)),
        FiltrationTargetBand(90.0, timedelta(hours=10)),
        FiltrationTargetBand(None, timedelta(hours=12)),
    )

    def target_for(self, trusted_temperature_f: float) -> timedelta:
        for band in self.bands:
            if band.maximum_temperature_f is None or trusted_temperature_f <= band.maximum_temperature_f:
                return max(timedelta(hours=6), band.required_runtime)
        raise AssertionError("filtration bands require an unbounded final band")


@dataclass(frozen=True, slots=True)
class DailyFiltrationDebt:
    day: date
    required_runtime: timedelta
    credited_runtime: timedelta = timedelta(0)

    @property
    def remaining_runtime(self) -> timedelta:
        return max(timedelta(0), self.required_runtime - self.credited_runtime)


@dataclass(frozen=True, slots=True)
class FiltrationDebtLedger:
    """At most two days of debt, repaid oldest-first by valid pool circulation."""

    debts: tuple[DailyFiltrationDebt, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.debts, key=lambda item: item.day))
        if len(ordered) > 2 or len({item.day for item in ordered}) != len(ordered):
            raise ValueError("filtration ledger requires unique debt for at most two days")
        object.__setattr__(self, "debts", ordered)

    @property
    def remaining_runtime(self) -> timedelta:
        return sum((item.remaining_runtime for item in self.debts), timedelta(0))

    def credit_circulation(
        self,
        elapsed: timedelta,
        *,
        pool_routed_through_filter: bool,
        confirmed_grid_outage: bool = False,
    ) -> FiltrationDebtLedger:
        if elapsed < timedelta(0):
            raise ValueError("circulation elapsed time must not be negative")
        if not pool_routed_through_filter:
            return self
        credit = elapsed * (2 / 3) if confirmed_grid_outage else elapsed
        remaining_credit = credit
        updated: list[DailyFiltrationDebt] = []
        for debt in self.debts:
            applied = min(debt.remaining_runtime, remaining_credit)
            updated.append(
                DailyFiltrationDebt(
                    debt.day,
                    debt.required_runtime,
                    debt.credited_runtime + applied,
                )
            )
            remaining_credit -= applied
        return FiltrationDebtLedger(tuple(updated))


class FiltrationDisposition(str, Enum):
    SATISFIED = "satisfied"
    RUN_NOW = "run_now"
    DEFERRED_TOU = "deferred_tou"
    DEFERRED_HIGHER_PRIORITY = "deferred_higher_priority"


@dataclass(frozen=True, slots=True)
class FiltrationAssessment:
    evaluated_at: datetime
    disposition: FiltrationDisposition
    remaining_runtime: timedelta
    tou_tier: TimeOfUseTier
    next_suitable_at: datetime | None
    intent: OperationalIntent | None
    rationale: tuple[str, ...]
    authority: str = "none"
    command_delivery_enabled: bool = False


class FiltrationPolicy:
    """Schedule outstanding filtration without crossing an execution boundary."""

    def __init__(
        self,
        tou_profile: TimeOfUseProfile,
        *,
        baselines: PumpOperatingBaselines = PumpOperatingBaselines(),
    ) -> None:
        self._tou_profile = tou_profile
        self._baselines = baselines

    def evaluate(
        self,
        obligation: FiltrationObligation,
        *,
        evaluated_at: datetime,
        safely_deferrable: bool,
        higher_priority_requirement: bool = False,
    ) -> FiltrationAssessment:
        tier = self._tou_profile.classify(evaluated_at)
        remaining = obligation.remaining_runtime
        if remaining == timedelta(0):
            return FiltrationAssessment(
                evaluated_at,
                FiltrationDisposition.SATISFIED,
                remaining,
                tier,
                None,
                None,
                ("Daily filtration obligation is already satisfied.",),
            )

        if higher_priority_requirement:
            disposition = FiltrationDisposition.DEFERRED_HIGHER_PRIORITY
            reason = "A higher-priority operational requirement defers filtration."
        elif tier is TimeOfUseTier.HIGH_PEAK and safely_deferrable:
            disposition = FiltrationDisposition.DEFERRED_TOU
            reason = "Flexible filtration is deferred during the high-price period."
        else:
            intent = OperationalIntent(
                intent_type=OperationalIntentType.MAINTAIN_CIRCULATION,
                source=OperationalIntentSource.SCHEDULE,
                priority=OperationalIntentPriority.NORMAL,
                description="Complete the outstanding daily filtration obligation",
                requested_at=evaluated_at,
                source_reference="daily-filtration-obligation",
                constraints=(
                    pump_baseline_criterion(
                        rpm=self._baselines.filtration_rpm,
                        operating_mode="ordinary_filtration",
                    ),
                    command_disabled_criterion(),
                    IntentCriterion(
                        code="filtration_runtime_remaining",
                        description="Outstanding daily filtration runtime evidence",
                        parameters={"seconds": remaining.total_seconds()},
                    ),
                ),
            )
            return FiltrationAssessment(
                evaluated_at,
                FiltrationDisposition.RUN_NOW,
                remaining,
                tier,
                evaluated_at,
                intent,
                ("Outstanding filtration should run in the current suitable window.",),
            )

        next_suitable = self._tou_profile.next_at_or_below(
            evaluated_at,
            maximum_tier=TimeOfUseTier.LOW_PEAK,
        )
        return FiltrationAssessment(
            evaluated_at,
            disposition,
            remaining,
            tier,
            next_suitable,
            None,
            (reason, "Remaining filtration obligation is preserved."),
        )
