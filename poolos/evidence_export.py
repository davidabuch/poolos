"""Human-accessible daily evidence exports for PoolOS commissioning."""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from poolos.expected_outage import ExpectedOutageAcknowledgment
from poolos.observations import PersistentObservationRecorder, RecordedObservationEvent

CSV_FIELDS = (
    "record_type", "recorded_at", "local_time", "event_kind", "changed_observation_ids", "observation_healthy",
    "missing_required", "unavailable_entities", "stale_entities",
    "acknowledgment_id", "acknowledged_at", "matching_window_start", "matching_window_end",
    "expected_outage_classification", "annotation_source", "annotation_source_id",
    "pool.active", "spa.active", "pool.command_active", "spa.command_active",
    "pump.rpm", "pump.gpm", "pump.power", "pool.temperature", "pool.target_temperature",
    "spa.temperature", "spa.target_temperature", "water.temperature", "solar.temperature",
    "air.temperature", "solar.active", "heater.active", "pool.heating_demand_active",
    "spa.heating_demand_active", "waterfall.active", "jets.active", "slide.active",
    "grid.available", "grid.outage_active", "pool_light.active", "pool_light.color_mode",
    "pool_light.effect",
)

class DailyEvidenceExporter:
    """Rewrite today's local-day JSONL and flattened CSV after each durable write."""

    def __init__(self, root: Path | str, timezone: ZoneInfo) -> None:
        self.root = Path(root)
        self.timezone = timezone
        self.last_exported_at: datetime | None = None
        self.last_error: str | None = None
        self.exports_written = 0

    def export_day(self, recorder: PersistentObservationRecorder, recorded_at: datetime) -> None:
        local_date = recorded_at.astimezone(self.timezone).date()
        start_local = datetime.combine(local_date, time.min, tzinfo=self.timezone)
        end_local = start_local + timedelta(days=1)
        records = recorder.query(start=start_local, end=end_local)
        acknowledgments = recorder.query_expected_outage_acknowledgments(
            start=start_local,
            end=end_local,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        stem = f"poolos_{local_date.isoformat()}"
        self._write_jsonl(self.root / f"{stem}.jsonl", records, acknowledgments)
        self._write_csv(self.root / f"{stem}.csv", records, acknowledgments)
        self.last_exported_at = recorded_at
        self.last_error = None
        self.exports_written += 1

    def _write_jsonl(
        self,
        path: Path,
        records: tuple[RecordedObservationEvent, ...],
        acknowledgments: tuple[ExpectedOutageAcknowledgment, ...],
    ) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                payload = {
                    "record_type": "observation",
                    "event_id": record.event_id,
                    "recorded_at": record.recorded_at.isoformat(),
                    "local_time": record.recorded_at.astimezone(self.timezone).isoformat(),
                    "kind": record.kind,
                    "changed_observation_ids": list(record.changed_observation_ids),
                    "observations": list(record.observations),
                    "health": record.health,
                }
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            for acknowledgment in acknowledgments:
                payload = {
                    "record_type": "expected_outage_acknowledgment",
                    **acknowledgment.to_dict(),
                }
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def _write_csv(
        self,
        path: Path,
        records: tuple[RecordedObservationEvent, ...],
        acknowledgments: tuple[ExpectedOutageAcknowledgment, ...],
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                values = {item["observation_id"]: item.get("value") for item in record.observations}
                row = {
                    "record_type": "observation",
                    "recorded_at": record.recorded_at.isoformat(),
                    "local_time": record.recorded_at.astimezone(self.timezone).isoformat(),
                    "event_kind": record.kind,
                    "changed_observation_ids": ";".join(record.changed_observation_ids),
                    "observation_healthy": record.health.get("healthy"),
                    "missing_required": ";".join(
                        str(item) for item in record.health.get("missing_required", ())
                    ),
                    "unavailable_entities": ";".join(
                        str(item) for item in record.health.get("unavailable_entities", ())
                    ),
                    "stale_entities": ";".join(
                        str(item) for item in record.health.get("stale_entities", ())
                    ),
                    **values,
                }
                writer.writerow(row)
            for acknowledgment in acknowledgments:
                writer.writerow(
                    {
                        "record_type": "expected_outage_acknowledgment",
                        "recorded_at": acknowledgment.acknowledged_at.isoformat(),
                        "local_time": acknowledgment.acknowledged_at.astimezone(
                            self.timezone
                        ).isoformat(),
                        "event_kind": "operator_annotation",
                        "acknowledgment_id": acknowledgment.acknowledgment_id,
                        "acknowledged_at": acknowledgment.acknowledged_at.isoformat(),
                        "matching_window_start": acknowledgment.matching_window_start.isoformat(),
                        "matching_window_end": acknowledgment.matching_window_end.isoformat(),
                        "expected_outage_classification": acknowledgment.classification.value,
                        "annotation_source": acknowledgment.source.value,
                        "annotation_source_id": acknowledgment.source_id,
                    }
                )

    def diagnostics(self) -> dict[str, object]:
        return {
            "export_directory": str(self.root),
            "exports_written_this_runtime": self.exports_written,
            "last_exported_at": self.last_exported_at.isoformat() if self.last_exported_at else None,
            "last_error": self.last_error,
        }
