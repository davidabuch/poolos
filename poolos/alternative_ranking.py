"""Deterministic, policy-neutral ranking for PoolOS decision alternatives."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional

from .decision_intelligence import AlternativeStatus, DecisionAlternative


@dataclass(frozen=True, slots=True)
class RankingCriterion:
    """One normalized scoring dimension and its relative importance."""

    criterion_id: str
    label: str
    weight: float

    def __post_init__(self) -> None:
        if not self.criterion_id.strip():
            raise ValueError("criterion_id must not be empty")
        if not self.label.strip():
            raise ValueError("criterion label must not be empty")
        if self.weight <= 0:
            raise ValueError("criterion weight must be positive")


@dataclass(frozen=True, slots=True)
class AlternativeCandidate:
    """One candidate with normalized criterion scores supplied by domain logic."""

    alternative_id: str
    label: str
    scores: Mapping[str, float]
    feasible: bool = True
    priority: int = 100
    reasons: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.alternative_id.strip():
            raise ValueError("alternative_id must not be empty")
        if not self.label.strip():
            raise ValueError("alternative label must not be empty")
        if self.priority < 0:
            raise ValueError("alternative priority must not be negative")
        if any(not key.strip() for key in self.scores):
            raise ValueError("score criterion IDs must not be empty")
        if any(score < 0 or score > 1 for score in self.scores.values()):
            raise ValueError("criterion scores must be between 0 and 1")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("alternative reasons must not be empty")
        object.__setattr__(self, "scores", MappingProxyType(dict(self.scores)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class CriterionContribution:
    """Traceable weighted contribution from one ranking criterion."""

    criterion_id: str
    raw_score: float
    normalized_weight: float
    weighted_score: float


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """One candidate after deterministic scoring and ordering."""

    candidate: AlternativeCandidate
    rank: int
    score: float
    contributions: tuple[CriterionContribution, ...]
    selected: bool

    @property
    def status(self) -> AlternativeStatus:
        """Return the decision-intelligence disposition for this result."""

        if not self.candidate.feasible:
            return AlternativeStatus.INFEASIBLE
        if self.selected:
            return AlternativeStatus.SELECTED
        return AlternativeStatus.REJECTED

    def to_decision_alternative(self) -> DecisionAlternative:
        """Convert the ranked result to the canonical explanation model."""

        reasons = self.candidate.reasons
        if not reasons:
            reasons = (
                (
                    "Candidate was selected by deterministic weighted ranking."
                    if self.selected
                    else "Candidate was not selected by deterministic weighted ranking."
                ),
            )
        return DecisionAlternative(
            alternative_id=self.candidate.alternative_id,
            label=self.candidate.label,
            status=self.status,
            rank=self.rank,
            score=self.score,
            reasons=reasons,
            metadata=self.candidate.metadata,
        )


@dataclass(frozen=True, slots=True)
class RankingResult:
    """Complete deterministic ranking of all supplied alternatives."""

    ranked: tuple[RankedCandidate, ...]
    selected_alternative_id: Optional[str]

    @property
    def selected(self) -> Optional[RankedCandidate]:
        """Return the selected feasible candidate, if one exists."""

        if self.selected_alternative_id is None:
            return None
        return next(
            item
            for item in self.ranked
            if item.candidate.alternative_id == self.selected_alternative_id
        )

    @property
    def decision_alternatives(self) -> tuple[DecisionAlternative, ...]:
        """Return canonical explanation alternatives in rank order."""

        return tuple(item.to_decision_alternative() for item in self.ranked)


@dataclass(frozen=True, slots=True)
class AlternativeRankingEngine:
    """Rank normalized alternatives without embedding domain-specific policy."""

    criteria: tuple[RankingCriterion, ...]

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("at least one ranking criterion is required")
        criterion_ids = [criterion.criterion_id for criterion in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique")

    @property
    def normalized_weights(self) -> Mapping[str, float]:
        """Return criterion weights normalized to sum to one."""

        total = sum(criterion.weight for criterion in self.criteria)
        return MappingProxyType(
            {
                criterion.criterion_id: criterion.weight / total
                for criterion in self.criteria
            }
        )

    def _score(
        self,
        candidate: AlternativeCandidate,
        weights: Mapping[str, float],
    ) -> tuple[float, tuple[CriterionContribution, ...]]:
        expected = set(weights)
        supplied = set(candidate.scores)
        missing = expected - supplied
        unknown = supplied - expected
        if missing:
            raise ValueError(
                f"candidate {candidate.alternative_id!r} is missing scores: {sorted(missing)}"
            )
        if unknown:
            raise ValueError(
                f"candidate {candidate.alternative_id!r} has unknown scores: {sorted(unknown)}"
            )

        contributions = tuple(
            CriterionContribution(
                criterion_id=criterion.criterion_id,
                raw_score=candidate.scores[criterion.criterion_id],
                normalized_weight=weights[criterion.criterion_id],
                weighted_score=(
                    candidate.scores[criterion.criterion_id]
                    * weights[criterion.criterion_id]
                ),
            )
            for criterion in self.criteria
        )
        score = sum(item.weighted_score for item in contributions)
        return score, contributions

    def rank(self, candidates: tuple[AlternativeCandidate, ...]) -> RankingResult:
        """Score and rank every candidate using stable deterministic tie-breakers."""

        candidate_ids = [candidate.alternative_id for candidate in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("alternative candidate IDs must be unique")
        if not candidates:
            return RankingResult((), None)

        weights = self.normalized_weights
        scored = tuple(
            (candidate, *self._score(candidate, weights)) for candidate in candidates
        )
        ordered = sorted(
            scored,
            key=lambda item: (
                not item[0].feasible,
                -item[1],
                item[0].priority,
                item[0].alternative_id,
            ),
        )
        selected_id = next(
            (
                candidate.alternative_id
                for candidate, _, _ in ordered
                if candidate.feasible
            ),
            None,
        )
        ranked = tuple(
            RankedCandidate(
                candidate=candidate,
                rank=index,
                score=score,
                contributions=contributions,
                selected=candidate.alternative_id == selected_id,
            )
            for index, (candidate, score, contributions) in enumerate(ordered, start=1)
        )
        return RankingResult(ranked, selected_id)
