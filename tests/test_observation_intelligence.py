"""Golden observation-intelligence scenarios for milestone 11.5."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from poolos.behavioral_inference import (
    BehavioralInferenceEngine,
    SolarEpisodeState,
)
from poolos.daily_retrospective import (
    DailyOperationalRetrospectiveEngine,
    ObservationIncidentState,
    SoakQualityReason,
    SoakQualityStatus,
    SolarLearningQuality,
)
from poolos.observations import RecordedObservationEvent

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def event(
    event_id: str,
    at: datetime,
    *,
    healthy: bool = True,
    missing: tuple[str, ...] = (),
    unavailable: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
    kind: str = "transition",
    **values: object,
) -> RecordedObservationEvent:
    observations = []
    for key, value in sorted(values.items()):
        unit = None
        if key == "pump.rpm":
            unit = "rpm"
        elif key == "pump.gpm":
            unit = "gpm"
        elif key == "pump.power":
            unit = "W"
        elif "temperature" in key:
            unit = "°F"
        observations.append(
            {
                "observation_id": key,
                "value": value,
                "unit": unit,
                "confidence": 1.0,
                "quality": "good",
                "source_kind": "live",
                "source_id": f"sensor.{key.replace('.', '_')}",
            }
        )
    return RecordedObservationEvent(
        event_id=event_id,
        recorded_at=at,
        kind=kind,
        changed_observation_ids=tuple(sorted(values)),
        observations=tuple(observations),
        health={
            "healthy": healthy,
            "missing_required": list(missing),
            "unavailable_entities": list(unavailable),
            "stale_entities": list(stale),
        },
    )


def report(
    records: tuple[RecordedObservationEvent, ...],
    *,
    end: datetime,
):
    return DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=START,
        window_end=end,
        report_date="2026-08-08",
        complete_day=False,
    )


def healthy_checkpoint(event_id: str, minutes: int, **values: object) -> RecordedObservationEvent:
    defaults: dict[str, object] = {
        "pump.rpm": 1800,
        "pool.active": True,
        "solar.active": False,
    }
    defaults.update(values)
    return event(event_id, START + timedelta(minutes=minutes), **defaults)


def test_complete_healthy_coverage_is_good() -> None:
    records = tuple(
        healthy_checkpoint(f"h{minute}", minute)
        for minute in (0, 10, 20, 30)
    )
    result = report(records, end=START + timedelta(minutes=40))

    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.observation_coverage_ratio == 1.0
    assert result.soak_quality.healthy_observation_coverage_ratio == 1.0
    assert result.soak_quality.largest_evidence_gap_seconds == 0.0
    assert result.soak_quality.reason_codes == (
        SoakQualityReason.COMPLETE_HEALTHY_WINDOW,
    )


def test_real_upstream_failure_is_one_recovered_incident_and_remains_evidence() -> None:
    records = (
        healthy_checkpoint("healthy-before", 0),
        event(
            "outage-start",
            START + timedelta(minutes=5),
            healthy=False,
            unavailable=("sensor.pool", "sensor.pump"),
            stale=("sensor.water",),
            **{"solar.active": False},
        ),
        event(
            "outage-checkpoint",
            START + timedelta(minutes=10),
            healthy=False,
            unavailable=("sensor.pool", "sensor.pump"),
            stale=("sensor.water",),
            **{"solar.active": False},
        ),
        healthy_checkpoint("recovered", 20),
        healthy_checkpoint("healthy-after", 30),
    )
    result = report(records, end=START + timedelta(minutes=40))

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.incident_type == "UPSTREAM_OBSERVATION_FAILURE"
    assert incident.state is ObservationIncidentState.RECOVERED
    assert incident.recovered is True
    assert incident.duration_seconds == 15 * 60
    assert incident.source_event_ids == (
        "outage-start",
        "outage-checkpoint",
        "recovered",
    )
    assert incident.unavailable_observations == ("sensor.pool", "sensor.pump")
    assert incident.stale_observations == ("sensor.water",)
    assert result.soak_quality.status in {
        SoakQualityStatus.DEGRADED,
        SoakQualityStatus.EXCLUDED,
    }
    assert result.soak_quality.incident_count == 1
    assert result.soak_quality.unavailable_duration_seconds == 15 * 60
    assert result.soak_quality.stale_duration_seconds == 15 * 60
    assert result.to_dict()["command_delivery_enabled"] is False
    assert "outage-start" in result.soak_quality.source_evidence_ids


def test_sixty_three_millisecond_unhealthy_artifact_is_not_durable_incident() -> None:
    unhealthy_at = START + timedelta(minutes=5)
    records = (
        healthy_checkpoint("healthy-before", 0),
        event(
            "transient-unhealthy",
            unhealthy_at,
            healthy=False,
            unavailable=("binary_sensor.grid",),
            stale=("B1202", "PMP01"),
        ),
        event(
            "recovered-63ms",
            unhealthy_at + timedelta(milliseconds=63),
            healthy=True,
        ),
        healthy_checkpoint("healthy-after", 10),
    )

    result = report(records, end=START + timedelta(minutes=20))

    assert result.incidents == ()
    assert result.soak_quality.incident_count == 0


def test_single_sparse_unhealthy_record_qualifies_when_supported_for_cadence() -> None:
    unhealthy_at = START + timedelta(minutes=5)
    records = (
        healthy_checkpoint("healthy-before", 0),
        event(
            "sparse-unhealthy",
            unhealthy_at,
            healthy=False,
            unavailable=("sensor.pool",),
        ),
        event(
            "sparse-recovered",
            unhealthy_at + timedelta(seconds=30),
            healthy=True,
        ),
    )

    incident = report(records, end=START + timedelta(minutes=10)).incidents[0]

    assert incident.started_at == unhealthy_at
    assert incident.ended_at == unhealthy_at + timedelta(seconds=30)
    assert incident.source_event_ids == ("sparse-unhealthy", "sparse-recovered")


def test_open_incident_has_no_fabricated_recovery_time() -> None:
    records = (
        healthy_checkpoint("healthy", 0),
        event(
            "unhealthy",
            START + timedelta(minutes=10),
            healthy=False,
            unavailable=("sensor.pool",),
        ),
        event(
            "still-unhealthy",
            START + timedelta(minutes=20),
            healthy=False,
            unavailable=("sensor.pool",),
        ),
    )
    result = report(records, end=START + timedelta(minutes=30))
    incident = result.incidents[0]

    assert incident.state is ObservationIncidentState.OPEN
    assert incident.recovered is False
    assert incident.ended_at is None
    assert incident.duration_seconds == 20 * 60

    recovered = report(
        (*records, healthy_checkpoint("recovered", 30)),
        end=START + timedelta(minutes=40),
    ).incidents[0]
    assert recovered.incident_id == incident.incident_id
    assert recovered.state is ObservationIncidentState.RECOVERED


def test_sparse_day_is_excluded_and_largest_gap_is_explicit() -> None:
    result = report(
        (healthy_checkpoint("only", 0),),
        end=START + timedelta(hours=4),
    )

    assert result.soak_quality.status is SoakQualityStatus.EXCLUDED
    assert result.soak_quality.observation_coverage_ratio == 0.0625
    assert result.soak_quality.largest_evidence_gap_seconds == 3.75 * 3600
    assert SoakQualityReason.INSUFFICIENT_COVERAGE in result.soak_quality.reason_codes
    assert SoakQualityReason.LARGE_EVIDENCE_GAP in result.soak_quality.reason_codes


def test_baseline_is_startup_evidence_without_claiming_restart() -> None:
    records = (
        event("baseline", START, kind="baseline", **{"pump.rpm": 0}),
        healthy_checkpoint("checkpoint", 10),
        healthy_checkpoint("checkpoint-2", 20),
    )
    result = report(records, end=START + timedelta(minutes=30))

    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.startup_evidence_ids == ("baseline",)
    assert (
        SoakQualityReason.STARTUP_OR_RESTART_WINDOW
        in result.soak_quality.reason_codes
    )
    assert SoakQualityReason.COMPLETE_HEALTHY_WINDOW in result.soak_quality.reason_codes


def test_solar_transition_is_enriched_and_episode_is_closed() -> None:
    records = (
        event("off", START, **{"solar.active": False, "pump.rpm": 1800}),
        event(
            "on",
            START + timedelta(minutes=5),
            **{
                "solar.active": True,
                "solar.temperature": 95.0,
                "pool.temperature": 82.0,
                "water.temperature": 81.5,
                "air.temperature": 76.0,
                "pool.target_temperature": 86.0,
                "pool.heating_demand_active": True,
                "spa.active": False,
                "pool.active": True,
                "heater.active": False,
                "pump.rpm": 2400,
                "pump.gpm": 52.0,
                "pump.power": 1350.0,
            },
        ),
        event("steady", START + timedelta(minutes=15), **{"solar.active": True}),
        event(
            "off-again",
            START + timedelta(minutes=35),
            **{
                "solar.active": False,
                "solar.temperature": 88.0,
                "pool.temperature": 84.0,
                "water.temperature": 83.5,
                "pump.rpm": 1800,
            },
        ),
    )
    inference = BehavioralInferenceEngine().infer(records)
    transition = next(item for item in inference.events if item.kind == "SOLAR_ACTIVATED")

    assert transition.attributes["roof_to_pool_differential_f"] == 13.0
    assert transition.attributes["roof_to_water_differential_f"] == 13.5
    assert transition.attributes["pool_target_temperature_f"] == 86.0
    assert transition.attributes["pool_heating_demand_active"] is True
    assert "solar_preferred_active" not in transition.attributes
    assert transition.attributes["pump_gpm"] == 52.0
    assert transition.attributes["pump_power"] == 1350.0
    with pytest.raises(TypeError):
        transition.attributes["pump_rpm"] = 1

    assert len(inference.solar_episodes) == 1
    episode = inference.solar_episodes[0]
    assert episode.state is SolarEpisodeState.CLOSED
    assert episode.duration_seconds == 30 * 60
    assert episode.source_event_ids == ("on", "off-again")


def test_missing_solar_attributes_are_not_fabricated_and_episode_remains_open() -> None:
    inference = BehavioralInferenceEngine().infer(
        (
            event("off", START, **{"solar.active": False}),
            event("on", START + timedelta(minutes=5), **{"solar.active": True}),
        )
    )
    activation = inference.events[0]

    assert "solar_temperature_f" not in activation.attributes
    assert "roof_to_pool_differential_f" not in activation.attributes
    assert inference.solar_episodes[0].state is SolarEpisodeState.OPEN
    assert inference.solar_episodes[0].deactivation_time is None
    assert inference.solar_episodes[0].duration_seconds is None

    closed = BehavioralInferenceEngine().infer(
        (
            event("off", START, **{"solar.active": False}),
            event("on", START + timedelta(minutes=5), **{"solar.active": True}),
            event("off-again", START + timedelta(minutes=10), **{"solar.active": False}),
        )
    ).solar_episodes[0]
    assert closed.episode_id == inference.solar_episodes[0].episode_id


def test_multiple_cycles_produce_daily_empirical_hysteresis_summary() -> None:
    records = (
        event("off-0", START, **{"solar.active": False, "pump.rpm": 1800}),
        event("on-1", START + timedelta(minutes=5), **{"solar.active": True, "solar.temperature": 94.0, "pool.temperature": 82.0, "pump.rpm": 2400}),
        event("off-1", START + timedelta(minutes=10), **{"solar.active": False, "solar.temperature": 89.0, "pool.temperature": 84.0, "pump.rpm": 1800}),
        event("on-2", START + timedelta(minutes=15), **{"solar.active": True, "solar.temperature": 96.0, "pool.temperature": 83.0, "pump.rpm": 2400}),
        event("off-2", START + timedelta(minutes=20), **{"solar.active": False, "solar.temperature": 90.0, "pool.temperature": 84.0, "pump.rpm": 1800}),
        healthy_checkpoint("end", 25),
    )
    result = report(records, end=START + timedelta(minutes=30))
    solar = result.solar_learning

    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert solar.activation_count == 2
    assert solar.deactivation_count == 2
    assert solar.complete_episode_count == 2
    assert solar.total_observed_runtime_seconds == 10 * 60
    assert solar.median_activation_differential_f == 12.5
    assert solar.median_deactivation_differential_f == 5.5
    assert solar.provisional_hysteresis_differential_f == 7.0
    assert solar.learning_quality is SolarLearningQuality.INCLUDED
    assert solar.usable_for_learning is True
    assert solar.to_dict()["poolos_control_rule"] is False


def test_degraded_and_excluded_days_bound_solar_learning() -> None:
    degraded_records = (
        event("off", START, **{"solar.active": False}),
        event("on", START + timedelta(minutes=5), healthy=False, stale=("sensor.water",), **{"solar.active": True, "solar.temperature": 94.0, "pool.temperature": 82.0}),
        event("off-again", START + timedelta(minutes=10), **{"solar.active": False, "solar.temperature": 88.0, "pool.temperature": 84.0}),
        healthy_checkpoint("end", 20),
    )
    degraded = report(degraded_records, end=START + timedelta(minutes=30))
    assert degraded.soak_quality.status is SoakQualityStatus.DEGRADED
    assert degraded.solar_learning.learning_quality is SolarLearningQuality.DEGRADED
    assert degraded.solar_learning.usable_for_learning is True

    excluded = report(degraded_records, end=START + timedelta(hours=4))
    assert excluded.soak_quality.status is SoakQualityStatus.EXCLUDED
    assert excluded.solar_learning.learning_quality is SolarLearningQuality.EXCLUDED
    assert excluded.solar_learning.usable_for_learning is False


def test_replay_identity_ordering_serialization_and_existing_fields_are_stable() -> None:
    records = (
        event("off", START, **{"solar.active": False, "pump.rpm": 1800}),
        event("on", START + timedelta(minutes=10), **{"solar.active": True, "solar.temperature": 94.0, "pool.temperature": 82.0, "pump.rpm": 2400}),
        event("off-again", START + timedelta(minutes=20), **{"solar.active": False, "solar.temperature": 88.0, "pool.temperature": 84.0, "pump.rpm": 1800}),
    )
    left = report(records, end=START + timedelta(minutes=30))
    right = report(tuple(reversed(records)), end=START + timedelta(minutes=30))

    assert left.report_id == right.report_id
    assert left.to_dict() == right.to_dict()
    payload = left.to_dict()
    for existing in (
        "report_id",
        "schema_version",
        "report_date",
        "generated_at",
        "complete_day",
        "actual",
        "counterfactual",
        "authority",
        "command_delivery_enabled",
    ):
        assert existing in payload
    assert payload["daily_assessment"]


def test_analysis_modules_import_no_control_vendor_network_or_io_authority() -> None:
    prohibited_roots = {
        "custom_components",
        "homeassistant",
        "intellicenter",
        "requests",
        "socket",
        "urllib",
    }
    prohibited_poolos = {
        "commands",
        "delivery",
        "execution",
        "hal",
        "home_assistant_transport_adapter",
        "runtime",
        "vendors",
    }
    for relative in (
        "poolos/behavioral_inference.py",
        "poolos/daily_retrospective.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in prohibited_roots
                if name.startswith("poolos."):
                    assert name.split(".")[1] not in prohibited_poolos


def test_behavioral_inference_rejects_naive_evidence_time() -> None:
    naive = event("naive", datetime(2026, 8, 8, 8, 0), **{"solar.active": False})
    with pytest.raises(ValueError, match="timezone-aware"):
        BehavioralInferenceEngine().infer((naive,))
    with pytest.raises(ValueError, match="timezone-aware"):
        report((naive,), end=START + timedelta(minutes=5))
