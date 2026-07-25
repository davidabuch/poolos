"""Clock abstractions that make kernel behavior deterministic in tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Provides the current timezone-aware timestamp."""

    def now(self) -> datetime:
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production clock using UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class FixedClock:
    """Mutable deterministic clock intended for tests and simulations."""

    current: datetime

    def now(self) -> datetime:
        if self.current.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        return self.current
