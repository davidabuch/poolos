"""Persistent-restraint state for human Pool-Off safety preemption.

The core object is command-free. It records only whether automatic Pool
mutation is restrained; Home Assistant owns persistence and operator surfaces.
It never represents equipment ownership and Resume never issues a command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from .filtration_policy import FiltrationOperationalDayPolicy
from types import MappingProxyType
from typing import Callable, Mapping


class PoolAutomaticControlSuppressionSource(StrEnum):
    """Positive origin for one automatic Pool-control restraint."""

    MANUAL_POOLOS_OFF_REQUEST = "manual_poolos_off_request"
    EXTERNAL_NATIVE_OFF = "external_native_off"
    OPERATOR_RESTRAINT = "operator_restraint"
    RESTORED = "restored"


class SpaAutomaticControlSuppressionSource(StrEnum):
    """Positive origin for one automatic Spa-control restraint."""

    MANUAL_POOLOS_OFF_REQUEST = "manual_poolos_off_request"
    EXTERNAL_NATIVE_OFF = "external_native_off"
    OPERATOR_RESTRAINT = "operator_restraint"
    RESTORED = "restored"


_TRANSIENT_POOL_SOURCES = frozenset(
    {
        PoolAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
        PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
    }
)

_TRANSIENT_SPA_SOURCES = frozenset(
    {
        SpaAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
        SpaAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
    }
)


def pool_suppression_is_current(
    state: "PoolAutomaticControlSuppressionState",
    *,
    evaluated_at: datetime,
    timezone: ZoneInfo,
) -> bool:
    """Return whether one Pool restraint remains valid for this operational day."""

    _require_aware(evaluated_at)

    if not state.suppressed:
        return False

    if state.source not in _TRANSIENT_POOL_SOURCES:
        return True

    if state.suppressed_at is None:
        return True

    policy = FiltrationOperationalDayPolicy()
    return policy.day_for(state.suppressed_at, timezone) == policy.day_for(
        evaluated_at,
        timezone,
    )


def spa_suppression_is_current(
    state: "SpaAutomaticControlSuppressionState",
    *,
    evaluated_at: datetime,
    timezone: ZoneInfo,
) -> bool:
    """Return whether one Spa restraint remains valid for this operational day."""

    _require_aware(evaluated_at)

    if not state.suppressed:
        return False

    if state.source not in _TRANSIENT_SPA_SOURCES:
        return True

    if state.suppressed_at is None:
        return True

    policy = FiltrationOperationalDayPolicy()
    return policy.day_for(state.suppressed_at, timezone) == policy.day_for(
        evaluated_at,
        timezone,
    )


@dataclass(frozen=True, slots=True)
class PoolAutomaticControlSuppressionState:
    """Immutable current restraint; it carries no equipment authority."""

    suppressed: bool = False
    source: PoolAutomaticControlSuppressionSource | None = None
    suppressed_at: datetime | None = None
    reason: str | None = None
    generation: int = 0

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("suppression generation must not be negative")
        if self.suppressed:
            if self.source is None or self.suppressed_at is None or not self.reason:
                raise ValueError("active suppression requires source, time, and reason")
            _require_aware(self.suppressed_at)
        elif any(item is not None for item in (self.source, self.suppressed_at, self.reason)):
            raise ValueError("inactive suppression cannot retain latch provenance")


@dataclass(slots=True)
class PoolAutomaticControlSuppression:
    """One bounded, explicit, command-free Pool automation restraint."""

    state: PoolAutomaticControlSuppressionState = field(
        default_factory=PoolAutomaticControlSuppressionState
    )
    _listeners: list[Callable[[PoolAutomaticControlSuppressionState], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def suppress(
        self,
        *,
        source: PoolAutomaticControlSuppressionSource,
        suppressed_at: datetime,
        reason: str,
    ) -> PoolAutomaticControlSuppressionState:
        """Latch a positive operator/external Off fact without actuating anything."""

        _require_aware(suppressed_at)
        if not reason.strip():
            raise ValueError("suppression reason must not be empty")
        source = PoolAutomaticControlSuppressionSource(source)
        if (
            self.state.suppressed
            and self.state.source is source
            and self.state.suppressed_at == suppressed_at
            and self.state.reason == reason
        ):
            return self.state
        self.state = PoolAutomaticControlSuppressionState(
            suppressed=True,
            source=source,
            suppressed_at=suppressed_at,
            reason=reason,
            generation=self.state.generation + 1,
        )
        self._publish()
        return self.state

    def resume(self, *, resumed_at: datetime) -> PoolAutomaticControlSuppressionState:
        """Clear only the restraint; never create ownership or physical work."""

        _require_aware(resumed_at)
        if not self.state.suppressed:
            return self.state
        self.state = PoolAutomaticControlSuppressionState(
            generation=self.state.generation + 1
        )
        self._publish()
        return self.state

    def add_listener(
        self,
        listener: Callable[[PoolAutomaticControlSuppressionState], None],
    ) -> Callable[[], None]:
        """Observe bounded state changes; registration performs no mutation."""

        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def diagnostics(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "pool_manual_off_suppression": self.state.suppressed,
                "pool_manual_off_suppression_source": (
                    None if self.state.source is None else self.state.source.value
                ),
                "pool_manual_off_suppression_at": (
                    None
                    if self.state.suppressed_at is None
                    else self.state.suppressed_at.isoformat()
                ),
                "pool_manual_off_suppression_reason": self.state.reason,
                "pool_manual_off_suppression_generation": self.state.generation,
                "pool_manual_off_resume_required": self.state.suppressed,
                "authority": "none",
                "command_delivery_performed": False,
            }
        )

    def _publish(self) -> None:
        for listener in tuple(self._listeners):
            listener(self.state)


@dataclass(frozen=True, slots=True)
class SpaAutomaticControlSuppressionState:
    """Immutable Spa restraint; it carries no equipment authority."""

    suppressed: bool = False
    source: SpaAutomaticControlSuppressionSource | None = None
    suppressed_at: datetime | None = None
    reason: str | None = None
    generation: int = 0

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("suppression generation must not be negative")
        if self.suppressed:
            if self.source is None or self.suppressed_at is None or not self.reason:
                raise ValueError("active suppression requires source, time, and reason")
            _require_aware(self.suppressed_at)
        elif any(item is not None for item in (self.source, self.suppressed_at, self.reason)):
            raise ValueError("inactive suppression cannot retain latch provenance")


@dataclass(slots=True)
class SpaAutomaticControlSuppression:
    """One bounded, command-free Spa automation restraint."""

    state: SpaAutomaticControlSuppressionState = field(
        default_factory=SpaAutomaticControlSuppressionState
    )
    _listeners: list[Callable[[SpaAutomaticControlSuppressionState], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def suppress(
        self,
        *,
        source: SpaAutomaticControlSuppressionSource,
        suppressed_at: datetime,
        reason: str,
    ) -> SpaAutomaticControlSuppressionState:
        _require_aware(suppressed_at)
        if not reason.strip():
            raise ValueError("suppression reason must not be empty")
        source = SpaAutomaticControlSuppressionSource(source)
        if (
            self.state.suppressed
            and self.state.source is source
            and self.state.suppressed_at == suppressed_at
            and self.state.reason == reason
        ):
            return self.state
        self.state = SpaAutomaticControlSuppressionState(
            suppressed=True,
            source=source,
            suppressed_at=suppressed_at,
            reason=reason,
            generation=self.state.generation + 1,
        )
        self._publish()
        return self.state

    def resume(self, *, resumed_at: datetime) -> SpaAutomaticControlSuppressionState:
        _require_aware(resumed_at)
        if not self.state.suppressed:
            return self.state
        self.state = SpaAutomaticControlSuppressionState(
            generation=self.state.generation + 1
        )
        self._publish()
        return self.state

    def add_listener(
        self,
        listener: Callable[[SpaAutomaticControlSuppressionState], None],
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def diagnostics(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "spa_manual_off_suppression": self.state.suppressed,
                "spa_manual_off_suppression_source": (
                    None if self.state.source is None else self.state.source.value
                ),
                "spa_manual_off_suppression_at": (
                    None
                    if self.state.suppressed_at is None
                    else self.state.suppressed_at.isoformat()
                ),
                "spa_manual_off_suppression_reason": self.state.reason,
                "spa_manual_off_suppression_generation": self.state.generation,
                "spa_manual_off_resume_required": self.state.suppressed,
                "authority": "none",
                "command_delivery_performed": False,
            }
        )

    def _publish(self) -> None:
        for listener in tuple(self._listeners):
            listener(self.state)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("suppression timestamp must be timezone-aware")


__all__ = [
    "PoolAutomaticControlSuppression",
    "PoolAutomaticControlSuppressionSource",
    "PoolAutomaticControlSuppressionState",
    "pool_suppression_is_current",
    "SpaAutomaticControlSuppression",
    "SpaAutomaticControlSuppressionSource",
    "SpaAutomaticControlSuppressionState",
    "spa_suppression_is_current",
]
