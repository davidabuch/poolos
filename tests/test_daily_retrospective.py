from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.daily_retrospective import CounterfactualStatus, DailyOperationalRetrospectiveEngine
from poolos.operator_recommendation import OperatorRecommendation, OperatorRecommendationStatus
from poolos.observations import RecordedObservationEvent


def event(event_id: str, at: datetime, **values: object) -> RecordedObservationEvent:
    observations = []
    for key, value in sorted(values.items()):
        unit = None
        if key == "pump.rpm":
            unit = "rpm"
        elif key == "pump.power":
            unit = "W"
        elif key.endswith("temperature"):
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
        event_id,
        at,
        "transition",
        tuple(sorted(values)),
        tuple(observations),
        {"healthy": True},
    )


def recommendation(*, rpm: int | None = 1800, status: OperatorRecommendationStatus = OperatorRecommendationStatus.RECOMMENDED) -> OperatorRecommendation:
    return OperatorRecommendation(
        recommendation_id="rec-test",
        status=status,
        summary="Recommend pump operation at 1800 RPM." if rpm else "No pump-operation change is recommended.",
        recommended_pump_rpm=rpm,
        selected_intent_ids=("intent-a", "intent-b"),
        rationale=("Effective pump envelope is 1800-3000 RPM.",),
        constraints=("Minimum required pump speed: 1800 RPM.",),
        expected_effect="Use the lowest feasible RPM.",
        confidence="deterministic",
    )


def test_daily_metrics_are_time_weighted_and_mode_specific() -> None:
    start = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=8)
    records = (
        event("e0", start, **{"pump.rpm": 0, "pump.power": 0, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 80.0, "spa.temperature": 80.0, "solar.temperature": 88.0, "air.temperature": 70.0}),
        event("e1", start + timedelta(hours=1), **{"pump.rpm": 1800, "pump.power": 900, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 81.0, "spa.temperature": 80.0, "solar.temperature": 90.0, "air.temperature": 72.0}),
        event("e2", start + timedelta(hours=3), **{"pump.rpm": 2400, "pump.power": 1400, "pool.active": True, "spa.active": False, "solar.active": True, "heater.active": False, "pool.temperature": 82.0, "spa.temperature": 80.0, "solar.temperature": 96.0, "air.temperature": 76.0}),
        event("e3", start + timedelta(hours=4), **{"pump.rpm": 1800, "pump.power": 900, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 83.0, "spa.temperature": 80.0, "solar.temperature": 92.0, "air.temperature": 78.0}),
        event("e4", start + timedelta(hours=5), **{"pump.rpm": 0, "pump.power": 0, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 83.0, "spa.temperature": 80.0, "solar.temperature": 90.0, "air.temperature": 79.0}),
        event("e5", start + timedelta(hours=5, minutes=30), **{"pump.rpm": 1800, "pump.power": 900, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 83.0, "spa.temperature": 80.0, "solar.temperature": 90.0, "air.temperature": 79.0}),
        event("e6", start + timedelta(hours=6), **{"pump.rpm": 2500, "pump.power": 1500, "pool.active": False, "spa.active": True, "solar.active": False, "heater.active": True, "pool.temperature": 83.0, "spa.temperature": 96.0, "solar.temperature": 90.0, "air.temperature": 78.0}),
        event("e7", start + timedelta(hours=7), **{"pump.rpm": 1800, "pump.power": 900, "pool.active": True, "spa.active": False, "solar.active": False, "heater.active": False, "pool.temperature": 82.0, "spa.temperature": 98.0, "solar.temperature": 88.0, "air.temperature": 75.0}),
    )
    engine = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(hours=24))
    report = engine.generate(records, window_start=start, window_end=end, report_date="2026-08-08", complete_day=True)
    actual = report.actual
    assert actual.pump_runtime_seconds == 6.5 * 3600
    assert actual.runtime_by_mode_seconds["FILTERING"] == 4.5 * 3600
    assert actual.runtime_by_mode_seconds["SOLAR_ASSIST"] == 1 * 3600
    assert actual.runtime_by_mode_seconds["SPA"] == 1 * 3600
    assert actual.solar_runtime_seconds == 3600
    assert actual.spa_runtime_seconds == 3600
    assert actual.heater_runtime_seconds == 3600
    assert actual.filtration_interruptions == 1
    assert actual.average_running_rpm is not None
    assert round(actual.average_running_rpm, 1) == 2000.0
    assert actual.pump_energy_kwh is not None
    assert round(actual.pump_energy_kwh, 2) == 6.95
    assert actual.temperatures["pool.temperature"].minimum_f == 80.0
    assert actual.temperatures["pool.temperature"].maximum_f == 83.0
    assert actual.coverage_ratio == 1.0


def test_missing_rpm_is_not_counted_as_running_or_weighted() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    records = (
        event("missing", start, **{"pool.active": True}),
        event("running", start + timedelta(minutes=5), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(minutes=10)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=10),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.pump_runtime_seconds == 5 * 60
    assert report.actual.average_running_rpm == 1800.0


def test_priming_count_and_duration_come_from_explainable_113c_inference() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    records = (
        event("off", start, **{"pump.rpm": 0, "pool.active": True}),
        event("peak", start + timedelta(seconds=30), **{"pump.rpm": 3000, "pool.active": True}),
        event("settle", start + timedelta(minutes=2), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(hours=1)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=10),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.priming_count == 1
    assert report.actual.inferred_priming_duration_seconds == 90.0
    assert report.actual.runtime_by_mode_seconds["PRIMING"] == 90.0
    assert sum(report.actual.runtime_by_mode_seconds.values()) == report.actual.pump_runtime_seconds


def test_no_advisory_evidence_does_not_invent_counterfactual() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    report = DailyOperationalRetrospectiveEngine().generate(
        (event("a", start, **{"pump.rpm": 1800, "pool.active": True}),),
        window_start=start,
        window_end=start + timedelta(minutes=5),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.counterfactual.status is CounterfactualStatus.NOT_AVAILABLE
    assert report.counterfactual.exact_differences == ()
    assert "does not encode a daily runtime target" in report.counterfactual.limitations[0]
    assert report.to_dict()["authority"] == "none"
    assert report.to_dict()["command_delivery_enabled"] is False


def test_counterfactual_reports_exact_supported_rpm_difference() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(hours=1)).generate(
        (event("a", start, **{"pump.rpm": 2100, "pool.active": True}),),
        window_start=start,
        window_end=start + timedelta(minutes=30),
        report_date="2026-08-08",
        recommendation=recommendation(rpm=1800),
        complete_day=False,
    )
    assert report.counterfactual.status is CounterfactualStatus.CHANGE_RECOMMENDED
    difference = report.counterfactual.exact_differences[0]
    assert difference.code == "average_running_rpm"
    assert difference.actual == 2100.0
    assert difference.counterfactual == 1800.0
    assert difference.delta == -300.0
    assert report.counterfactual.selected_intent_ids == ("intent-a", "intent-b")
    assert report.counterfactual.rationale
    assert report.counterfactual.constraints
    assert report.counterfactual.expected_effect == "Use the lowest feasible RPM."
    assert report.counterfactual.confidence == "deterministic"


def test_no_action_recommendation_is_reported_without_fabricated_difference() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    report = DailyOperationalRetrospectiveEngine().generate(
        (event("a", start, **{"pump.rpm": 1800, "pool.active": True}),),
        window_start=start,
        window_end=start + timedelta(minutes=5),
        report_date="2026-08-08",
        recommendation=recommendation(rpm=None, status=OperatorRecommendationStatus.NO_ACTION),
        complete_day=False,
    )
    assert report.counterfactual.status is CounterfactualStatus.NO_CHANGE_RECOMMENDED
    assert report.counterfactual.exact_differences == ()


def test_large_recording_gap_is_not_extrapolated_as_observed_runtime() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    records = (
        event("a", start, **{"pump.rpm": 1800, "pool.active": True}),
        event("b", start + timedelta(hours=2), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(minutes=15)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(hours=3),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.evidence_coverage_seconds == 30 * 60
    assert report.actual.pump_runtime_seconds == 30 * 60
    assert round(report.actual.coverage_ratio, 3) == 0.167


def test_pre_window_record_seeds_midnight_without_becoming_a_daily_event() -> None:
    start = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    records = (
        event("seed", start - timedelta(minutes=5), **{"pump.rpm": 1800, "pool.active": True}),
        event("next", start + timedelta(minutes=5), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(minutes=15)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=10),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.pump_runtime_seconds == 10 * 60
    assert "seed" in report.actual.source_event_ids


def test_report_identity_and_serialization_are_deterministic() -> None:
    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    records = (event("a", start, **{"pump.rpm": 1800, "pool.active": True}),)
    engine = DailyOperationalRetrospectiveEngine()
    left = engine.generate(records, window_start=start, window_end=start + timedelta(minutes=5), report_date="2026-08-08", complete_day=False)
    right = engine.generate(records, window_start=start, window_end=start + timedelta(minutes=5), report_date="2026-08-08", complete_day=False)
    assert left.report_id == right.report_id
    assert left.to_dict() == right.to_dict()


def test_recommendation_recorder_canonicalizes_equivalent_instants_to_utc(tmp_path) -> None:
    from datetime import timezone

    from poolos.daily_retrospective import PersistentRecommendationRecorder

    local = datetime(2026, 8, 8, 5, 0, tzinfo=timezone(timedelta(hours=-7)))
    recorder = PersistentRecommendationRecorder(tmp_path)
    assert recorder.record(recommendation(rpm=1800), published_at=local) is True

    records = recorder.query(
        start=datetime(2026, 8, 8, 11, 59, tzinfo=UTC),
        end=datetime(2026, 8, 8, 12, 1, tzinfo=UTC),
    )
    assert len(records) == 1
    assert records[0].published_at == datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    assert list(tmp_path.glob("recommendations-*.jsonl"))[0].name == "recommendations-2026-08-08.jsonl"


def test_recommendation_history_persists_and_reloads_across_recorder_instances(tmp_path) -> None:
    from poolos.daily_retrospective import PersistentRecommendationRecorder

    at = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    writer = PersistentRecommendationRecorder(tmp_path)
    rec = recommendation(rpm=1800)
    assert writer.record(rec, published_at=at) is True
    assert writer.record(rec, published_at=at + timedelta(minutes=5)) is False

    reader = PersistentRecommendationRecorder(tmp_path)
    records = reader.query(start=at - timedelta(minutes=1), end=at + timedelta(hours=1))
    assert len(records) == 1
    assert records[0].recommendation == rec
    assert records[0].published_at == at
    assert records[0].event_id


def test_recommendation_recorder_does_not_duplicate_unchanged_state_after_restart(tmp_path) -> None:
    from poolos.daily_retrospective import PersistentRecommendationRecorder

    at = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    rec = recommendation(rpm=1800)
    assert PersistentRecommendationRecorder(tmp_path).record(rec, published_at=at) is True

    restarted = PersistentRecommendationRecorder(tmp_path)
    assert restarted.record(rec, published_at=at + timedelta(minutes=5)) is False
    records = restarted.query(start=at - timedelta(minutes=1), end=at + timedelta(hours=1))
    assert len(records) == 1


def test_daily_counterfactual_uses_latest_persisted_advisory_and_preserves_provenance(tmp_path) -> None:
    from poolos.daily_retrospective import PersistentRecommendationRecorder

    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    recorder = PersistentRecommendationRecorder(tmp_path)
    first = recommendation(rpm=2200)
    second = OperatorRecommendation(
        recommendation_id="rec-second",
        status=OperatorRecommendationStatus.RECOMMENDED,
        summary="Recommend pump operation at 1800 RPM.",
        recommended_pump_rpm=1800,
        selected_intent_ids=("intent-a",),
        rationale=("Lower feasible target.",),
        constraints=("Minimum required pump speed: 1800 RPM.",),
        expected_effect="Reduce pump energy while satisfying the selected intent.",
        confidence="deterministic",
    )
    assert recorder.record(first, published_at=start + timedelta(minutes=5)) is True
    assert recorder.record(second, published_at=start + timedelta(minutes=15)) is True
    advisories = recorder.query(start=start, end=start + timedelta(hours=1))

    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(hours=1)).generate(
        (event("actual", start, **{"pump.rpm": 2100, "pool.active": True}),),
        window_start=start,
        window_end=start + timedelta(minutes=30),
        report_date="2026-08-08",
        advisories=advisories,
        complete_day=False,
    )
    assert report.counterfactual.advisory_count == 2
    assert report.counterfactual.recommendation_id == "rec-second"
    assert report.counterfactual.recommendation_published_at == start + timedelta(minutes=15)
    assert report.counterfactual.advisory_event_ids == tuple(item.event_id for item in advisories)
    assert report.counterfactual.exact_differences[0].delta == -300.0


def test_cleared_recommendation_is_persisted_and_prevents_stale_counterfactual(tmp_path) -> None:
    from poolos.daily_retrospective import PersistentRecommendationRecorder

    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    recorder = PersistentRecommendationRecorder(tmp_path)
    rec = recommendation(rpm=1800)
    assert recorder.record(rec, published_at=start + timedelta(minutes=5)) is True
    assert recorder.record(None, published_at=start + timedelta(minutes=20)) is True
    advisories = recorder.query(start=start, end=start + timedelta(hours=1))
    assert len(advisories) == 2
    assert advisories[-1].recommendation is None

    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(hours=1)).generate(
        (event("actual", start, **{"pump.rpm": 2100, "pool.active": True}),),
        window_start=start,
        window_end=start + timedelta(minutes=30),
        report_date="2026-08-08",
        advisories=advisories,
        complete_day=False,
    )
    assert report.counterfactual.status is CounterfactualStatus.NOT_AVAILABLE
    assert report.counterfactual.recommendation_id is None
    assert report.counterfactual.advisory_count == 2
    assert "cleared the active recommendation" in report.counterfactual.summary


def test_stale_pre_window_seed_is_not_extrapolated_into_new_day() -> None:
    start = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    records = (
        event("stale", start - timedelta(hours=2), **{"pump.rpm": 1800, "pool.active": True}),
        event("fresh", start + timedelta(minutes=10), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(minutes=15)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=20),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.pump_runtime_seconds == 10 * 60
    assert "stale" not in report.actual.source_event_ids
    assert report.actual.source_event_ids == ("fresh",)


def test_filtration_interruption_can_begin_after_midnight_from_seeded_running_state() -> None:
    start = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    records = (
        event("seed", start - timedelta(minutes=5), **{"pump.rpm": 1800, "pool.active": True}),
        event("stop", start + timedelta(minutes=2), **{"pump.rpm": 0, "pool.active": True}),
        event("resume", start + timedelta(minutes=7), **{"pump.rpm": 1800, "pool.active": True}),
    )
    report = DailyOperationalRetrospectiveEngine(maximum_evidence_gap=timedelta(minutes=15)).generate(
        records,
        window_start=start,
        window_end=start + timedelta(minutes=10),
        report_date="2026-08-08",
        complete_day=False,
    )
    assert report.actual.filtration_interruptions == 1


def test_cleared_recommendation_event_serializes_without_error(tmp_path) -> None:
    from poolos.daily_retrospective import PersistentRecommendationRecorder

    start = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    recorder = PersistentRecommendationRecorder(tmp_path)
    assert recorder.record(recommendation(rpm=1800), published_at=start) is True
    assert recorder.record(None, published_at=start + timedelta(minutes=1)) is True
    cleared = recorder.query(start=start, end=start + timedelta(hours=1))[-1]
    assert cleared.to_dict()["recommendation"] is None
