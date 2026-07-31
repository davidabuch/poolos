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
from poolos.technical_explanation import TechnicalExplanation, TechnicalExplanationRenderer


def make_explanation() -> DecisionExplanation:
    return DecisionExplanation(
        decision_id="decision-42",
        evaluated_at=datetime(2026, 7, 30, 19, 45, tzinfo=timezone.utc),
        goal="Prepare pool efficiently",
        outcome=DecisionOutcome.SELECTED,
        selected_alternative_id="hybrid",
        confidence=0.875,
        evidence=(
            DecisionEvidence(
                key="water_temp",
                value="84.0",
                kind=EvidenceKind.OBSERVATION,
                source="sensor.pool_temperature",
                observed_at=datetime(2026, 7, 30, 19, 44, tzinfo=timezone.utc),
                metadata={"unit": "F", "quality": "good"},
            ),
        ),
        checks=(
            DecisionCheck(
                check_id="safety",
                label="Safety gate",
                status=CheckStatus.PASSED,
                reason="all safety conditions passed",
                evidence_keys=("water_temp",),
            ),
        ),
        alternatives=(
            DecisionAlternative(
                alternative_id="heater",
                label="Heater only",
                status=AlternativeStatus.REJECTED,
                rank=2,
                score=0.72,
                reasons=("higher operating cost",),
            ),
            DecisionAlternative(
                alternative_id="hybrid",
                label="Solar plus heater",
                status=AlternativeStatus.SELECTED,
                rank=1,
                score=0.91,
                reasons=("best weighted fit", "meets target time"),
                metadata={"profile": "balanced"},
            ),
        ),
        summary="Hybrid heating selected",
        next_change="forecast materially changes",
        metadata={"planner": "goal_facade", "version": "1"},
    )


def test_renderer_exposes_complete_decision_graph_in_stable_sections():
    rendered = TechnicalExplanationRenderer().render(make_explanation())

    assert tuple(name for name, _ in rendered.sections) == (
        "decision",
        "evidence",
        "checks",
        "alternatives",
        "metadata",
    )
    assert rendered.section("decision")[0] == "decision_id=decision-42"
    assert "outcome=selected" in rendered.section("decision")
    assert "kind=observation" in rendered.section("evidence")[0]
    assert "blocking=false" in rendered.section("checks")[0]
    assert rendered.section("alternatives")[0].startswith("rank=1 id=hybrid")
    assert rendered.section("metadata") == ("planner=goal_facade", "version=1")


def test_text_is_machine_comparable_and_display_ready():
    renderer = TechnicalExplanationRenderer()

    first = renderer.render(make_explanation()).text
    second = renderer.render(make_explanation()).text

    assert first == second
    assert first.startswith("[decision]\ndecision_id=decision-42")
    assert "\n\n[evidence]\n" in first
    assert "score=0.910000" in first


def test_metadata_is_sorted_at_every_level():
    rendered = TechnicalExplanationRenderer().render(make_explanation())

    evidence_line = rendered.section("evidence")[0]
    assert evidence_line.index("quality='good'") < evidence_line.index("unit='F'")
    assert rendered.section("metadata") == ("planner=goal_facade", "version=1")


def test_empty_sections_are_explicit_by_default():
    value = DecisionExplanation(
        decision_id="no-action",
        evaluated_at=datetime(2026, 7, 30, 19, 45, tzinfo=timezone.utc),
        goal="Maintain current state",
        outcome=DecisionOutcome.NO_ACTION,
        selected_alternative_id=None,
        confidence=1.0,
        evidence=(),
        checks=(),
        alternatives=(),
        summary="No action needed",
    )

    rendered = TechnicalExplanationRenderer().render(value)

    assert rendered.section("evidence") == ("none",)
    assert rendered.section("checks") == ("none",)
    assert rendered.section("alternatives") == ("none",)
    assert rendered.section("metadata") == ("none",)


def test_empty_sections_can_be_omitted():
    value = DecisionExplanation(
        decision_id="no-action",
        evaluated_at=datetime(2026, 7, 30, 19, 45, tzinfo=timezone.utc),
        goal="Maintain current state",
        outcome=DecisionOutcome.NO_ACTION,
        selected_alternative_id=None,
        confidence=1.0,
        evidence=(),
        checks=(),
        alternatives=(),
        summary="No action needed",
    )

    rendered = TechnicalExplanationRenderer(include_empty_sections=False).render(value)

    assert tuple(name for name, _ in rendered.sections) == ("decision",)


def test_technical_explanation_validates_sections_and_lines():
    with pytest.raises(ValueError, match="section names"):
        TechnicalExplanation((("", ("line",)),))
    with pytest.raises(ValueError, match="unique"):
        TechnicalExplanation((("same", ("one",)), ("same", ("two",))))
    with pytest.raises(ValueError, match="lines"):
        TechnicalExplanation((("valid", ("",)),))


def test_unknown_section_returns_empty_tuple():
    rendered = TechnicalExplanationRenderer().render(make_explanation())

    assert rendered.section("missing") == ()
