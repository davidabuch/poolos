"""Deterministic multi-day commissioning-intelligence scenarios for milestone 11.6."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from poolos.daily_retrospective import DailyOperationalRetrospectiveEngine
from poolos.multiday_commissioning import (
    CommissioningEvidenceReason,
    CommissioningEvidenceStatus,
    MultiDayCommissioningIntelligence,
)
from poolos.observations import RecordedObservationEvent

ROOT = Path(__file__).resolve().parents[1]
FIRST_DATE = date(2026, 8, 1)


def event(
    event_id: str,
    at: datetime,
    *,
    healthy: bool = True,
    unavailable: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
    **values: object,
) -> RecordedObservationEvent:
    observations = tuple(
        {
            "observation_id": key,
            "value": value,
            "unit": "°F" if "temperature" in key else None,
            "confidence": 1.0,
            "quality": "good",
            "source_kind": "live",
            "source_id": f"sensor.{key.replace('.', '_')}",
        }
        for key, value in sorted(values.items())
    )
    return RecordedObservationEvent(
        event_id=event_id,
        recorded_at=at,
        kind="transition",
        changed_observation_ids=tuple(sorted(values)),
        observations=observations,
        health={
            "healthy": healthy,
            "missing_required": [],
            "unavailable_entities": list(unavailable),
            "stale_entities": list(stale),
        },
    )


def daily_report(
    report_date: date,
    *,
    solar: bool = False,
    activation_differential_f: float = 12.0,
    degraded: bool = False,
    excluded: bool = False,
    open_incident: bool = False,
):
    start = datetime.combine(report_date, datetime.min.time(), tzinfo=UTC)
    if excluded:
        records = (
            event("off", start, **{"solar.active": False}),
            event(
                "on",
                start + timedelta(minutes=5),
                **{
                    "solar.active": True,
                    "solar.temperature": 82.0 + activation_differential_f,
                    "pool.temperature": 82.0,
                },
            ),
            event(
                "off-again",
                start + timedelta(minutes=10),
                **{
                    "solar.active": False,
                    "solar.temperature": 89.0,
                    "pool.temperature": 84.0,
                },
            ),
        )
        end = start + timedelta(hours=4)
    elif solar:
        records = (
            event("off-0", start, **{"solar.active": False}),
            event(
                "on-1",
                start + timedelta(minutes=5),
                healthy=not degraded,
                unavailable=("sensor.pool",) if degraded else (),
                **{
                    "solar.active": True,
                    "solar.temperature": 82.0 + activation_differential_f,
                    "pool.temperature": 82.0,
                },
            ),
            event(
                "off-1",
                start + timedelta(minutes=10),
                **{
                    "solar.active": False,
                    "solar.temperature": 89.0,
                    "pool.temperature": 84.0,
                },
            ),
            event(
                "on-2",
                start + timedelta(minutes=15),
                **{
                    "solar.active": True,
                    "solar.temperature": 83.0 + activation_differential_f,
                    "pool.temperature": 82.0,
                },
            ),
            event(
                "off-2",
                start + timedelta(minutes=20),
                **{
                    "solar.active": False,
                    "solar.temperature": 90.0,
                    "pool.temperature": 84.0,
                },
            ),
            event("end", start + timedelta(minutes=25), **{"solar.active": False}),
        )
        end = start + timedelta(minutes=30)
    elif open_incident:
        records = (
            event("healthy", start),
            event(
                "failure",
                start + timedelta(minutes=5),
                healthy=False,
                unavailable=("sensor.pool",),
            ),
            event(
                "still-failed",
                start + timedelta(minutes=10),
                healthy=False,
                unavailable=("sensor.pool",),
            ),
        )
        end = start + timedelta(minutes=15)
    elif degraded:
        records = (
            event("healthy", start),
            event(
                "failure",
                start + timedelta(minutes=5),
                healthy=False,
                unavailable=("sensor.pool",),
            ),
            event("recovered", start + timedelta(minutes=10)),
            event("end", start + timedelta(minutes=20)),
        )
        end = start + timedelta(minutes=30)
    else:
        records = tuple(
            event(f"healthy-{minute}", start + timedelta(minutes=minute))
            for minute in (0, 10, 20)
        )
        end = start + timedelta(minutes=30)
    return DailyOperationalRetrospectiveEngine().generate(
        records,
        window_start=start,
        window_end=end,
        report_date=report_date.isoformat(),
        complete_day=True,
    )


def generate(reports):
    ordered_dates = sorted(date.fromisoformat(item.report_date) for item in reports)
    return MultiDayCommissioningIntelligence().generate(
        reports,
        start_date=ordered_dates[0],
        end_date=ordered_dates[-1],
    )


def test_several_good_days_with_solar_are_sufficient_for_human_review() -> None:
    reports = tuple(
        daily_report(
            FIRST_DATE + timedelta(days=offset),
            solar=offset < 3,
            activation_differential_f=11.0 + offset,
        )
        for offset in range(6)
    )
    result = generate(reports)

    assert result.evidence_status is CommissioningEvidenceStatus.SUFFICIENT_FOR_POLICY_REVIEW
    assert result.good_days == 6
    assert result.consecutive_good_days == 6
    assert result.consecutive_good_incident_free_days == 6
    assert result.usable_solar_learning_days == 3
    assert result.complete_solar_episode_count == 6
    assert result.activation_sample_count == 6
    assert result.deactivation_sample_count == 6
    assert result.activation_differentials.median is not None
    assert result.activation_differentials.range is not None
    assert result.provisional_cross_day_hysteresis_f is not None
    assert result.to_dict()["policy_created"] is False
    assert result.to_dict()["authority"] == "none"


def test_mixed_quality_days_remain_visible_without_contaminating_clean_samples() -> None:
    good_solar = daily_report(FIRST_DATE, solar=True, activation_differential_f=12.0)
    good_plain = daily_report(FIRST_DATE + timedelta(days=1))
    degraded_solar = daily_report(
        FIRST_DATE + timedelta(days=2),
        solar=True,
        activation_differential_f=50.0,
        degraded=True,
    )
    excluded_solar = daily_report(
        FIRST_DATE + timedelta(days=3),
        activation_differential_f=70.0,
        excluded=True,
    )
    result = generate((excluded_solar, degraded_solar, good_plain, good_solar))

    assert result.good_days == 2
    assert result.degraded_days == 1
    assert result.excluded_days == 1
    assert result.included_report_ids == (good_solar.report_id, good_plain.report_id)
    assert result.degraded_report_ids == (degraded_solar.report_id,)
    assert result.excluded_report_ids == (excluded_solar.report_id,)
    assert result.usable_solar_learning_days == 1
    assert all(value < 50.0 for value in result.activation_differentials.samples)
    assert degraded_solar.report_id not in {
        item.report_id for item in result.solar_contributions
    }
    assert excluded_solar.report_id not in {
        item.report_id for item in result.solar_contributions
    }


def test_recent_incident_requires_review_even_with_otherwise_sufficient_evidence() -> None:
    reports = [
        daily_report(FIRST_DATE + timedelta(days=offset), solar=offset < 3)
        for offset in range(6)
    ]
    reports[-1] = daily_report(FIRST_DATE + timedelta(days=5), open_incident=True)
    result = generate(tuple(reports))

    assert result.evidence_status is CommissioningEvidenceStatus.REVIEW_REQUIRED
    assert result.open_incident_count == 1
    assert result.most_recent_incident_date == FIRST_DATE + timedelta(days=5)
    assert CommissioningEvidenceReason.RECENT_OBSERVATION_INCIDENT in result.reason_codes
    assert CommissioningEvidenceReason.OPEN_OBSERVATION_INCIDENT in result.reason_codes


def test_older_recovered_incident_remains_provenance_but_does_not_block_forever() -> None:
    earlier = daily_report(FIRST_DATE, degraded=True)
    clean = tuple(
        daily_report(
            FIRST_DATE + timedelta(days=offset),
            solar=offset in {1, 2, 3},
        )
        for offset in range(1, 6)
    )
    result = generate((earlier, *clean))

    assert result.total_incident_count == 1
    assert result.recovered_incident_count == 1
    assert result.most_recent_incident_date == FIRST_DATE
    assert result.consecutive_good_days == 5
    assert result.evidence_status is CommissioningEvidenceStatus.SUFFICIENT_FOR_POLICY_REVIEW
    assert CommissioningEvidenceReason.RECENT_OBSERVATION_INCIDENT not in result.reason_codes


def test_insufficient_solar_evidence_remains_accumulating() -> None:
    reports = tuple(
        daily_report(FIRST_DATE + timedelta(days=offset), solar=offset < 2)
        for offset in range(5)
    )
    result = generate(reports)

    assert result.evidence_status is CommissioningEvidenceStatus.ACCUMULATING
    assert CommissioningEvidenceReason.INSUFFICIENT_USABLE_SOLAR_DAYS in result.reason_codes
    assert CommissioningEvidenceReason.INSUFFICIENT_COMPLETE_SOLAR_EPISODES in result.reason_codes


def test_real_commissioning_shape_progresses_without_creating_policy() -> None:
    # Models calibrated startup/reload noise in daily reports, one earlier
    # degraded day, and an increasing sequence of clean observation days.
    degraded = daily_report(FIRST_DATE, degraded=True)
    first_clean = tuple(
        daily_report(FIRST_DATE + timedelta(days=offset), solar=offset <= 2)
        for offset in range(1, 4)
    )
    accumulating = generate((degraded, *first_clean))
    assert accumulating.evidence_status is CommissioningEvidenceStatus.ACCUMULATING

    additional = tuple(
        daily_report(FIRST_DATE + timedelta(days=offset), solar=offset == 4)
        for offset in range(4, 6)
    )
    sufficient = generate((degraded, *first_clean, *additional))
    assert sufficient.evidence_status is CommissioningEvidenceStatus.SUFFICIENT_FOR_POLICY_REVIEW
    assert sufficient.to_dict()["policy_created"] is False
    assert "Human review only" in sufficient.assessment


def test_identity_ordering_and_serialization_are_deterministic() -> None:
    reports = tuple(
        daily_report(FIRST_DATE + timedelta(days=offset), solar=offset < 3)
        for offset in range(5)
    )
    forward = generate(reports)
    reverse = generate(tuple(reversed(reports)))

    assert forward.report_id == reverse.report_id
    assert forward.to_dict() == reverse.to_dict()
    assert forward.to_dict()["criteria"]["minimum_good_days"] == 5
    assert forward.source_report_ids == tuple(item.report_id for item in reports)


def test_rejects_partial_duplicate_or_out_of_range_daily_reports() -> None:
    complete = daily_report(FIRST_DATE)
    partial = DailyOperationalRetrospectiveEngine().generate(
        (),
        window_start=datetime(2026, 8, 2, tzinfo=UTC),
        window_end=datetime(2026, 8, 3, tzinfo=UTC),
        report_date="2026-08-02",
        complete_day=False,
    )
    intelligence = MultiDayCommissioningIntelligence()
    with pytest.raises(ValueError, match="completed"):
        intelligence.generate(
            (partial,), start_date=FIRST_DATE, end_date=FIRST_DATE + timedelta(days=1)
        )
    with pytest.raises(ValueError, match="unique"):
        intelligence.generate(
            (complete, complete), start_date=FIRST_DATE, end_date=FIRST_DATE
        )
    with pytest.raises(ValueError, match="outside"):
        intelligence.generate(
            (complete,),
            start_date=FIRST_DATE + timedelta(days=1),
            end_date=FIRST_DATE + timedelta(days=1),
        )
    incident_report = daily_report(FIRST_DATE, degraded=True)
    naive_incident = replace(
        incident_report.incidents[0], started_at=datetime(2026, 8, 1, 0, 5)
    )
    with pytest.raises(ValueError, match="incident timestamps"):
        intelligence.generate(
            (replace(incident_report, incidents=(naive_incident,)),),
            start_date=FIRST_DATE,
            end_date=FIRST_DATE,
        )


def test_module_imports_no_control_service_network_or_vendor_authority() -> None:
    path = ROOT / "poolos" / "multiday_commissioning.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prohibited = {
        "commands",
        "custom_components",
        "delivery",
        "execution",
        "hal",
        "homeassistant",
        "intellicenter",
        "requests",
        "runtime",
        "socket",
        "urllib",
        "vendors",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not any(part in prohibited for part in name.split("."))
