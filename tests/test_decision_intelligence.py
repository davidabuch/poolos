from datetime import datetime, timezone

import pytest

from poolos.decision_intelligence import (
    AlternativeStatus,
    CheckStatus,
    DecisionAlternative,
    DecisionCheck,
    DecisionEvidence,
    DecisionExplanation,
    DecisionOutcome,
    EvidenceKind,
)

NOW = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)


def evidence(key: str = "pool_temperature") -> DecisionEvidence:
    return DecisionEvidence(
        key=key,
        value="84 F",
        kind=EvidenceKind.OBSERVATION,
        source="sensor.pool_temperature",
        observed_at=NOW,
        metadata={"quality": "good"},
    )


def check(*, blocking: bool = False) -> DecisionCheck:
    return DecisionCheck(
        check_id="temperature_valid",
        label="Temperature is valid",
        status=CheckStatus.FAILED if blocking else CheckStatus.PASSED,
        reason="Temperature validation completed.",
        blocking=blocking,
        evidence_keys=("pool_temperature",),
    )


def alternative(
    alternative_id: str,
    status: AlternativeStatus,
    rank: int,
) -> DecisionAlternative:
    return DecisionAlternative(
        alternative_id=alternative_id,
        label=alternative_id.replace("_", " ").title(),
        status=status,
        rank=rank,
        score=0.9 if status is AlternativeStatus.SELECTED else 0.5,
        reasons=("Deterministic candidate evaluation completed.",),
    )


def explanation(**overrides: object) -> DecisionExplanation:
    values: dict[str, object] = {
        "decision_id": "decision-001",
        "evaluated_at": NOW,
        "goal": "Heat pool to 90 F",
        "outcome": DecisionOutcome.SELECTED,
        "selected_alternative_id": "hybrid_heat",
        "confidence": 0.96,
        "evidence": (evidence(),),
        "checks": (check(),),
        "alternatives": (
            alternative("solar_only", AlternativeStatus.REJECTED, 2),
            alternative("hybrid_heat", AlternativeStatus.SELECTED, 1),
        ),
        "summary": "Hybrid heating was selected.",
        "next_change": "A lower target temperature would permit solar-only heating.",
    }
    values.update(overrides)
    return DecisionExplanation(**values)  # type: ignore[arg-type]


def test_models_are_immutable_and_metadata_is_read_only():
    item = evidence()
    with pytest.raises(TypeError):
        item.metadata["quality"] = "bad"  # type: ignore[index]
    with pytest.raises(Exception):
        item.value = "85 F"  # type: ignore[misc]


def test_selected_explanation_resolves_selected_and_rejected_alternatives():
    value = explanation()
    assert value.selected_alternative is not None
    assert value.selected_alternative.alternative_id == "hybrid_heat"
    assert [item.alternative_id for item in value.alternatives] == [
        "hybrid_heat",
        "solar_only",
    ]
    assert [item.alternative_id for item in value.rejected_alternatives] == [
        "solar_only"
    ]


def test_selected_outcome_requires_matching_selected_alternative():
    with pytest.raises(ValueError, match="selected alternative must exist"):
        explanation(selected_alternative_id="missing")
    with pytest.raises(ValueError, match="exactly one alternative"):
        explanation(
            alternatives=(
                alternative("hybrid_heat", AlternativeStatus.FEASIBLE, 1),
            )
        )


def test_non_selected_outcome_cannot_select_an_alternative():
    with pytest.raises(ValueError, match="cannot identify"):
        explanation(outcome=DecisionOutcome.NO_ACTION)


def test_blocked_outcome_requires_a_blocking_check():
    with pytest.raises(ValueError, match="requires at least one blocking check"):
        explanation(
            outcome=DecisionOutcome.BLOCKED,
            selected_alternative_id=None,
            alternatives=(
                alternative("wait", AlternativeStatus.REJECTED, 1),
            ),
        )


def test_blocked_explanation_exposes_blocking_checks():
    value = explanation(
        outcome=DecisionOutcome.BLOCKED,
        selected_alternative_id=None,
        checks=(check(blocking=True),),
        alternatives=(alternative("wait", AlternativeStatus.REJECTED, 1),),
    )
    assert value.selected_alternative is None
    assert value.blocking_checks == value.checks


def test_check_cannot_reference_unknown_evidence():
    invalid = DecisionCheck(
        check_id="ownership",
        label="Ownership available",
        status=CheckStatus.PASSED,
        reason="Ownership is available.",
        evidence_keys=("owner",),
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        explanation(checks=(invalid,))


def test_duplicate_graph_identifiers_are_rejected():
    with pytest.raises(ValueError, match="evidence keys must be unique"):
        explanation(evidence=(evidence(), evidence()))
    with pytest.raises(ValueError, match="check IDs must be unique"):
        explanation(checks=(check(), check()))
    with pytest.raises(ValueError, match="alternative IDs must be unique"):
        explanation(
            alternatives=(
                alternative("hybrid_heat", AlternativeStatus.SELECTED, 1),
                alternative("hybrid_heat", AlternativeStatus.REJECTED, 2),
            )
        )


def test_alternative_rank_and_score_are_validated():
    with pytest.raises(ValueError, match="rank"):
        alternative("wait", AlternativeStatus.FEASIBLE, 0)
    with pytest.raises(ValueError, match="score"):
        DecisionAlternative(
            alternative_id="wait",
            label="Wait",
            status=AlternativeStatus.FEASIBLE,
            rank=1,
            score=1.1,
        )


def test_timezone_aware_timestamps_are_required():
    with pytest.raises(ValueError, match="timezone-aware"):
        explanation(evaluated_at=datetime(2026, 7, 30, 16, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        DecisionEvidence(
            key="temperature",
            value="84 F",
            kind=EvidenceKind.OBSERVATION,
            source="test",
            observed_at=datetime(2026, 7, 30, 16, 0),
        )
