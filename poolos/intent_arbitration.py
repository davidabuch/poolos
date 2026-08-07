"""Deterministic, explainable arbitration for canonical PoolOS operational intents.

Arbitration selects a compatible set of eligible intents. It does not optimize
pump operation, create execution plans, call Home Assistant, or actuate equipment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .operational_intent import (
    OperationalIntent,
    OperationalIntentLifecycle,
    OperationalIntentType,
    canonical_intent_order,
)


class IntentDisposition(str, Enum):
    SELECTED = "selected"
    INELIGIBLE = "ineligible"
    SUPERSEDED = "superseded"
    CONFLICT_SUPPRESSED = "conflict_suppressed"


@dataclass(frozen=True, slots=True)
class IntentArbitrationDecision:
    intent_id: str
    disposition: IntentDisposition
    reason: str
    winning_intent_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntentArbitrationPolicy:
    """Declarative conflict policy independent of current intent instances."""

    exclusive_groups: tuple[frozenset[OperationalIntentType], ...] = ()
    suppresses: Mapping[OperationalIntentType, frozenset[OperationalIntentType]] = MappingProxyType({})

    def __post_init__(self) -> None:
        groups = tuple(frozenset(group) for group in self.exclusive_groups)
        if any(len(group) < 2 for group in groups):
            raise ValueError("exclusive groups must contain at least two intent types")
        normalized = {
            source: frozenset(targets)
            for source, targets in self.suppresses.items()
            if targets
        }
        object.__setattr__(self, "exclusive_groups", groups)
        object.__setattr__(self, "suppresses", MappingProxyType(normalized))

    def relationship(
        self,
        candidate: OperationalIntent,
        selected: OperationalIntent,
    ) -> tuple[str, bool] | None:
        """Return (reason, candidate_wins) for a conflict, or None if compatible."""

        candidate_suppresses = selected.intent_type in self.suppresses.get(
            candidate.intent_type, frozenset()
        )
        selected_suppresses = candidate.intent_type in self.suppresses.get(
            selected.intent_type, frozenset()
        )
        if candidate_suppresses and not selected_suppresses:
            return "candidate explicitly suppresses selected intent", True
        if selected_suppresses and not candidate_suppresses:
            return "selected intent explicitly suppresses candidate", False
        for group in self.exclusive_groups:
            if candidate.intent_type in group and selected.intent_type in group:
                return "mutually exclusive operational intents", False
        if candidate_suppresses and selected_suppresses:
            return "mutual suppression resolved by canonical ordering", False
        return None


DEFAULT_INTENT_ARBITRATION_POLICY = IntentArbitrationPolicy(
    exclusive_groups=(
        frozenset({OperationalIntentType.HEAT_POOL, OperationalIntentType.HEAT_SPA}),
        frozenset({OperationalIntentType.MAINTENANCE_MODE, OperationalIntentType.COMMISSIONING_MODE}),
    ),
    suppresses={
        OperationalIntentType.FREEZE_PROTECTION: frozenset(
            {
                OperationalIntentType.MINIMIZE_ENERGY,
                OperationalIntentType.QUIET_HOURS,
                OperationalIntentType.SCHEDULED_OPERATION,
            }
        ),
        OperationalIntentType.PROTECT_EQUIPMENT: frozenset(
            {
                OperationalIntentType.MINIMIZE_ENERGY,
                OperationalIntentType.SCHEDULED_OPERATION,
            }
        ),
        OperationalIntentType.MAINTENANCE_MODE: frozenset(
            {
                OperationalIntentType.MAINTAIN_CIRCULATION,
                OperationalIntentType.MAINTAIN_SANITATION,
                OperationalIntentType.MAINTAIN_CHEMISTRY,
                OperationalIntentType.HEAT_POOL,
                OperationalIntentType.HEAT_SPA,
                OperationalIntentType.MAXIMIZE_SOLAR,
                OperationalIntentType.MINIMIZE_ENERGY,
                OperationalIntentType.QUIET_HOURS,
                OperationalIntentType.SCHEDULED_OPERATION,
            }
        ),
    },
)


@dataclass(frozen=True, slots=True)
class IntentArbitrationResult:
    evaluated_at: datetime
    selected: tuple[OperationalIntent, ...]
    decisions: tuple[IntentArbitrationDecision, ...]

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        object.__setattr__(self, "evaluated_at", self.evaluated_at.astimezone(timezone.utc))

    @property
    def selected_intent_ids(self) -> tuple[str, ...]:
        return tuple(intent.intent_id for intent in self.selected)

    def decision_for(self, intent_id: str) -> IntentArbitrationDecision:
        matches = [decision for decision in self.decisions if decision.intent_id == intent_id]
        if len(matches) != 1:
            raise KeyError(intent_id)
        return matches[0]

    def explain(self) -> tuple[str, ...]:
        return tuple(
            f"{decision.intent_id}: {decision.disposition.value} - {decision.reason}"
            for decision in self.decisions
        )


class OperationalIntentArbitrator:
    """Resolve eligible intents into a deterministic compatible selected set."""

    def __init__(self, policy: IntentArbitrationPolicy = DEFAULT_INTENT_ARBITRATION_POLICY) -> None:
        self._policy = policy

    def arbitrate(
        self,
        intents: tuple[OperationalIntent, ...],
        *,
        evaluated_at: datetime,
    ) -> IntentArbitrationResult:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        now = evaluated_at.astimezone(timezone.utc)
        if len({intent.intent_id for intent in intents}) != len(intents):
            raise ValueError("duplicate operational intent identities are not allowed")

        ordered = canonical_intent_order(intents)
        by_id = {intent.intent_id: intent for intent in ordered}
        decisions: dict[str, IntentArbitrationDecision] = {}
        eligible: list[OperationalIntent] = []

        for intent in ordered:
            if intent.lifecycle not in {
                OperationalIntentLifecycle.REQUESTED,
                OperationalIntentLifecycle.ACTIVE,
            }:
                decisions[intent.intent_id] = IntentArbitrationDecision(
                    intent.intent_id,
                    IntentDisposition.INELIGIBLE,
                    f"lifecycle is {intent.lifecycle.value}",
                )
                continue
            if intent.requested_at > now:
                decisions[intent.intent_id] = IntentArbitrationDecision(
                    intent.intent_id,
                    IntentDisposition.INELIGIBLE,
                    "request time is in the future",
                )
                continue
            if intent.expires_at is not None and intent.expires_at <= now:
                decisions[intent.intent_id] = IntentArbitrationDecision(
                    intent.intent_id,
                    IntentDisposition.INELIGIBLE,
                    "intent has expired",
                )
                continue
            eligible.append(intent)

        superseded_ids = {
            intent.supersedes_intent_id
            for intent in eligible
            if intent.supersedes_intent_id in by_id
        }
        candidates: list[OperationalIntent] = []
        for intent in eligible:
            if intent.intent_id in superseded_ids:
                winner = next(
                    item for item in eligible if item.supersedes_intent_id == intent.intent_id
                )
                decisions[intent.intent_id] = IntentArbitrationDecision(
                    intent.intent_id,
                    IntentDisposition.SUPERSEDED,
                    "superseded by a newer eligible intent",
                    winner.intent_id,
                )
            else:
                candidates.append(intent)

        selected: list[OperationalIntent] = []
        for candidate in candidates:
            suppressed_by: tuple[OperationalIntent, str] | None = None
            evicted: list[tuple[OperationalIntent, str]] = []
            for current in selected:
                relationship = self._policy.relationship(candidate, current)
                if relationship is None:
                    continue
                reason, candidate_wins = relationship
                if candidate_wins:
                    evicted.append((current, reason))
                else:
                    suppressed_by = (current, reason)
                    break

            if suppressed_by is not None:
                winner, reason = suppressed_by
                decisions[candidate.intent_id] = IntentArbitrationDecision(
                    candidate.intent_id,
                    IntentDisposition.CONFLICT_SUPPRESSED,
                    reason,
                    winner.intent_id,
                )
                continue

            for loser, reason in evicted:
                selected.remove(loser)
                decisions[loser.intent_id] = IntentArbitrationDecision(
                    loser.intent_id,
                    IntentDisposition.CONFLICT_SUPPRESSED,
                    reason,
                    candidate.intent_id,
                )
            selected.append(candidate)
            decisions[candidate.intent_id] = IntentArbitrationDecision(
                candidate.intent_id,
                IntentDisposition.SELECTED,
                "eligible and compatible after policy arbitration",
            )

        selected = list(canonical_intent_order(tuple(selected)))

        return IntentArbitrationResult(
            evaluated_at=now,
            selected=tuple(selected),
            decisions=tuple(decisions[intent.intent_id] for intent in ordered),
        )

