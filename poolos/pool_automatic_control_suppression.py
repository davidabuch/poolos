"""Persistent-restraint state for human Pool-Off safety preemption.

The core object is command-free. It records only whether automatic Pool
mutation is restrained; Home Assistant owns persistence and operator surfaces.
It never represents equipment ownership and Resume never issues a command.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True, slots=True)
class PoolSemanticOpportunity:
    """One policy reason's bounded cancellation state, without command authority."""

    family: str
    sequence: int = 0
    eligible: bool | None = None
    observed_at: datetime | None = None
    canceled: bool = False
    canceled_opportunity_id: str | None = None

    @property
    def opportunity_id(self) -> str | None:
        return None if self.sequence == 0 else f"pool:{self.family}:{self.sequence}"


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

    _opportunities: dict[str, PoolSemanticOpportunity] = field(
        default_factory=dict, init=False, repr=False,
    )

    def observe_opportunity(
        self, family: str, *, eligible: bool | None, observed_at: datetime,
    ) -> str | None:
        """Consume independent policy evidence, not authorization or plan IDs.

        Unknown evidence leaves the prior eligibility intact. A canceled reason
        can expire only through a later authoritative False -> True boundary.
        This does not restore an execution or create equipment ownership.
        """
        if family not in {"thermal", "filtration"}:
            raise ValueError("unsupported Pool opportunity family")
        _require_aware(observed_at)
        prior = self._opportunities.get(family, PoolSemanticOpportunity(
            family, canceled=self.state.suppressed,
        ))
        if (self.state.suppressed_at is not None
                and observed_at <= self.state.suppressed_at):
            return prior.opportunity_id
        if prior.observed_at is not None and observed_at <= prior.observed_at:
            return prior.opportunity_id
        current = replace(prior, observed_at=observed_at)
        if eligible is not None:
            current = replace(current, eligible=eligible)
            if eligible and prior.eligible is not True:
                current = replace(current, sequence=prior.sequence + 1)
            if not eligible:
                current = replace(current, canceled=False)
        self._opportunities[family] = current
        return current.opportunity_id

    def opportunity_id(self, family: str) -> str | None:
        if family not in {"thermal", "filtration"}:
            raise ValueError("unsupported Pool opportunity family")
        opportunity = self._opportunities.get(family)
        return None if opportunity is None else opportunity.opportunity_id

    def blocks_opportunity(self, family: str) -> bool:
        if family not in {"thermal", "filtration"}:
            raise ValueError("unsupported Pool opportunity family")
        if not self.state.suppressed:
            return False
        if self.state.source not in _TRANSIENT_POOL_SOURCES:
            return True
        opportunity = self._opportunities.get(family)
        return (opportunity is None or opportunity.canceled
                or opportunity.eligible is not True)

    @property
    def globally_suppressed(self) -> bool:
        """Persistent restraint; transient cancellation is checked per purpose."""
        return (self.state.suppressed
                and self.state.source not in _TRANSIENT_POOL_SOURCES)

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
        self._opportunities = {
            family: replace(opportunity, canceled=opportunity.eligible is not False,
                            canceled_opportunity_id=opportunity.opportunity_id)
            for family, opportunity in self._opportunities.items()
        }
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
                "pool_semantic_opportunities": {
                    family: {
                        "opportunity_id": item.opportunity_id,
                        "eligible": item.eligible,
                        "canceled_opportunity_id": item.canceled_opportunity_id,
                        "blocked": self.blocks_opportunity(family),
                    } for family, item in self._opportunities.items()
                },
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
