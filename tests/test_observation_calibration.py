"""Real-world observation calibration regressions for milestone 11.5.1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from poolos.daily_retrospective import (
    DailyOperationalRetrospectiveEngine,
    ObservationIncidentState,
    SoakQualityReason,
    SoakQualityPolicy,
    SoakQualityStatus,
)
from poolos.observations import RecordedObservationEvent

START = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def event(
    event_id: str,
    seconds: int,
    *,
    kind: str = "transition",
    healthy: bool = True,
    missing: tuple[str, ...] = (),
    unavailable: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
) -> RecordedObservationEvent:
    return RecordedObservationEvent(
        event_id=event_id,
        recorded_at=START + timedelta(seconds=seconds),
        kind=kind,
        changed_observation_ids=(),
        observations=(),
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
    end_seconds: int,
):
    return DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=START,
        window_end=START + timedelta(seconds=end_seconds),
        report_date="2026-08-09",
        complete_day=False,
    )


def test_startup_transient_within_60_seconds_is_provenance_not_degradation() -> None:
    assert SoakQualityPolicy().startup_health_grace == timedelta(seconds=60)
    live_constants = (ROOT / "custom_components" / "poolos" / "const.py").read_text(
        encoding="utf-8"
    )
    assert "STARTUP_HEALTH_GRACE = timedelta(seconds=60)" in live_constants
    records = (
        event("baseline", 0, kind="baseline"),
        event(
            "initializing",
            20,
            healthy=False,
            unavailable=("sensor.pool", "sensor.pump"),
            stale=("sensor.water",),
        ),
        event("recovered", 50),
        event("checkpoint-10m", 600),
        event("checkpoint-20m", 1200),
        event("checkpoint-30m", 1800),
    )
    result = report(records, end_seconds=2400)

    assert result.incidents == ()
    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.unhealthy_duration_seconds == 0
    assert result.soak_quality.unavailable_duration_seconds == 0
    assert result.soak_quality.stale_duration_seconds == 0
    assert result.actual.healthy_coverage_seconds == result.actual.evidence_coverage_seconds
    assert result.soak_quality.startup_evidence_ids == ("baseline",)
    assert (
        SoakQualityReason.STARTUP_OR_RESTART_WINDOW
        in result.soak_quality.reason_codes
    )


def test_august_9_shaped_reloads_and_healthy_staleness_do_not_multiply_incidents() -> None:
    # Compact synthetic shape derived from real 2026-08-09 commissioning
    # evidence. The 11 MB raw log is intentionally not embedded in the repo.
    records = [
        event("healthy-start", 0),
        event("healthy-stale-5m", 300, stale=("sensor.pump_rpm", "sensor.water")),
        event("healthy-stale-10m", 600, stale=("sensor.pool",)),
        event("healthy-stale-15m", 900, stale=("sensor.pump_gpm",)),
        event("healthy-stale-25m", 1500, stale=("sensor.water",)),
        event("healthy-stale-30m", 1800, stale=("sensor.pump_rpm",)),
        event("healthy-stale-35m", 2100, stale=("sensor.pool",)),
        event("healthy-stale-45m", 2700, stale=("sensor.pump_gpm",)),
        event("healthy-stale-50m", 3000, stale=("sensor.water",)),
        event("healthy-stale-55m", 3300, stale=("sensor.pool",)),
        event("healthy-end", 3600),
    ]
    for index, baseline_at in enumerate((60, 1200, 2400)):
        records.extend(
            (
                event(f"baseline-{index}", baseline_at, kind="baseline"),
                event(
                    f"startup-unavailable-{index}",
                    baseline_at + 20,
                    healthy=False,
                    unavailable=("sensor.all_required",),
                    stale=("sensor.pump_rpm", "sensor.pump_gpm", "sensor.water"),
                ),
                event(f"startup-recovered-{index}", baseline_at + 50),
            )
        )
    result = report(tuple(reversed(records)), end_seconds=3900)

    assert result.incidents == ()
    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.unhealthy_duration_seconds == 0
    assert result.soak_quality.unavailable_duration_seconds == 0
    assert result.soak_quality.stale_duration_seconds == 0
    assert len(result.soak_quality.startup_evidence_ids) == 3
    assert SoakQualityReason.REQUIRED_ENTITY_STALE not in result.soak_quality.reason_codes


def test_healthy_tolerated_staleness_never_opens_incident_or_degrades_duration() -> None:
    records = tuple(
        event(
            f"healthy-stale-{minute}",
            minute * 60,
            stale=("sensor.pump_rpm", "sensor.pump_gpm", "sensor.water"),
        )
        for minute in range(0, 61, 10)
    )
    result = report(records, end_seconds=4200)

    assert result.incidents == ()
    assert result.soak_quality.status is SoakQualityStatus.GOOD
    assert result.soak_quality.stale_duration_seconds == 0
    assert SoakQualityReason.REQUIRED_ENTITY_STALE not in result.soak_quality.reason_codes


def test_unhealthy_stale_and_unavailable_failure_outside_grace_still_counts() -> None:
    records = (
        event("baseline", 0, kind="baseline"),
        event("healthy", 60),
        event(
            "failure",
            300,
            healthy=False,
            unavailable=("sensor.pool",),
            stale=("sensor.pump",),
        ),
        event(
            "failure-checkpoint",
            600,
            healthy=False,
            unavailable=("sensor.pool",),
            stale=("sensor.pump",),
        ),
        event("recovered", 900),
        event("healthy-end", 1200),
    )
    result = report(records, end_seconds=1500)

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.state is ObservationIncidentState.RECOVERED
    assert incident.source_event_ids == (
        "failure",
        "failure-checkpoint",
        "recovered",
    )
    assert incident.unavailable_observations == ("sensor.pool",)
    assert incident.stale_observations == ("sensor.pump",)
    assert result.soak_quality.unhealthy_duration_seconds == 600
    assert result.soak_quality.unavailable_duration_seconds == 600
    assert result.soak_quality.stale_duration_seconds == 600
    assert result.soak_quality.status in {
        SoakQualityStatus.DEGRADED,
        SoakQualityStatus.EXCLUDED,
    }


def test_failure_crossing_grace_boundary_is_suppressed_only_until_boundary() -> None:
    records = (
        event("baseline", 0, kind="baseline"),
        event(
            "failure-during-grace",
            30,
            healthy=False,
            unavailable=("sensor.pool",),
            stale=("sensor.pump",),
        ),
        event(
            "failure-after-grace",
            70,
            healthy=False,
            unavailable=("sensor.pool",),
            stale=("sensor.pump",),
        ),
        event("recovered", 120),
        event("healthy-end", 600),
    )
    result = report(records, end_seconds=900)

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.started_at == START + timedelta(seconds=60)
    assert incident.ended_at == START + timedelta(seconds=120)
    assert result.soak_quality.unhealthy_duration_seconds == 60
    assert result.soak_quality.unavailable_duration_seconds == 60
    assert result.soak_quality.stale_duration_seconds == 60
    assert result.soak_quality.status is SoakQualityStatus.DEGRADED


def test_calibration_replay_and_input_order_are_deterministic() -> None:
    records = (
        event("baseline", 0, kind="baseline"),
        event("startup-failure", 20, healthy=False, unavailable=("sensor.pool",)),
        event("startup-recovery", 50),
        event("healthy-stale", 300, stale=("sensor.pump",)),
        event("healthy-end", 600),
    )
    forward = report(records, end_seconds=900)
    reverse = report(tuple(reversed(records)), end_seconds=900)

    assert forward.report_id == reverse.report_id
    assert forward.to_dict() == reverse.to_dict()
