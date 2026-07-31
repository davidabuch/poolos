"""Immutable explanation models for traceable PoolOS decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional


class DecisionOutcome(str, Enum):
    """Final disposition of a decision evaluation."""

    SELECTED = "selected"
    NO_ACTION = "no_action"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class EvidenceKind(str, Enum):
    """Kinds of facts considered by a decision."""

    OBSERVATION = "observation"
    FORECAST = "forecast"
    GOAL = "goal"
    POLICY = "policy"
    OWNERSHIP = "ownership"
    SAFETY = "safety"
    COST = "cost"
    SYSTEM = "system"


class CheckStatus(str, Enum):
    """Result of evaluating one constraint or rule."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class AlternativeStatus(str, Enum):
    """Disposition of a candidate alternative."""

    SELECTED = "selected"
    REJECTED = "rejected"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """One immutable fact used during decision evaluation."""

    key: str
    value: str
    kind: EvidenceKind
    source: str
    observed_at: Optional[datetime] = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("evidence key must not be empty")
        if not self.source.strip():
            raise ValueError("evidence source must not be empty")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("evidence observed_at must be timezone-aware")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DecisionCheck:
    """One rule, constraint, safety, or ownership check."""

    check_id: str
    label: str
    status: CheckStatus
    reason: str
    blocking: bool = False
    evidence_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("check_id must not be empty")
        if not self.label.strip():
            raise ValueError("check label must not be empty")
        if not self.reason.strip():
            raise ValueError("check reason must not be empty")
        if self.blocking and self.status is CheckStatus.PASSED:
            raise ValueError("a passed check cannot be blocking")


@dataclass(frozen=True, slots=True)
class DecisionAlternative:
    """One candidate action considered by the decision engine."""

    alternative_id: str
    label: str
    status: AlternativeStatus
    rank: int
    score: Optional[float] = None
    reasons: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.alternative_id.strip():
            raise ValueError("alternative_id must not be empty")
        if not self.label.strip():
            raise ValueError("alternative label must not be empty")
        if self.rank < 1:
            raise ValueError("alternative rank must be at least 1")
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("alternative score must be between 0 and 1")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("alternative reasons must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    """Complete immutable explanation graph for one PoolOS decision."""

    decision_id: str
    evaluated_at: datetime
    goal: str
    outcome: DecisionOutcome
    selected_alternative_id: Optional[str]
    confidence: float
    evidence: tuple[DecisionEvidence, ...]
    checks: tuple[DecisionCheck, ...]
    alternatives: tuple[DecisionAlternative, ...]
    summary: str
    next_change: Optional[str] = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            raise ValueError("decision_id must not be empty")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not self.goal.strip():
            raise ValueError("goal must not be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not self.summary.strip():
            raise ValueError("summary must not be empty")

        evidence_keys = [item.key for item in self.evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("evidence keys must be unique")

        check_ids = [item.check_id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("check IDs must be unique")

        alternative_ids = [item.alternative_id for item in self.alternatives]
        if len(alternative_ids) != len(set(alternative_ids)):
            raise ValueError("alternative IDs must be unique")
        ranks = [item.rank for item in self.alternatives]
        if len(ranks) != len(set(ranks)):
            raise ValueError("alternative ranks must be unique")

        known_evidence = set(evidence_keys)
        for check in self.checks:
            unknown = set(check.evidence_keys) - known_evidence
            if unknown:
                raise ValueError(f"check references unknown evidence: {sorted(unknown)}")

        selected = [
            item for item in self.alternatives if item.status is AlternativeStatus.SELECTED
        ]
        if self.outcome is DecisionOutcome.SELECTED:
            if self.selected_alternative_id is None:
                raise ValueError("selected outcome requires selected_alternative_id")
            if self.selected_alternative_id not in alternative_ids:
                raise ValueError("selected alternative must exist")
            if len(selected) != 1 or selected[0].alternative_id != self.selected_alternative_id:
                raise ValueError("exactly one alternative must be marked selected")
        elif self.selected_alternative_id is not None:
            raise ValueError("non-selected outcome cannot identify a selected alternative")
        elif selected:
            raise ValueError("non-selected outcome cannot contain a selected alternative")

        if self.outcome is DecisionOutcome.BLOCKED and not any(
            check.blocking for check in self.checks
        ):
            raise ValueError("blocked outcome requires at least one blocking check")

        object.__setattr__(
            self,
            "alternatives",
            tuple(sorted(self.alternatives, key=lambda item: item.rank)),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def selected_alternative(self) -> Optional[DecisionAlternative]:
        """Return the selected alternative when the outcome selected one."""

        if self.selected_alternative_id is None:
            return None
        return next(
            item
            for item in self.alternatives
            if item.alternative_id == self.selected_alternative_id
        )

    @property
    def blocking_checks(self) -> tuple[DecisionCheck, ...]:
        """Return checks that actively prevented execution."""

        return tuple(check for check in self.checks if check.blocking)

    @property
    def rejected_alternatives(self) -> tuple[DecisionAlternative, ...]:
        """Return alternatives rejected or found infeasible."""

        rejected = {AlternativeStatus.REJECTED, AlternativeStatus.INFEASIBLE}
        return tuple(item for item in self.alternatives if item.status in rejected)
