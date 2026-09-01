"""Command-free daily filtration obligation and TOU scheduling policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from fractions import Fraction
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
    maximum_inclusive: bool = True

    def includes(self, temperature_f: float) -> bool:
        """Return whether the temperature is within this ordered band."""

        if self.maximum_temperature_f is None:
            return True
        if self.maximum_inclusive:
            return temperature_f <= self.maximum_temperature_f
        return temperature_f < self.maximum_temperature_f


@dataclass(frozen=True, slots=True)
class TemperatureFiltrationPolicy:
    """Initial configurable daily runtime targets using trusted water temperature."""

    bands: tuple[FiltrationTargetBand, ...] = (
        FiltrationTargetBand(70.0, timedelta(hours=6)),
        FiltrationTargetBand(80.0, timedelta(hours=8)),
        FiltrationTargetBand(85.0, timedelta(hours=9)),
        FiltrationTargetBand(90.0, timedelta(hours=10), maximum_inclusive=False),
        FiltrationTargetBand(None, timedelta(hours=12)),
    )

    def target_for(self, trusted_temperature_f: float) -> timedelta:
        for band in self.bands:
            if band.includes(trusted_temperature_f):
                return max(timedelta(hours=6), band.required_runtime)
        raise AssertionError("filtration bands require an unbounded final band")


@dataclass(frozen=True, slots=True)
class FiltrationOperationalDayPolicy:
    """Map evidence to the installation's local 08:00 filtration day."""

    boundary: time = time(hour=8)

    def day_for(self, observed_at: datetime, timezone: ZoneInfo) -> date:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        local = observed_at.astimezone(timezone)
        day = local.date()
        if local.timetz().replace(tzinfo=None) < self.boundary:
            day -= timedelta(days=1)
        return day

    def starts_at(self, day: date, timezone: ZoneInfo) -> datetime:
        return datetime.combine(day, self.boundary, tzinfo=timezone)

    def next_boundary_after(self, day: date, timezone: ZoneInfo) -> datetime:
        return self.starts_at(day + timedelta(days=1), timezone)


class FiltrationCreditBand(str, Enum):
    """Bounded installation credit bands derived from observed pump RPM."""

    NO_CREDIT = "no_credit"
    REDUCED_LOW = "reduced_low"
    REDUCED_MEDIUM = "reduced_medium"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class FiltrationRpmCredit:
    """Exact rational filtration credit for one authoritative RPM sample."""

    band: FiltrationCreditBand
    factor: Fraction

    def apply(self, elapsed: timedelta) -> timedelta:
        if elapsed < timedelta(0):
            raise ValueError("filtration elapsed time must not be negative")
        total_microseconds = (
            elapsed.days * 86_400_000_000
            + elapsed.seconds * 1_000_000
            + elapsed.microseconds
        )
        credited_microseconds = (
            total_microseconds * self.factor.numerator // self.factor.denominator
        )
        return timedelta(microseconds=credited_microseconds)


def filtration_rpm_credit(pump_rpm: float | None) -> FiltrationRpmCredit:
    """Return the sole filtration-credit factor for actual observed RPM."""

    if pump_rpm is None or pump_rpm < 800:
        return FiltrationRpmCredit(FiltrationCreditBand.NO_CREDIT, Fraction(0))
    if pump_rpm < 1200:
        return FiltrationRpmCredit(FiltrationCreditBand.REDUCED_LOW, Fraction(1, 2))
    if pump_rpm < 1901:
        return FiltrationRpmCredit(
            FiltrationCreditBand.REDUCED_MEDIUM,
            Fraction(2, 3),
        )
    return FiltrationRpmCredit(FiltrationCreditBand.FULL, Fraction(1))


@dataclass(frozen=True, slots=True)
class DailyFiltrationDebt:
    day: date
    required_runtime: timedelta
    credited_runtime: timedelta = timedelta(0)
    highest_validated_pool_temperature_f: float | None = None

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
        pump_rpm: float | None,
    ) -> FiltrationDebtLedger:
        if elapsed < timedelta(0):
            raise ValueError("circulation elapsed time must not be negative")
        if not pool_routed_through_filter:
            return self
        credit = filtration_rpm_credit(pump_rpm).apply(elapsed)
        remaining_credit = credit
        updated: list[DailyFiltrationDebt] = []
        for debt in self.debts:
            applied = min(debt.remaining_runtime, remaining_credit)
            updated.append(
                DailyFiltrationDebt(
                    debt.day,
                    debt.required_runtime,
                    debt.credited_runtime + applied,
                    debt.highest_validated_pool_temperature_f,
                )
            )
            remaining_credit -= applied
        return FiltrationDebtLedger(tuple(updated))

    def ensure_daily_minimum(
        self,
        *,
        day: date,
        required_runtime: timedelta = timedelta(hours=6),
    ) -> FiltrationDebtLedger:
        """Materialize one bounded daily minimum before evidence-based increases."""

        if any(item.day == day for item in self.debts):
            return self
        cutoff = day - timedelta(days=1)
        retained = tuple(item for item in self.debts if cutoff <= item.day < day)
        return FiltrationDebtLedger(
            (*retained, DailyFiltrationDebt(day, required_runtime))
        )

    def record_daily_temperature(
        self,
        *,
        day: date,
        temperature_f: float,
        required_runtime: timedelta,
    ) -> FiltrationDebtLedger:
        """Create or monotonically raise one retained day's validated target."""

        existing = next((item for item in self.debts if item.day == day), None)
        if existing is not None:
            previous_maximum = existing.highest_validated_pool_temperature_f
            if previous_maximum is not None and temperature_f <= previous_maximum:
                return self
            updated = tuple(
                DailyFiltrationDebt(
                    item.day,
                    max(item.required_runtime, required_runtime),
                    item.credited_runtime,
                    temperature_f,
                )
                if item.day == day
                else item
                for item in self.debts
            )
            return FiltrationDebtLedger(updated)

        cutoff = day - timedelta(days=1)
        retained = tuple(item for item in self.debts if cutoff <= item.day < day)
        return FiltrationDebtLedger(
            (
                *retained,
                DailyFiltrationDebt(
                    day,
                    required_runtime,
                    highest_validated_pool_temperature_f=temperature_f,
                ),
            )
        )


class FiltrationDisposition(str, Enum):
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    SATISFIED = "satisfied"
    CREDITING = "crediting"
    RUN_NOW = "run_now"
    DEFERRED_TOU = "deferred_tou"
    DEFERRED_HIGHER_PRIORITY = "deferred_higher_priority"


class PoolTemperatureValidationState(str, Enum):
    """Bounded diagnostic state for hydraulic Pool-temperature validation."""

    AWAITING_POOL_CIRCULATION = "awaiting_pool_circulation"
    STABILIZING_POOL_TEMPERATURE = "stabilizing_pool_temperature"
    AWAITING_USABLE_TEMPERATURE = "awaiting_usable_temperature"
    VALIDATED = "validated"


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
        filtration_in_progress: bool = False,
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

        if filtration_in_progress:
            rationale = (
                "Valid Pool circulation is actively earning filtration credit."
                if not higher_priority_requirement
                else (
                    "Valid Pool circulation is actively earning filtration credit "
                    "while serving another operational requirement."
                )
            )
            return FiltrationAssessment(
                evaluated_at,
                FiltrationDisposition.CREDITING,
                remaining,
                tier,
                None,
                None,
                (rationale,),
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
    pump_rpm: float | None
    water_temperature_f: float | None
    circulation_evidence_usable: bool
    temperature_evidence_usable: bool

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.pump_rpm is not None and self.pump_rpm < 0:
            raise ValueError("pump_rpm must not be negative")

    @property
    def valid_pool_routing(self) -> bool:
        """Return whether Pool hydraulics are usable with positive actual RPM."""

        return (
            self.circulation_evidence_usable
            and self.pool_active is True
            and self.spa_active is not True
            and self.pump_rpm is not None
            and self.pump_rpm > 0
        )

    @property
    def earning_filtration_credit(self) -> bool:
        """Return whether current routing has a nonzero observed-RPM factor."""

        return (
            self.valid_pool_routing
            and filtration_rpm_credit(self.pump_rpm).factor > 0
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
    currently_earning_credit: bool
    restored_from_history: bool
    temporal_regressions_ignored: int
    highest_validated_pool_temperature_f: float | None
    temperature_validation_state: PoolTemperatureValidationState
    pool_temperature_stabilization_started_at: datetime | None
    pool_temperature_stabilization_remaining: timedelta | None
    operational_day_started_at: datetime
    next_operational_day_boundary: datetime
    observed_pump_rpm: float | None
    filtration_credit_factor: Fraction
    filtration_credit_band: FiltrationCreditBand
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
                "currently_earning_credit": self.currently_earning_credit,
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
                "highest_validated_pool_temperature_f": (
                    self.highest_validated_pool_temperature_f
                ),
                "temperature_validation_state": (
                    self.temperature_validation_state.value
                ),
                "pool_temperature_stabilization_started_at": (
                    None
                    if self.pool_temperature_stabilization_started_at is None
                    else self.pool_temperature_stabilization_started_at.isoformat()
                ),
                "pool_temperature_stabilization_remaining_seconds": (
                    None
                    if self.pool_temperature_stabilization_remaining is None
                    else self.pool_temperature_stabilization_remaining.total_seconds()
                ),
                "operational_day_started_at": (
                    self.operational_day_started_at.isoformat()
                ),
                "next_operational_day_boundary": (
                    self.next_operational_day_boundary.isoformat()
                ),
                "observed_pump_rpm": self.observed_pump_rpm,
                "filtration_credit_factor": float(self.filtration_credit_factor),
                "filtration_credit_factor_ratio": (
                    f"{self.filtration_credit_factor.numerator}/"
                    f"{self.filtration_credit_factor.denominator}"
                ),
                "filtration_credit_band": self.filtration_credit_band.value,
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
        operational_day_policy: FiltrationOperationalDayPolicy = (
            FiltrationOperationalDayPolicy()
        ),
    ) -> None:
        self._target_policy = target_policy
        self._tou_profile = tou_profile
        self._policy = FiltrationPolicy(tou_profile, baselines=baselines)
        self._baselines = baselines
        self._operational_day_policy = operational_day_policy
        self._timezone = ZoneInfo(tou_profile.timezone_name)
        self._ledger = FiltrationDebtLedger(())
        self._previous: FiltrationObservation | None = None
        self._last_evaluated_at: datetime | None = None
        self._current: FiltrationAccountingSnapshot | None = None
        self._restored_from_history = False
        self._temporal_regressions_ignored = 0
        self._restore_high_water: datetime | None = None
        self._restore_overlap_baseline: FiltrationObservation | None = None
        self._pool_temperature_stabilization_started_at: datetime | None = None
        self._temperature_validation_state = (
            PoolTemperatureValidationState.AWAITING_POOL_CIRCULATION
        )

    _POOL_TEMPERATURE_STABILIZATION = timedelta(minutes=2)

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
        self._restore_high_water = None
        self._restore_overlap_baseline = None
        self._pool_temperature_stabilization_started_at = None
        self._temperature_validation_state = (
            PoolTemperatureValidationState.AWAITING_POOL_CIRCULATION
        )
        for observation in sorted(
            observations,
            key=lambda item: item.observed_at.astimezone(UTC),
        ):
            self.observe(observation)
        self._restore_high_water = self._last_evaluated_at
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
        handoff = self._observe_restore_handoff(
            observation,
            safely_deferrable=safely_deferrable,
            higher_priority_requirement=higher_priority_requirement,
        )
        if handoff is not None:
            return handoff

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

        operational_day = self._operational_day_policy.day_for(
            observation.observed_at,
            self._timezone,
        )
        self._ensure_retained_operational_days(operational_day)
        self._update_temperature_validation(operational_day, observation)

        previous = self._previous
        if (
            previous is not None
            and previous.valid_pool_routing
            and observation.circulation_evidence_usable
        ):
            elapsed = (
                observation.observed_at.astimezone(UTC)
                - previous.observed_at.astimezone(UTC)
            )
            self._credit_interval(
                elapsed,
                pump_rpm=previous.pump_rpm,
            )

        self._previous = observation
        self._last_evaluated_at = observation.observed_at
        self._current = self._assessment(
            observation.observed_at,
            operational_day,
            safely_deferrable=safely_deferrable,
            higher_priority_requirement=higher_priority_requirement,
            filtration_in_progress=observation.earning_filtration_credit,
        )
        return self._current

    def _ensure_retained_operational_days(self, operational_day: date) -> None:
        """Materialize bounded minima after an established chronology advances."""

        if self._last_evaluated_at is not None:
            previous_observation_day = self._operational_day_policy.day_for(
                self._last_evaluated_at,
                self._timezone,
            )
            if operational_day > previous_observation_day:
                self._ledger = self._ledger.ensure_daily_minimum(
                    day=operational_day - timedelta(days=1)
                )
        self._ledger = self._ledger.ensure_daily_minimum(day=operational_day)

    def _observe_restore_handoff(
        self,
        observation: FiltrationObservation,
        *,
        safely_deferrable: bool,
        higher_priority_requirement: bool,
    ) -> FiltrationAccountingSnapshot | None:
        """Join restored and live timelines without overlap or restart-gap credit."""

        high_water = self._restore_high_water
        if high_water is None:
            return None

        observed_instant = observation.observed_at.astimezone(UTC)
        high_water_instant = high_water.astimezone(UTC)
        if observed_instant <= high_water_instant:
            overlap = self._restore_overlap_baseline
            if (
                overlap is None
                or observed_instant > overlap.observed_at.astimezone(UTC)
            ):
                self._restore_overlap_baseline = observation
                return self._establish_baseline(
                    observation,
                    effective_at=high_water,
                    preserve_restored_temperature_state=True,
                    safely_deferrable=safely_deferrable,
                    higher_priority_requirement=higher_priority_requirement,
                )
            return self._current

        overlap = self._restore_overlap_baseline
        self._restore_high_water = None
        self._restore_overlap_baseline = None
        if overlap is None:
            return self._establish_baseline(
                observation,
                effective_at=observation.observed_at,
                preserve_restored_temperature_state=False,
                safely_deferrable=safely_deferrable,
                higher_priority_requirement=higher_priority_requirement,
            )

        self._previous = replace(overlap, observed_at=high_water)
        self._last_evaluated_at = high_water
        return None

    def _establish_baseline(
        self,
        observation: FiltrationObservation,
        *,
        effective_at: datetime,
        preserve_restored_temperature_state: bool,
        safely_deferrable: bool,
        higher_priority_requirement: bool,
    ) -> FiltrationAccountingSnapshot:
        """Accept one live baseline while deliberately earning no new credit."""

        baseline = replace(observation, observed_at=effective_at)
        operational_day = self._operational_day_policy.day_for(
            effective_at,
            self._timezone,
        )
        self._ensure_retained_operational_days(operational_day)
        if not preserve_restored_temperature_state:
            self._pool_temperature_stabilization_started_at = None
            self._temperature_validation_state = (
                PoolTemperatureValidationState.AWAITING_POOL_CIRCULATION
            )
            self._update_temperature_validation(operational_day, baseline)
        self._previous = baseline
        self._last_evaluated_at = effective_at
        self._current = self._assessment(
            effective_at,
            operational_day,
            safely_deferrable=safely_deferrable,
            higher_priority_requirement=higher_priority_requirement,
            filtration_in_progress=baseline.earning_filtration_credit,
        )
        return self._current

    def _update_temperature_validation(
        self,
        local_day: date,
        observation: FiltrationObservation,
    ) -> None:
        if not observation.valid_pool_routing:
            self._pool_temperature_stabilization_started_at = None
            self._temperature_validation_state = (
                PoolTemperatureValidationState.AWAITING_POOL_CIRCULATION
            )
            return

        started_at = self._pool_temperature_stabilization_started_at
        if started_at is None:
            started_at = observation.observed_at
            self._pool_temperature_stabilization_started_at = started_at
        elapsed = observation.observed_at.astimezone(UTC) - started_at.astimezone(UTC)
        if elapsed < self._POOL_TEMPERATURE_STABILIZATION:
            self._temperature_validation_state = (
                PoolTemperatureValidationState.STABILIZING_POOL_TEMPERATURE
            )
            return

        if (
            not observation.temperature_evidence_usable
            or observation.water_temperature_f is None
        ):
            self._temperature_validation_state = (
                PoolTemperatureValidationState.AWAITING_USABLE_TEMPERATURE
            )
            return

        self._temperature_validation_state = PoolTemperatureValidationState.VALIDATED
        required = self._target_policy.target_for(observation.water_temperature_f)
        self._ledger = self._ledger.record_daily_temperature(
            day=local_day,
            temperature_f=observation.water_temperature_f,
            required_runtime=required,
        )

    def _credit_interval(
        self,
        elapsed: timedelta,
        *,
        pump_rpm: float | None,
    ) -> None:
        """Credit provable work oldest-first using actual observed RPM."""

        self._ledger = self._ledger.credit_circulation(
            elapsed,
            pool_routed_through_filter=True,
            pump_rpm=pump_rpm,
        )

    def _temperature_diagnostics(
        self,
        *,
        evaluated_at: datetime,
        current: DailyFiltrationDebt | None,
    ) -> tuple[
        float | None,
        PoolTemperatureValidationState,
        datetime | None,
        timedelta | None,
    ]:
        started_at = self._pool_temperature_stabilization_started_at
        remaining: timedelta | None = None
        if started_at is not None:
            elapsed = evaluated_at.astimezone(UTC) - started_at.astimezone(UTC)
            remaining = max(
                timedelta(0),
                self._POOL_TEMPERATURE_STABILIZATION - elapsed,
            )
        return (
            None
            if current is None
            else current.highest_validated_pool_temperature_f,
            self._temperature_validation_state,
            started_at,
            remaining,
        )

    def _assessment(
        self,
        evaluated_at: datetime,
        local_day: date,
        *,
        safely_deferrable: bool,
        higher_priority_requirement: bool,
        filtration_in_progress: bool,
    ) -> FiltrationAccountingSnapshot:
        current = next(
            (item for item in self._ledger.debts if item.day == local_day),
            None,
        )
        if current is None:
            raise AssertionError("operational filtration day must be materialized")

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
            filtration_in_progress=filtration_in_progress,
        )
        reason_code = {
            FiltrationDisposition.SATISFIED: "filtration_obligation_satisfied",
            FiltrationDisposition.CREDITING: (
                "filtration_crediting_during_other_operation"
                if higher_priority_requirement
                else "filtration_crediting_active_pool_circulation"
            ),
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
        temperature_diagnostics = self._temperature_diagnostics(
            evaluated_at=evaluated_at,
            current=current,
        )
        rpm_credit = filtration_rpm_credit(
            None if self._previous is None else self._previous.pump_rpm
        )
        operational_day_started_at = self._operational_day_policy.starts_at(
            local_day,
            self._timezone,
        )
        next_boundary = self._operational_day_policy.next_boundary_after(
            local_day,
            self._timezone,
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
            currently_earning_credit=(
                policy.disposition is FiltrationDisposition.CREDITING
            ),
            restored_from_history=self._restored_from_history,
            temporal_regressions_ignored=self._temporal_regressions_ignored,
            highest_validated_pool_temperature_f=temperature_diagnostics[0],
            temperature_validation_state=temperature_diagnostics[1],
            pool_temperature_stabilization_started_at=temperature_diagnostics[2],
            pool_temperature_stabilization_remaining=temperature_diagnostics[3],
            operational_day_started_at=operational_day_started_at,
            next_operational_day_boundary=next_boundary,
            observed_pump_rpm=(
                None if self._previous is None else self._previous.pump_rpm
            ),
            filtration_credit_factor=rpm_credit.factor,
            filtration_credit_band=rpm_credit.band,
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
            currently_earning_credit=snapshot.currently_earning_credit,
            restored_from_history=snapshot.restored_from_history,
            temporal_regressions_ignored=self._temporal_regressions_ignored,
            highest_validated_pool_temperature_f=(
                snapshot.highest_validated_pool_temperature_f
            ),
            temperature_validation_state=snapshot.temperature_validation_state,
            pool_temperature_stabilization_started_at=(
                snapshot.pool_temperature_stabilization_started_at
            ),
            pool_temperature_stabilization_remaining=(
                snapshot.pool_temperature_stabilization_remaining
            ),
            operational_day_started_at=snapshot.operational_day_started_at,
            next_operational_day_boundary=snapshot.next_operational_day_boundary,
            observed_pump_rpm=snapshot.observed_pump_rpm,
            filtration_credit_factor=snapshot.filtration_credit_factor,
            filtration_credit_band=snapshot.filtration_credit_band,
        )
