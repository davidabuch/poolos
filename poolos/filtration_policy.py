"""Command-free daily filtration obligation and TOU scheduling policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

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

    def __post_init__(self) -> None:
        if self.required_runtime < timedelta(0):
            raise ValueError("required_runtime must not be negative")
        if self.credited_runtime < timedelta(0):
            raise ValueError("credited_runtime must not be negative")
        if self.credited_runtime > self.required_runtime:
            raise ValueError("credited_runtime must not exceed required_runtime")

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
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
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


@dataclass(frozen=True, slots=True)
class FiltrationObservation:
    """Minimal authoritative evidence used for deterministic runtime credit."""

    observed_at: datetime
    pool_active: bool | None
    spa_active: bool | None
    pump_rpm: int | None
    water_temperature_f: float | None
    circulation_evidence_usable: bool
    temperature_evidence_usable: bool
    confirmed_grid_outage: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.pump_rpm is not None and self.pump_rpm < 0:
            raise ValueError("pump_rpm must not be negative")

    @property
    def valid_pool_circulation(self) -> bool:
        """Return whether the observed hydraulic state earns Pool credit."""

        return (
            self.circulation_evidence_usable
            and self.pool_active is True
            and self.spa_active is not True
            and self.pump_rpm is not None
            and self.pump_rpm > 0
        )


@dataclass(frozen=True, slots=True)
class FiltrationAccountingSnapshot:
    """Bounded authoritative view of the current two-day filtration ledger."""

    evaluated_at: datetime
    obligation_day: date
    required_runtime: timedelta
    credited_runtime: timedelta
    remaining_runtime: timedelta
    carried_prior_day_debt: timedelta
    total_remaining_runtime: timedelta
    disposition: FiltrationDisposition
    tou_tier: TimeOfUseTier
    next_suitable_at: datetime | None
    ordinary_filtration_rpm: int
    reason_code: str
    rationale: tuple[str, ...]
    debt_days: tuple[date, ...]
    restored_from_history: bool
    temporal_regressions_ignored: int
    authority: str = "none"
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.ordinary_filtration_rpm <= 0:
            raise ValueError("ordinary_filtration_rpm must be positive")
        if self.authority != "none" or self.command_delivery_enabled:
            raise ValueError("filtration accounting must remain command-disabled")
        object.__setattr__(self, "rationale", tuple(self.rationale))
        object.__setattr__(self, "debt_days", tuple(self.debt_days))

    def diagnostics(self) -> Mapping[str, Any]:
        """Return compact Recorder-safe accounting evidence."""

        return MappingProxyType(
            {
                "obligation_day": self.obligation_day.isoformat(),
                "required_runtime_seconds": self.required_runtime.total_seconds(),
                "credited_runtime_seconds": self.credited_runtime.total_seconds(),
                "remaining_runtime_seconds": self.remaining_runtime.total_seconds(),
                "carried_prior_day_debt_seconds": (
                    self.carried_prior_day_debt.total_seconds()
                ),
                "total_remaining_runtime_seconds": (
                    self.total_remaining_runtime.total_seconds()
                ),
                "disposition": self.disposition.value,
                "tou_tier": self.tou_tier.name.lower(),
                "reason_code": self.reason_code,
                "rationale": list(self.rationale[:4]),
                "next_suitable_at": (
                    None
                    if self.next_suitable_at is None
                    else self.next_suitable_at.isoformat()
                ),
                "ordinary_filtration_rpm": self.ordinary_filtration_rpm,
                "debt_days": [item.isoformat() for item in self.debt_days],
                "debt_retention_days": 2,
                "restored_from_observation_history": self.restored_from_history,
                "temporal_regressions_ignored": self.temporal_regressions_ignored,
                "authority": self.authority,
                "command_delivery_enabled": self.command_delivery_enabled,
            }
        )


class FiltrationAccountingTracker:
    """Derive one restart-replayable ledger from chronological observations."""

    def __init__(
        self,
        *,
        tou_profile: TimeOfUseProfile,
        target_policy: TemperatureFiltrationPolicy = TemperatureFiltrationPolicy(),
        baselines: PumpOperatingBaselines = PumpOperatingBaselines(),
    ) -> None:
        self._target_policy = target_policy
        self._tou_profile = tou_profile
        self._policy = FiltrationPolicy(tou_profile, baselines=baselines)
        self._baselines = baselines
        self._timezone = ZoneInfo(tou_profile.timezone_name)
        self._ledger = FiltrationDebtLedger(())
        self._previous: FiltrationObservation | None = None
        self._last_evaluated_at: datetime | None = None
        self._current: FiltrationAccountingSnapshot | None = None
        self._restored_from_history = False
        self._temporal_regressions_ignored = 0

    @property
    def current(self) -> FiltrationAccountingSnapshot | None:
        return self._current

    @property
    def ledger(self) -> FiltrationDebtLedger:
        return self._ledger

    def restore(
        self,
        observations: Iterable[FiltrationObservation],
    ) -> FiltrationAccountingSnapshot | None:
        """Reconstruct state from durable observations without crediting restart gaps."""

        self._ledger = FiltrationDebtLedger(())
        self._previous = None
        self._last_evaluated_at = None
        self._current = None
        self._temporal_regressions_ignored = 0
        self._restored_from_history = True
        for observation in sorted(
            observations,
            key=lambda item: item.observed_at.astimezone(UTC),
        ):
            self.observe(observation)
        self._previous = None
        return self._current

    def observe(
        self,
        observation: FiltrationObservation,
        *,
        safely_deferrable: bool = True,
        higher_priority_requirement: bool = False,
    ) -> FiltrationAccountingSnapshot | None:
        """Apply one observation at most once and return current bounded state."""

        observed_instant = observation.observed_at.astimezone(UTC)
        last_instant = (
            None
            if self._last_evaluated_at is None
            else self._last_evaluated_at.astimezone(UTC)
        )
        if last_instant is not None and observed_instant < last_instant:
            self._temporal_regressions_ignored += 1
            if self._current is not None:
                self._current = self._replace_regression_count(self._current)
            return self._current
        if observed_instant == last_instant:
            return self._current

        local_day = observation.observed_at.astimezone(self._timezone).date()
        self._ensure_daily_requirement(local_day, observation)

        previous = self._previous
        if (
            previous is not None
            and previous.valid_pool_circulation
            and observation.circulation_evidence_usable
        ):
            elapsed = observation.observed_at.astimezone(UTC) - previous.observed_at.astimezone(UTC)
            self._ledger = self._ledger.credit_circulation(
                elapsed,
                pool_routed_through_filter=True,
                confirmed_grid_outage=previous.confirmed_grid_outage,
            )

        self._previous = observation
        self._last_evaluated_at = observation.observed_at
        self._current = self._assessment(
            observation.observed_at,
            local_day,
            safely_deferrable=safely_deferrable,
            higher_priority_requirement=higher_priority_requirement,
        )
        return self._current

    def _ensure_daily_requirement(
        self,
        local_day: date,
        observation: FiltrationObservation,
    ) -> None:
        if any(item.day == local_day for item in self._ledger.debts):
            return
        if (
            not observation.temperature_evidence_usable
            or observation.water_temperature_f is None
        ):
            return
        cutoff = local_day - timedelta(days=1)
        retained = tuple(
            item for item in self._ledger.debts if cutoff <= item.day < local_day
        )
        required = self._target_policy.target_for(observation.water_temperature_f)
        self._ledger = FiltrationDebtLedger(
            (*retained, DailyFiltrationDebt(local_day, required))
        )

    def _assessment(
        self,
        evaluated_at: datetime,
        local_day: date,
        *,
        safely_deferrable: bool,
        higher_priority_requirement: bool,
    ) -> FiltrationAccountingSnapshot:
        current = next(
            (item for item in self._ledger.debts if item.day == local_day),
            None,
        )
        tier = self._tou_profile.classify(evaluated_at)
        if current is None:
            carried = self._ledger.remaining_runtime
            return FiltrationAccountingSnapshot(
                evaluated_at=evaluated_at,
                obligation_day=local_day,
                required_runtime=timedelta(0),
                credited_runtime=timedelta(0),
                remaining_runtime=timedelta(0),
                carried_prior_day_debt=carried,
                total_remaining_runtime=carried,
                disposition=FiltrationDisposition.EVIDENCE_UNAVAILABLE,
                tou_tier=tier,
                next_suitable_at=None,
                ordinary_filtration_rpm=self._baselines.filtration_rpm,
                reason_code="daily_requirement_temperature_unavailable",
                rationale=(
                    "Trusted Pool temperature is unavailable for the daily requirement.",
                ),
                debt_days=tuple(item.day for item in self._ledger.debts),
                restored_from_history=self._restored_from_history,
                temporal_regressions_ignored=self._temporal_regressions_ignored,
            )

        total_required = sum(
            (item.required_runtime for item in self._ledger.debts), timedelta(0)
        )
        total_credited = sum(
            (item.credited_runtime for item in self._ledger.debts), timedelta(0)
        )
        policy = self._policy.evaluate(
            FiltrationObligation(total_required, total_credited),
            evaluated_at=evaluated_at,
            safely_deferrable=safely_deferrable,
            higher_priority_requirement=higher_priority_requirement,
        )
        reason_code = {
            FiltrationDisposition.SATISFIED: "filtration_obligation_satisfied",
            FiltrationDisposition.RUN_NOW: "outstanding_filtration_run_now",
            FiltrationDisposition.DEFERRED_TOU: "filtration_deferred_high_peak",
            FiltrationDisposition.DEFERRED_HIGHER_PRIORITY: (
                "filtration_deferred_higher_priority"
            ),
            FiltrationDisposition.EVIDENCE_UNAVAILABLE: (
                "daily_requirement_temperature_unavailable"
            ),
        }[policy.disposition]
        carried = sum(
            (
                item.remaining_runtime
                for item in self._ledger.debts
                if item.day < local_day
            ),
            timedelta(0),
        )
        return FiltrationAccountingSnapshot(
            evaluated_at=evaluated_at,
            obligation_day=local_day,
            required_runtime=current.required_runtime,
            credited_runtime=current.credited_runtime,
            remaining_runtime=current.remaining_runtime,
            carried_prior_day_debt=carried,
            total_remaining_runtime=self._ledger.remaining_runtime,
            disposition=policy.disposition,
            tou_tier=policy.tou_tier,
            next_suitable_at=policy.next_suitable_at,
            ordinary_filtration_rpm=self._baselines.filtration_rpm,
            reason_code=reason_code,
            rationale=policy.rationale,
            debt_days=tuple(item.day for item in self._ledger.debts),
            restored_from_history=self._restored_from_history,
            temporal_regressions_ignored=self._temporal_regressions_ignored,
        )

    def _replace_regression_count(
        self,
        snapshot: FiltrationAccountingSnapshot,
    ) -> FiltrationAccountingSnapshot:
        return FiltrationAccountingSnapshot(
            evaluated_at=snapshot.evaluated_at,
            obligation_day=snapshot.obligation_day,
            required_runtime=snapshot.required_runtime,
            credited_runtime=snapshot.credited_runtime,
            remaining_runtime=snapshot.remaining_runtime,
            carried_prior_day_debt=snapshot.carried_prior_day_debt,
            total_remaining_runtime=snapshot.total_remaining_runtime,
            disposition=snapshot.disposition,
            tou_tier=snapshot.tou_tier,
            next_suitable_at=snapshot.next_suitable_at,
            ordinary_filtration_rpm=snapshot.ordinary_filtration_rpm,
            reason_code=snapshot.reason_code,
            rationale=snapshot.rationale,
            debt_days=snapshot.debt_days,
            restored_from_history=snapshot.restored_from_history,
            temporal_regressions_ignored=self._temporal_regressions_ignored,
        )
