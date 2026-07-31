from datetime import datetime, timezone

import pytest

from poolos.decision_intelligence import (
    AlternativeStatus,
    CheckStatus,
    DecisionAlternative,
    DecisionCheck,
    DecisionExplanation,
    DecisionOutcome,
)
from poolos.human_explanation import (
    HumanExplanationRenderer,
    HumanReadableExplanation,
)


def alternative(
    alternative_id: str,
    label: str,
    status: AlternativeStatus,
    rank: int,
    *,
    score: float | None = None,
    reasons: tuple[str, ...] = (),
) -> DecisionAlternative:
    return DecisionAlternative(
        alternative_id=alternative_id,
        label=label,
        status=status,
        rank=rank,
        score=score,
        reasons=reasons,
    )


def explanation(
    *,
    outcome: DecisionOutcome,
    selected_id: str | None,
    alternatives: tuple[DecisionAlternative, ...],
    checks: tuple[DecisionCheck, ...] = (),
    summary: str = "Pool heating decision completed",
    confidence: float = 0.87,
    next_change: str | None = None,
) -> DecisionExplanation:
    return DecisionExplanation(
        decision_id="decision-1",
        evaluated_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        goal="Prepare the pool efficiently",
        outcome=outcome,
        selected_alternative_id=selected_id,
        confidence=confidence,
        evidence=(),
        checks=checks,
        alternatives=alternatives,
        summary=summary,
        next_change=next_change,
    )


def test_selected_decision_renders_plain_language_details():
    value = explanation(
        outcome=DecisionOutcome.SELECTED,
        selected_id="hybrid",
        alternatives=(
            alternative(
                "hybrid",
                "solar plus heater",
                AlternativeStatus.SELECTED,
                1,
                score=0.89,
                reasons=("it reaches the target efficiently",),
            ),
            alternative(
                "heater",
                "heater only",
                AlternativeStatus.REJECTED,
                2,
                score=0.74,
                reasons=("it costs more to operate",),
            ),
        ),
        next_change="a material change in the weather forecast",
    )

    rendered = HumanExplanationRenderer().render(value)

    assert rendered.headline == "Pool heating decision completed."
    assert rendered.details == (
        "Selected solar plus heater (89% fit) because it reaches the target efficiently.",
        "Other options: heater only was not selected because it costs more to operate.",
        "What could change this: a material change in the weather forecast.",
        "Decision confidence is 87%.",
    )
    assert rendered.text == " ".join((rendered.headline, *rendered.details))


def test_blocked_decision_names_blockers_and_failed_checks():
    safety = DecisionCheck(
        check_id="safety",
        label="Power outage safety",
        status=CheckStatus.FAILED,
        reason="grid power is unavailable",
        blocking=True,
    )
    ownership = DecisionCheck(
        check_id="ownership",
        label="Equipment ownership",
        status=CheckStatus.UNKNOWN,
        reason="current ownership could not be confirmed",
    )
    value = explanation(
        outcome=DecisionOutcome.BLOCKED,
        selected_id=None,
        alternatives=(
            alternative(
                "heat",
                "start heater",
                AlternativeStatus.INFEASIBLE,
                1,
                reasons=("power-outage safety prevents heating",),
            ),
        ),
        checks=(safety, ownership),
        summary="Heating is unavailable",
    )

    rendered = HumanExplanationRenderer().render(value)

    assert rendered.details[0] == "Action is blocked by Power outage safety."
    assert rendered.details[1] == (
        "Important checks: Power outage safety: grid power is unavailable; "
        "Equipment ownership: current ownership could not be confirmed."
    )
    assert "start heater was not available" in rendered.details[2]


def test_deferred_and_no_action_have_distinct_messages():
    deferred = explanation(
        outcome=DecisionOutcome.DEFERRED,
        selected_id=None,
        alternatives=(),
    )
    no_action = explanation(
        outcome=DecisionOutcome.NO_ACTION,
        selected_id=None,
        alternatives=(),
    )

    renderer = HumanExplanationRenderer(include_confidence=False)

    assert renderer.render(deferred).details == (
        "Action is being deferred until conditions change.",
    )
    assert renderer.render(no_action).details == ("No action is needed right now.",)


def test_renderer_limits_rejected_alternatives_and_can_hide_them():
    value = explanation(
        outcome=DecisionOutcome.SELECTED,
        selected_id="one",
        alternatives=(
            alternative("one", "first", AlternativeStatus.SELECTED, 1),
            alternative("two", "second", AlternativeStatus.REJECTED, 2),
            alternative("three", "third", AlternativeStatus.REJECTED, 3),
            alternative("four", "fourth", AlternativeStatus.REJECTED, 4),
        ),
    )

    limited = HumanExplanationRenderer(max_alternatives=2).render(value)
    hidden = HumanExplanationRenderer(max_alternatives=0).render(value)

    assert "second" in limited.details[1]
    assert "third" in limited.details[1]
    assert "fourth" not in limited.details[1]
    assert all(not detail.startswith("Other options:") for detail in hidden.details)


def test_renderer_uses_stable_grammar_for_multiple_blockers():
    checks = tuple(
        DecisionCheck(
            check_id=str(index),
            label=label,
            status=CheckStatus.FAILED,
            reason="failed",
            blocking=True,
        )
        for index, label in enumerate(("Safety", "Ownership", "Policy"), start=1)
    )
    value = explanation(
        outcome=DecisionOutcome.BLOCKED,
        selected_id=None,
        alternatives=(),
        checks=checks,
    )

    rendered = HumanExplanationRenderer(include_confidence=False).render(value)

    assert rendered.details[0] == "Action is blocked by Safety, Ownership, and Policy."


def test_human_models_validate_configuration_and_content():
    with pytest.raises(ValueError, match="max_alternatives"):
        HumanExplanationRenderer(max_alternatives=-1)
    with pytest.raises(ValueError, match="headline"):
        HumanReadableExplanation(" ", ())
    with pytest.raises(ValueError, match="details"):
        HumanReadableExplanation("Valid", ("",))
