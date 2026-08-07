from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.behavioral_inference import BehavioralInferenceEngine, InferredOperatingState
from poolos.observations import RecordedObservationEvent


def event(event_id: str, at: datetime, **values: object) -> RecordedObservationEvent:
    observations = tuple(
        {
            "observation_id": key,
            "value": value,
            "confidence": 1.0,
            "quality": "good",
            "source_kind": "live",
            "source_id": f"sensor.{key.replace('.', '_')}",
        }
        for key, value in sorted(values.items())
    )
    return RecordedObservationEvent(event_id, at, "transition", tuple(sorted(values)), observations, {"healthy": True})


def test_empty_evidence_is_unknown_and_nonassertive() -> None:
    report = BehavioralInferenceEngine().infer(())
    assert report.current_state is InferredOperatingState.UNKNOWN
    assert report.current_state_confidence == 0.0
    assert report.events == ()
    assert report.solar.confidence == 0.0


def test_current_state_precedence_is_spa_then_solar_then_heating_then_filtering() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    engine = BehavioralInferenceEngine()
    assert engine.infer((event("a", now, **{"pump.rpm": 2200, "pool.active": True}),)).current_state is InferredOperatingState.FILTERING
    assert engine.infer((event("a", now, **{"pump.rpm": 2200, "pool.active": True, "heater.active": True}),)).current_state is InferredOperatingState.HEATING
    assert engine.infer((event("a", now, **{"pump.rpm": 2200, "pool.active": True, "solar.active": True, "heater.active": True}),)).current_state is InferredOperatingState.SOLAR_ASSIST
    assert engine.infer((event("a", now, **{"pump.rpm": 2200, "spa.active": True, "solar.active": True}),)).current_state is InferredOperatingState.SPA



def test_running_baseline_does_not_invent_start_or_activation_events() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    report = BehavioralInferenceEngine().infer(
        (event("baseline", now, **{"pump.rpm": 2200, "pool.active": True, "heater.active": True, "spa.active": True}),)
    )
    assert report.events == ()
    assert report.current_state is InferredOperatingState.SPA


def test_missing_prior_values_do_not_invent_transitions() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    records = (
        event("gap", now, **{"pool.temperature": 82.0}),
        event(
            "present",
            now + timedelta(seconds=30),
            **{"pump.rpm": 2200, "pool.active": True, "heater.active": True, "spa.active": True},
        ),
    )
    report = BehavioralInferenceEngine().infer(records)
    assert report.events == ()
    assert report.current_state is InferredOperatingState.SPA

def test_pump_start_and_priming_are_inferred_from_observed_peak_then_drop() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    records = (
        event("off", now, **{"pump.rpm": 0, "pool.active": False}),
        event("start", now + timedelta(seconds=30), **{"pump.rpm": 3000, "pool.active": True}),
        event("settle", now + timedelta(minutes=2), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = BehavioralInferenceEngine().infer(records)
    assert [item.kind for item in report.events] == ["PUMP_START", "PUMP_PRIMING_INFERRED"]
    priming = report.events[-1]
    assert priming.attributes["peak_rpm"] == 3000
    assert priming.attributes["settled_rpm"] == 1800
    assert priming.evidence_event_ids == ("start", "settle")
    assert report.current_state is InferredOperatingState.FILTERING


def test_no_priming_claim_when_startup_does_not_show_large_drop() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    records = (
        event("off", now, **{"pump.rpm": 0, "pool.active": False}),
        event("start", now + timedelta(seconds=30), **{"pump.rpm": 1800, "pool.active": True}),
        event("steady", now + timedelta(minutes=2), **{"pump.rpm": 1700, "pool.active": True}),
    )
    report = BehavioralInferenceEngine().infer(records)
    assert [item.kind for item in report.events] == ["PUMP_START"]


def test_solar_transition_preserves_observed_context_and_differential() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    records = (
        event("off", now, **{"pump.rpm": 1800, "pool.temperature": 82.0, "solar.temperature": 90.0, "solar.active": False}),
        event("on", now + timedelta(minutes=1), **{"pump.rpm": 2400, "pool.temperature": 82.0, "solar.temperature": 94.0, "solar.active": True}),
    )
    report = BehavioralInferenceEngine().infer(records)
    solar_on = next(item for item in report.events if item.kind == "SOLAR_ACTIVATED")
    assert solar_on.attributes["temperature_differential_f"] == 12.0
    assert solar_on.attributes["pump_rpm"] == 2400
    assert solar_on.evidence_event_ids == ("on",)
    assert report.solar.activation_samples == 1
    assert "more repeated-day evidence" in report.solar.assessment


def test_repeated_solar_cycles_produce_provisional_hysteresis_not_controller_fact() -> None:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    records = []
    for day in range(3):
        base = now + timedelta(days=day)
        records.extend(
            (
                event(f"off{day}", base, **{"pump.rpm": 1800, "pool.temperature": 82.0, "solar.temperature": 88.0, "solar.active": False}),
                event(f"on{day}", base + timedelta(hours=2), **{"pump.rpm": 2400, "pool.temperature": 82.0, "solar.temperature": 94.0 + day * 0.2, "solar.active": True}),
                event(f"down{day}", base + timedelta(hours=6), **{"pump.rpm": 1800, "pool.temperature": 84.0, "solar.temperature": 90.0 + day * 0.2, "solar.active": False}),
            )
        )
    report = BehavioralInferenceEngine().infer(records)
    assert report.solar.activation_samples == 3
    assert report.solar.deactivation_samples >= 3
    assert report.solar.activation_differential_f == 12.2
    assert report.solar.deactivation_differential_f == 6.2
    assert report.solar.hysteresis_differential_f == 6.0
    assert "provisional hysteresis" in report.solar.assessment
    assert report.solar.confidence < 1.0


def test_inference_identity_is_deterministic() -> None:
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    records = (
        event("off", now, **{"pump.rpm": 0, "pool.active": False}),
        event("start", now + timedelta(seconds=30), **{"pump.rpm": 2000, "pool.active": True}),
    )
    left = BehavioralInferenceEngine().infer(records)
    right = BehavioralInferenceEngine().infer(records)
    assert left.events[0].inference_id == right.events[0].inference_id
    assert left.to_dict() == right.to_dict()
