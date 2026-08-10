"""Deterministic expected-outage annotation contracts for milestone 11.6.1."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path

from poolos.daily_retrospective import (
    DailyOperationalRetrospectiveEngine,
    ObservationIncidentClassification,
    SoakQualityStatus,
)
from poolos.expected_outage import ExpectedOutageAcknowledgment
from poolos.multiday_commissioning import (
    CommissioningEvidenceStatus,
    MultiDayCommissioningIntelligence,
)
from poolos.observations import PersistentObservationRecorder, RecordedObservationEvent
from tests.test_multiday_commissioning import daily_report


def event(
    event_id: str,
    at: datetime,
    *,
    healthy: bool = True,
    solar_active: bool = False,
) -> RecordedObservationEvent:
    return RecordedObservationEvent(
        event_id=event_id,
        recorded_at=at,
        kind="health_transition",
        changed_observation_ids=("solar.active",),
        observations=(
            {
                "observation_id": "solar.active",
                "value": solar_active,
                "unit": None,
                "confidence": 1.0,
                "quality": "good",
                "source_kind": "live",
                "source_id": "sensor.solar_active",
            },
        ),
        health={
            "healthy": healthy,
            "missing_required": [],
            "unavailable_entities": [] if healthy else ["sensor.pool_temperature"],
            "stale_entities": [],
        },
    )


def acknowledgment(at: datetime, source: str = "operator:test") -> ExpectedOutageAcknowledgment:
    return ExpectedOutageAcknowledgment.create(acknowledged_at=at, source_id=source)


def report(
    *,
    outage_start: datetime,
    outage_end: datetime,
    acknowledgments: tuple[ExpectedOutageAcknowledgment, ...] = (),
):
    window_start = outage_start - timedelta(minutes=20)
    window_end = outage_end + timedelta(minutes=20)
    records = (
        event("healthy-start", window_start),
        event("healthy-before", outage_start - timedelta(minutes=10)),
        event("outage", outage_start, healthy=False, solar_active=False),
        event("outage-checkpoint", outage_start + timedelta(minutes=5), healthy=False),
        event("recovered", outage_end, solar_active=True),
        event("healthy-end", outage_end + timedelta(minutes=10), solar_active=True),
    )
    return DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=window_start,
        window_end=window_end,
        report_date=window_start.date().isoformat(),
        expected_outage_acknowledgments=acknowledgments,
        complete_day=True,
    )


def test_acknowledgment_before_after_and_during_outage_matches() -> None:
    start = datetime(2026, 8, 9, 8, 20, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    for pressed_at in (
        start - timedelta(minutes=30),
        end + timedelta(minutes=40),
        start + timedelta(minutes=5),
    ):
        incident = report(
            outage_start=start,
            outage_end=end,
            acknowledgments=(acknowledgment(pressed_at),),
        ).incidents[0]
        assert incident.classification is ObservationIncidentClassification.EXPECTED_OUTAGE
        assert incident.expected is True
        assert incident.acknowledged_by_operator is True
        assert incident.troubleshooting_required is False


def test_outside_window_is_unexpected_and_exact_boundaries_match() -> None:
    start = datetime(2026, 8, 9, 8, 20, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    outside = report(
        outage_start=start,
        outage_end=end,
        acknowledgments=(acknowledgment(start - timedelta(hours=2, seconds=1)),),
    ).incidents[0]
    assert outside.classification is ObservationIncidentClassification.UNEXPECTED
    assert outside.troubleshooting_required is True

    for pressed_at in (start - timedelta(hours=2), end + timedelta(hours=2)):
        matched = report(
            outage_start=start,
            outage_end=end,
            acknowledgments=(acknowledgment(pressed_at),),
        ).incidents[0]
        assert matched.expected is True


def test_multiple_incidents_and_overlapping_acknowledgments_preserve_identity() -> None:
    window_start = datetime(2026, 8, 9, tzinfo=UTC)
    records = (
        event("healthy-0", window_start),
        event("outage-1", window_start + timedelta(minutes=20), healthy=False),
        event("recover-1", window_start + timedelta(minutes=30)),
        event("outage-2", window_start + timedelta(minutes=50), healthy=False),
        event("recover-2", window_start + timedelta(minutes=60)),
        event("healthy-end", window_start + timedelta(minutes=70)),
    )
    acknowledgments = (
        acknowledgment(window_start + timedelta(minutes=40), "operator:first"),
        acknowledgment(window_start + timedelta(minutes=45), "operator:second"),
    )
    result = DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=window_start,
        window_end=window_start + timedelta(minutes=80),
        report_date=window_start.date().isoformat(),
        expected_outage_acknowledgments=tuple(reversed(acknowledgments)),
        complete_day=True,
    )
    assert len(result.incidents) == 2
    assert len({item.incident_id for item in result.incidents}) == 2
    assert all(item.expected for item in result.incidents)
    assert all(len(item.acknowledgment_ids) == 2 for item in result.incidents)


def test_actual_duration_and_raw_health_remain_truthful_without_quality_penalty() -> None:
    start = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    result = report(
        outage_start=start,
        outage_end=end,
        acknowledgments=(acknowledgment(end + timedelta(minutes=40)),),
    )
    incident = result.incidents[0]
    assert incident.started_at == start
    assert incident.ended_at == end
    assert incident.duration_seconds == 600.0
    assert incident.unavailable_observations == ("sensor.pool_temperature",)
    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.incident_count == 1
    assert result.soak_quality.expected_incident_count == 1
    assert result.soak_quality.unexpected_incident_count == 0
    assert result.soak_quality.healthy_observation_coverage_ratio < 1.0
    assert result.soak_quality.commissioning_healthy_coverage_ratio == 1.0


def test_expected_outage_evidence_is_not_used_for_solar_learning() -> None:
    start = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    result = report(
        outage_start=start,
        outage_end=start + timedelta(minutes=10),
        acknowledgments=(acknowledgment(start),),
    )
    incident_ids = set(result.incidents[0].source_event_ids)
    assert not incident_ids.intersection(result.solar_learning.source_evidence_ids)
    assert result.solar_learning.activation_count == 0


def test_unexpected_outage_still_degrades_normally() -> None:
    start = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    result = report(outage_start=start, outage_end=start + timedelta(minutes=10))
    assert result.soak_quality.status is SoakQualityStatus.DEGRADED
    assert result.soak_quality.unexpected_incident_count == 1
    assert result.incidents[0].troubleshooting_required is True


def test_expected_recent_outage_does_not_block_multiday_readiness() -> None:
    first = date(2026, 8, 1)
    reports = [
        daily_report(first + timedelta(days=offset), solar=offset < 3)
        for offset in range(5)
    ]
    outage_start = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)
    reports.append(
        report(
            outage_start=outage_start,
            outage_end=outage_start + timedelta(minutes=10),
            acknowledgments=(acknowledgment(outage_start),),
        )
    )
    result = MultiDayCommissioningIntelligence().generate(
        reports,
        start_date=first,
        end_date=first + timedelta(days=5),
    )
    assert result.evidence_status is CommissioningEvidenceStatus.SUFFICIENT_FOR_POLICY_REVIEW
    assert result.total_incident_count == 1
    assert result.expected_incident_count == 1
    assert result.unexpected_incident_count == 0
    assert result.most_recent_incident_date == first + timedelta(days=5)
    assert result.most_recent_unexpected_incident_date is None
    assert result.open_unexpected_incident_count == 0
    assert result.consecutive_good_incident_free_days == 6


def test_cross_midnight_acknowledgment_matches_next_day_incident() -> None:
    pressed = datetime(2026, 8, 9, 23, 30, tzinfo=UTC)
    start = datetime(2026, 8, 10, 0, 15, tzinfo=UTC)
    result = report(
        outage_start=start,
        outage_end=start + timedelta(minutes=10),
        acknowledgments=(acknowledgment(pressed),),
    )
    assert result.incidents[0].expected is True


def test_acknowledgment_does_not_turn_startup_grace_transient_into_incident() -> None:
    start = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
    records = (
        replace(event("baseline", start, healthy=False), kind="baseline"),
        event("recovered", start + timedelta(seconds=30)),
        event("healthy", start + timedelta(minutes=5)),
    )
    result = DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=10),
        report_date=start.date().isoformat(),
        expected_outage_acknowledgments=(acknowledgment(start),),
        complete_day=True,
    )
    assert result.incidents == ()
    assert result.soak_quality.expected_incident_count == 0


def test_identity_serialization_and_durable_replay_are_deterministic(
    tmp_path: Path,
) -> None:
    pressed = datetime(2026, 8, 9, 9, 15, tzinfo=UTC)
    expected = acknowledgment(pressed)
    assert expected == acknowledgment(pressed)
    assert expected.to_dict() == acknowledgment(pressed).to_dict()

    recorder = PersistentObservationRecorder(tmp_path)
    recorder.record_expected_outage_acknowledgment(expected)
    recorder.record_expected_outage_acknowledgment(expected)
    restored = recorder.query_expected_outage_acknowledgments(
        start=pressed - timedelta(hours=3),
        end=pressed + timedelta(hours=3),
    )
    assert restored == (expected,)
    payloads = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert all(item["record_type"] == "expected_outage_acknowledgment" for item in payloads)
    assert payloads[0]["matching_window_start"] == (pressed - timedelta(hours=2)).isoformat()
