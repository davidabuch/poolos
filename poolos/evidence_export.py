"""Human-accessible daily evidence exports for PoolOS commissioning."""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from poolos.observations import PersistentObservationRecorder, RecordedObservationEvent

CSV_FIELDS = (
    "recorded_at", "local_time", "event_kind", "changed_observation_ids", "observation_healthy",
    "pool.active", "spa.active", "pool.command_active", "spa.command_active",
    "pump.rpm", "pump.gpm", "pump.power", "pool.temperature", "pool.target_temperature",
    "spa.temperature", "spa.target_temperature", "water.temperature", "solar.temperature",
    "air.temperature", "solar.active", "heater.active", "pool.heating_demand_active",
    "spa.heating_demand_active", "solar_preferred.active", "waterfall.active", "jets.active", "slide.active",
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
        self.root.mkdir(parents=True, exist_ok=True)
        stem = f"poolos_{local_date.isoformat()}"
        self._write_jsonl(self.root / f"{stem}.jsonl", records)
        self._write_csv(self.root / f"{stem}.csv", records)
        self.last_exported_at = recorded_at
        self.last_error = None
        self.exports_written += 1

    def _write_jsonl(self, path: Path, records: tuple[RecordedObservationEvent, ...]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                payload = {
                    "event_id": record.event_id,
                    "recorded_at": record.recorded_at.isoformat(),
                    "local_time": record.recorded_at.astimezone(self.timezone).isoformat(),
                    "kind": record.kind,
                    "changed_observation_ids": list(record.changed_observation_ids),
                    "observations": list(record.observations),
                    "health": record.health,
                }
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def _write_csv(self, path: Path, records: tuple[RecordedObservationEvent, ...]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                values = {item["observation_id"]: item.get("value") for item in record.observations}
                row = {
                    "recorded_at": record.recorded_at.isoformat(),
                    "local_time": record.recorded_at.astimezone(self.timezone).isoformat(),
                    "event_kind": record.kind,
                    "changed_observation_ids": ";".join(record.changed_observation_ids),
                    "observation_healthy": record.health.get("healthy"),
                    **values,
                }
                writer.writerow(row)

    def diagnostics(self) -> dict[str, object]:
        return {
            "export_directory": str(self.root),
            "exports_written_this_runtime": self.exports_written,
            "last_exported_at": self.last_exported_at.isoformat() if self.last_exported_at else None,
            "last_error": self.last_error,
        }
