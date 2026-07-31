from datetime import datetime, timezone

import pytest

from poolos.evaluation_context import EvaluationTrigger
from poolos.evaluation_triggers import (
    EvaluationTriggerCoalescer,
    EvaluationTriggerRequest,
    TriggerUrgency,
)


NOW = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def request(trigger, urgency=TriggerUrgency.NORMAL, source="test", reason="changed"):
    return EvaluationTriggerRequest(
        trigger=trigger,
        requested_at=NOW,
        urgency=urgency,
        source=source,
        reason=reason,
    )


def test_coalescer_prefers_highest_urgency():
    result = EvaluationTriggerCoalescer().coalesce(
        (
            request(EvaluationTrigger.POLICY_CHANGED),
            request(EvaluationTrigger.SCHEDULED, TriggerUrgency.IMMEDIATE),
        )
    )
    assert result.trigger is EvaluationTrigger.SCHEDULED
    assert result.urgency is TriggerUrgency.IMMEDIATE


def test_coalescer_uses_stable_trigger_precedence_for_ties():
    result = EvaluationTriggerCoalescer().coalesce(
        (
            request(EvaluationTrigger.FORECAST_CHANGED),
            request(EvaluationTrigger.POLICY_CHANGED),
        )
    )
    assert result.trigger is EvaluationTrigger.POLICY_CHANGED


def test_coalescer_is_deterministic_and_retains_all_reasons():
    low = request(EvaluationTrigger.SCHEDULED, source="z", reason="timer")
    high = request(EvaluationTrigger.MANUAL, source="a", reason="operator")
    first = EvaluationTriggerCoalescer().coalesce((low, high))
    second = EvaluationTriggerCoalescer().coalesce((high, low))
    assert first == second
    assert first.reasons == ("operator", "timer")


def test_trigger_request_requires_timezone_and_text():
    with pytest.raises(ValueError):
        EvaluationTriggerRequest(
            trigger=EvaluationTrigger.MANUAL,
            requested_at=datetime(2026, 7, 31, 15, 0),
        )
    with pytest.raises(ValueError):
        EvaluationTriggerRequest(
            trigger=EvaluationTrigger.MANUAL,
            requested_at=NOW,
            source=" ",
        )


def test_coalescer_rejects_empty_batch():
    with pytest.raises(ValueError):
        EvaluationTriggerCoalescer().coalesce(())
