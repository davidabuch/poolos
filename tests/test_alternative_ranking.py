import pytest

from poolos.alternative_ranking import (
    AlternativeCandidate,
    AlternativeRankingEngine,
    RankingCriterion,
)
from poolos.decision_intelligence import AlternativeStatus


def engine() -> AlternativeRankingEngine:
    return AlternativeRankingEngine(
        criteria=(
            RankingCriterion("goal", "Goal satisfaction", 5),
            RankingCriterion("cost", "Cost efficiency", 3),
            RankingCriterion("risk", "Operational safety", 2),
        )
    )


def candidate(
    alternative_id: str,
    *,
    goal: float,
    cost: float,
    risk: float,
    feasible: bool = True,
    priority: int = 100,
) -> AlternativeCandidate:
    return AlternativeCandidate(
        alternative_id=alternative_id,
        label=alternative_id.replace("_", " ").title(),
        scores={"goal": goal, "cost": cost, "risk": risk},
        feasible=feasible,
        priority=priority,
        reasons=(f"Evaluated {alternative_id}.",),
        metadata={"source": "test"},
    )


def test_weighted_ranking_selects_highest_scoring_feasible_candidate():
    result = engine().rank(
        (
            candidate("solar_only", goal=0.7, cost=1.0, risk=0.9),
            candidate("hybrid_heat", goal=1.0, cost=0.7, risk=0.9),
            candidate("heater_only", goal=1.0, cost=0.4, risk=0.8),
        )
    )

    assert result.selected_alternative_id == "hybrid_heat"
    assert result.selected is not None
    assert result.selected.candidate.alternative_id == "hybrid_heat"
    assert [item.candidate.alternative_id for item in result.ranked] == [
        "hybrid_heat",
        "solar_only",
        "heater_only",
    ]
    assert result.ranked[0].score == pytest.approx(0.89)
    assert sum(
        contribution.weighted_score
        for contribution in result.ranked[0].contributions
    ) == pytest.approx(result.ranked[0].score)


def test_infeasible_candidate_cannot_win_even_with_higher_score():
    result = engine().rank(
        (
            candidate("unsafe_fast", goal=1.0, cost=1.0, risk=1.0, feasible=False),
            candidate("safe_slow", goal=0.6, cost=0.6, risk=0.6),
        )
    )

    assert result.selected_alternative_id == "safe_slow"
    assert [item.candidate.alternative_id for item in result.ranked] == [
        "safe_slow",
        "unsafe_fast",
    ]
    assert result.ranked[1].status is AlternativeStatus.INFEASIBLE


def test_ties_use_priority_then_stable_alternative_id():
    result = engine().rank(
        (
            candidate("zeta", goal=0.8, cost=0.8, risk=0.8, priority=20),
            candidate("beta", goal=0.8, cost=0.8, risk=0.8, priority=10),
            candidate("alpha", goal=0.8, cost=0.8, risk=0.8, priority=10),
        )
    )

    assert [item.candidate.alternative_id for item in result.ranked] == [
        "alpha",
        "beta",
        "zeta",
    ]
    assert result.selected_alternative_id == "alpha"


def test_no_feasible_candidate_produces_no_selection():
    result = engine().rank(
        (
            candidate("first", goal=0.8, cost=0.8, risk=0.8, feasible=False),
            candidate("second", goal=0.5, cost=0.5, risk=0.5, feasible=False),
        )
    )

    assert result.selected is None
    assert result.selected_alternative_id is None
    assert all(item.status is AlternativeStatus.INFEASIBLE for item in result.ranked)


def test_result_converts_to_canonical_decision_alternatives():
    result = engine().rank(
        (
            candidate("selected", goal=0.9, cost=0.9, risk=0.9),
            candidate("rejected", goal=0.6, cost=0.6, risk=0.6),
            candidate("blocked", goal=1.0, cost=1.0, risk=1.0, feasible=False),
        )
    )

    converted = result.decision_alternatives
    assert [item.status for item in converted] == [
        AlternativeStatus.SELECTED,
        AlternativeStatus.REJECTED,
        AlternativeStatus.INFEASIBLE,
    ]
    assert [item.rank for item in converted] == [1, 2, 3]
    assert converted[0].metadata["source"] == "test"


def test_weights_are_normalized_and_read_only():
    weights = engine().normalized_weights
    assert weights == {"goal": 0.5, "cost": 0.3, "risk": 0.2}
    with pytest.raises(TypeError):
        weights["goal"] = 1.0  # type: ignore[index]


def test_candidates_require_exactly_the_configured_criteria():
    with pytest.raises(ValueError, match="missing scores"):
        engine().rank(
            (
                AlternativeCandidate(
                    alternative_id="missing",
                    label="Missing",
                    scores={"goal": 1.0, "cost": 1.0},
                ),
            )
        )
    with pytest.raises(ValueError, match="unknown scores"):
        engine().rank(
            (
                AlternativeCandidate(
                    alternative_id="unknown",
                    label="Unknown",
                    scores={"goal": 1.0, "cost": 1.0, "risk": 1.0, "other": 1.0},
                ),
            )
        )


def test_invalid_criteria_candidates_and_duplicate_ids_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        AlternativeRankingEngine(())
    with pytest.raises(ValueError, match="criterion IDs must be unique"):
        AlternativeRankingEngine(
            (
                RankingCriterion("cost", "Cost", 1),
                RankingCriterion("cost", "Cost again", 2),
            )
        )
    with pytest.raises(ValueError, match="weight"):
        RankingCriterion("cost", "Cost", 0)
    with pytest.raises(ValueError, match="between 0 and 1"):
        AlternativeCandidate("bad", "Bad", {"goal": 1.1})
    with pytest.raises(ValueError, match="candidate IDs must be unique"):
        value = candidate("same", goal=1.0, cost=1.0, risk=1.0)
        engine().rank((value, value))


def test_empty_candidate_collection_returns_empty_ranking():
    result = engine().rank(())
    assert result.ranked == ()
    assert result.selected is None
    assert result.decision_alternatives == ()
