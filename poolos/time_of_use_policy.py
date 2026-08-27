"""Generic deterministic time-of-use classification for advisory policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from zoneinfo import ZoneInfo


class TimeOfUseTier(IntEnum):
    """Relative price tier; numeric order permits generic comparisons."""

    BASE = 0
    LOW_PEAK = 1
    HIGH_PEAK = 2


@dataclass(frozen=True, slots=True)
class TimeOfUsePeriod:
    """One local-time, half-open tariff period for selected weekdays."""

    weekdays: frozenset[int]
    start_minute: int
    end_minute: int
    tier: TimeOfUseTier

    def __post_init__(self) -> None:
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must contain values from 0 through 6")
        if not 0 <= self.start_minute < self.end_minute <= 24 * 60:
            raise ValueError("TOU period must be a non-empty interval within one day")

    def contains(self, *, weekday: int, minute: int) -> bool:
        return (
            weekday in self.weekdays
            and self.start_minute <= minute < self.end_minute
        )


@dataclass(frozen=True, slots=True)
class TimeOfUseProfile:
    """Versionable tariff data independent of operating decisions."""

    name: str
    timezone_name: str
    periods: tuple[TimeOfUsePeriod, ...]
    default_tier: TimeOfUseTier = TimeOfUseTier.BASE
    effective_from: date | None = None
    effective_until: date | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("TOU profile name must not be blank")
        ZoneInfo(self.timezone_name)
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must not precede effective_from")
        ordered = tuple(
            sorted(
                self.periods,
                key=lambda item: (
                    min(item.weekdays),
                    item.start_minute,
                    item.end_minute,
                    int(item.tier),
                ),
            )
        )
        for day in range(7):
            applicable = [item for item in ordered if day in item.weekdays]
            for first, second in zip(applicable, applicable[1:]):
                if first.end_minute > second.start_minute:
                    raise ValueError("TOU periods must not overlap")
        object.__setattr__(self, "periods", ordered)

    def _local(self, evaluated_at: datetime) -> datetime:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        local = evaluated_at.astimezone(ZoneInfo(self.timezone_name))
        if self.effective_from is not None and local.date() < self.effective_from:
            raise ValueError("TOU profile is not yet effective")
        if self.effective_until is not None and local.date() > self.effective_until:
            raise ValueError("TOU profile is no longer effective")
        return local

    def classify(self, evaluated_at: datetime) -> TimeOfUseTier:
        local = self._local(evaluated_at)
        minute = local.hour * 60 + local.minute
        matches = [
            item.tier
            for item in self.periods
            if item.contains(weekday=local.weekday(), minute=minute)
        ]
        if len(matches) > 1:
            raise ValueError("TOU profile has overlapping matching periods")
        return self.default_tier if not matches else matches[0]

    def next_at_or_below(
        self,
        evaluated_at: datetime,
        *,
        maximum_tier: TimeOfUseTier,
    ) -> datetime:
        """Return the next configured boundary whose tier meets the ceiling."""

        local = self._local(evaluated_at)
        if self.classify(local) <= maximum_tier:
            return local
        candidates = {local}
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(9):
            day_start = start + timedelta(days=day_offset)
            candidates.add(day_start)
            for period in self.periods:
                if day_start.weekday() in period.weekdays:
                    candidates.add(day_start + timedelta(minutes=period.start_minute))
                    candidates.add(day_start + timedelta(minutes=period.end_minute))
        suitable = sorted(
            candidate
            for candidate in candidates
            if candidate >= local and self.classify(candidate) <= maximum_tier
        )
        if not suitable:
            raise ValueError("TOU profile has no suitable future period")
        return suitable[0]


LADWP_INITIAL_PROFILE = TimeOfUseProfile(
    name="ladwp-initial-weekday-tou",
    timezone_name="America/Los_Angeles",
    default_tier=TimeOfUseTier.BASE,
    periods=(
        TimeOfUsePeriod(frozenset(range(5)), 10 * 60, 13 * 60, TimeOfUseTier.LOW_PEAK),
        TimeOfUsePeriod(frozenset(range(5)), 13 * 60, 17 * 60, TimeOfUseTier.HIGH_PEAK),
        TimeOfUsePeriod(frozenset(range(5)), 17 * 60, 20 * 60, TimeOfUseTier.LOW_PEAK),
    ),
)
