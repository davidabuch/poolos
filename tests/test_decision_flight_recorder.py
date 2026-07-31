from datetime import datetime, timezone

from poolos.decision_flight_recorder import InMemoryDecisionFlightRecorder
from poolos.decision_intelligence import DecisionExplanation, DecisionOutcome
from poolos.human_explanation import HumanReadableExplanation
from poolos.technical_explanation import TechnicalExplanation

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


def explanation(decision_id: str) -> DecisionExplanation:
    return DecisionExplanation(
        decision_id=decision_id,
        evaluated_at=NOW,
        goal="prepare spa",
        outcome=DecisionOutcome.NO_ACTION,
        selected_alternative_id=None,
        confidence=0.0,
        evidence=(),
        checks=(),
        alternatives=(),
        summary="No action required",
    )


def test_recorder_appends_stable_sequences_and_histories():
    recorder = InMemoryDecisionFlightRecorder()
    human = HumanReadableExplanation("No action required.", ("No action is needed.",))
    technical = TechnicalExplanation((("decision", ("outcome=no_action",)),))

    first = recorder.record(
        plan_id="plan-1",
        objective_id="goal-1",
        decision=explanation("decision-1"),
        human=human,
        technical=technical,
        recorded_at=NOW,
    )
    second = recorder.record(
        plan_id="plan-2",
        objective_id="goal-1",
        decision=explanation("decision-2"),
        human=human,
        technical=technical,
        recorded_at=NOW,
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert recorder.records == (first, second)
    assert recorder.latest == second
    assert recorder.history_for_plan("plan-1") == (first,)
    assert recorder.history_for_objective("goal-1") == (first, second)


def test_json_export_is_stable_and_compact():
    recorder = InMemoryDecisionFlightRecorder()
    recorder.record(
        plan_id="plan-1",
        objective_id="goal-1",
        decision=explanation("decision-1"),
        human=HumanReadableExplanation("Headline.", ("Detail.",)),
        technical=TechnicalExplanation((("decision", ("outcome=no_action",)),)),
        recorded_at=NOW,
    )

    payload = recorder.export_json()
    assert payload.startswith('[{"confidence":0.0,"decision_id":"decision-1"')
    assert '"technical_text":"[decision]\\noutcome=no_action"' in payload
    assert ": " not in payload
    assert ", " not in payload
