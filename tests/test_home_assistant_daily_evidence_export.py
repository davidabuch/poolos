from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from poolos.evidence_export import CSV_FIELDS, DailyEvidenceExporter
from poolos.expected_outage import ExpectedOutageAcknowledgment
from poolos.observations import PersistentObservationRecorder
from tests.test_persistent_observation_recorder import obs


def test_daily_export_writes_easy_jsonl_and_csv(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path / "storage")
    exporter = DailyEvidenceExporter(tmp_path / "poolos_logs", ZoneInfo("America/Los_Angeles"))
    now = datetime(2026, 8, 8, 16, 0, tzinfo=UTC)
    assert recorder.record_snapshot(recorded_at=now, observations=(obs("pump.rpm", 1500, now),), health={"healthy": True})
    exporter.export_day(recorder, now)
    jsonl = tmp_path / "poolos_logs" / "poolos_2026-08-08.jsonl"
    csv_path = tmp_path / "poolos_logs" / "poolos_2026-08-08.csv"
    assert jsonl.is_file() and csv_path.is_file()
    payload = json.loads(jsonl.read_text().splitlines()[0])
    assert payload["kind"] == "baseline"
    assert payload["local_time"].startswith("2026-08-08T09:00:00")
    header = csv_path.read_text().splitlines()[0].split(",")
    assert header == list(CSV_FIELDS)
    assert "1500" in csv_path.read_text()
    assert "grid.available" in header
    assert "grid.outage_active" in header
    assert "pool_light.active" in header
    assert "pool_light.color_mode" in header
    assert "pool_light.effect" in header
    assert "missing_required" in header
    assert "unavailable_entities" in header
    assert "stale_entities" in header


def test_export_diagnostics_expose_operator_path(tmp_path: Path) -> None:
    exporter = DailyEvidenceExporter(tmp_path / "poolos_logs", ZoneInfo("UTC"))
    diagnostics = exporter.diagnostics()
    assert diagnostics["export_directory"].endswith("poolos_logs")
    assert diagnostics["exports_written_this_runtime"] == 0


def test_daily_export_preserves_expected_outage_annotation_metadata(
    tmp_path: Path,
) -> None:
    recorder = PersistentObservationRecorder(tmp_path / "storage")
    exporter = DailyEvidenceExporter(tmp_path / "poolos_logs", ZoneInfo("UTC"))
    now = datetime(2026, 8, 9, 9, 15, tzinfo=UTC)
    acknowledgment = ExpectedOutageAcknowledgment.create(
        acknowledged_at=now,
        source_id="home_assistant:test-entry",
    )
    recorder.record_expected_outage_acknowledgment(acknowledgment)
    exporter.export_day(recorder, now)

    jsonl = tmp_path / "poolos_logs" / "poolos_2026-08-09.jsonl"
    payload = json.loads(jsonl.read_text().splitlines()[0])
    assert payload["record_type"] == "expected_outage_acknowledgment"
    assert payload["acknowledgment_id"] == acknowledgment.acknowledgment_id
    assert payload["matching_window_start"] == acknowledgment.matching_window_start.isoformat()
    csv_text = (tmp_path / "poolos_logs" / "poolos_2026-08-09.csv").read_text()
    assert "EXPECTED_OUTAGE" in csv_text
    assert acknowledgment.acknowledgment_id in csv_text
