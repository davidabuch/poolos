"""Durable append-only observation history for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..expected_outage import ExpectedOutageAcknowledgment
from .model import PoolObservation

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ObservationRetentionPolicy:
    """Bound durable history by age while preserving recent evidence."""

    retention_days: int = 35
    checkpoint_interval: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if self.retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        if self.checkpoint_interval <= timedelta(0):
            raise ValueError("checkpoint_interval must be positive")


@dataclass(frozen=True, slots=True)
class ObservationSignificancePolicy:
    """Decide when a value change is large enough for an immediate record."""

    numeric_thresholds: Mapping[str, float] = field(
        default_factory=lambda: {
            "pump.rpm": 25.0,
            "pump.gpm": 1.0,
            "pool.temperature": 0.1,
            "spa.temperature": 0.1,
            "water.temperature": 0.1,
            "pool.target_temperature": 0.1,
            "spa.target_temperature": 0.1,
            "solar.temperature": 0.1,
            "air.temperature": 0.1,
            "pump.power": 50.0,
        }
    )

    def __post_init__(self) -> None:
        normalized = {str(key): float(value) for key, value in self.numeric_thresholds.items()}
        if any(value <= 0 or not math.isfinite(value) for value in normalized.values()):
            raise ValueError("numeric significance thresholds must be finite and positive")
        object.__setattr__(self, "numeric_thresholds", MappingProxyType(dict(sorted(normalized.items()))))

    def is_significant(self, previous: PoolObservation, current: PoolObservation) -> bool:
        if _metadata_fingerprint(previous) != _metadata_fingerprint(current):
            return True
        if previous.value == current.value:
            return False
        if isinstance(previous.value, bool) or isinstance(current.value, bool):
            return True
        threshold = self.numeric_thresholds.get(current.observation_id)
        if threshold is None:
            return True
        old = _finite_float(previous.value)
        new = _finite_float(current.value)
        if old is None or new is None:
            return True
        return abs(new - old) >= threshold


@dataclass(frozen=True, slots=True)
class RecordedObservationEvent:
    """One durable evidence record returned by history queries."""

    event_id: str
    recorded_at: datetime
    kind: str
    changed_observation_ids: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    health: dict[str, Any]


class PersistentObservationRecorder:
    """Append restart-safe observation evidence without recording unchanged polls."""

    def __init__(
        self,
        root: Path | str,
        *,
        retention: ObservationRetentionPolicy | None = None,
        significance: ObservationSignificancePolicy | None = None,
    ) -> None:
        self.root = Path(root)
        self.retention = retention or ObservationRetentionPolicy()
        self.significance = significance or ObservationSignificancePolicy()
        self._latest: dict[str, PoolObservation] = {}
        self._last_health: dict[str, Any] | None = None
        self._last_recorded_at: datetime | None = None
        self._started = False
        self._records_written = 0
        self._write_errors = 0
        self._last_error: str | None = None

    def record_snapshot(
        self,
        *,
        recorded_at: datetime,
        observations: Iterable[PoolObservation],
        health: dict[str, Any],
    ) -> bool:
        """Persist a baseline, significant transition, health change, or checkpoint."""

        if recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        current = {item.observation_id: item for item in observations}
        changed = tuple(
            sorted(
                observation_id
                for observation_id, observation in current.items()
                if observation_id not in self._latest
                or self.significance.is_significant(self._latest[observation_id], observation)
            )
        )
        health_changed = self._last_health is not None and health != self._last_health
        checkpoint_due = (
            self._last_recorded_at is not None
            and recorded_at - self._last_recorded_at >= self.retention.checkpoint_interval
        )

        if not self._started:
            kind = "baseline"
            changed = tuple(sorted(current))
        elif changed:
            kind = "transition"
        elif health_changed:
            kind = "health_transition"
        elif checkpoint_due:
            kind = "checkpoint"
        else:
            return False

        payload = {
            "schema_version": SCHEMA_VERSION,
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            "kind": kind,
            "changed_observation_ids": list(changed),
            "observations": [_observation_payload(item) for item in sorted(current.values(), key=lambda item: item.observation_id)],
            "health": _canonical_health(health),
        }
        payload["event_id"] = _event_id(payload)
        try:
            self._append(payload)
            self._prune(recorded_at)
        except OSError as exc:
            self._write_errors += 1
            self._last_error = str(exc)
            raise

        self._started = True
        self._latest = current
        self._last_health = _canonical_health(health)
        self._last_recorded_at = recorded_at
        self._records_written += 1
        self._last_error = None
        return True

    def query(self, *, start: datetime, end: datetime) -> tuple[RecordedObservationEvent, ...]:
        """Return deterministic durable evidence in the half-open ``[start, end)`` window."""

        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("query bounds must be timezone-aware")
        if end <= start:
            raise ValueError("end must be after start")
        records: list[RecordedObservationEvent] = []
        if not self.root.exists():
            return ()
        for path in sorted(self.root.glob("observations-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if payload.get("record_type", "observation") != "observation":
                        continue
                    recorded_at = datetime.fromisoformat(payload["recorded_at"])
                    if start <= recorded_at < end:
                        records.append(_recorded_event(payload))
        return tuple(sorted(records, key=lambda item: (item.recorded_at, item.event_id)))

    def record_expected_outage_acknowledgment(
        self, acknowledgment: ExpectedOutageAcknowledgment
    ) -> bool:
        """Append operator annotation evidence without changing observation state."""

        payload = {
            "record_type": "expected_outage_acknowledgment",
            "recorded_at": acknowledgment.acknowledged_at.astimezone(UTC).isoformat(),
            **acknowledgment.to_dict(),
        }
        try:
            self._append(payload)
            self._prune(acknowledgment.acknowledged_at)
        except OSError as exc:
            self._write_errors += 1
            self._last_error = str(exc)
            raise
        self._records_written += 1
        self._last_error = None
        return True

    def query_expected_outage_acknowledgments(
        self, *, start: datetime, end: datetime
    ) -> tuple[ExpectedOutageAcknowledgment, ...]:
        """Return durable acknowledgments whose matching windows intersect a range."""

        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("query bounds must be timezone-aware")
        if end <= start:
            raise ValueError("end must be after start")
        acknowledgments: dict[str, ExpectedOutageAcknowledgment] = {}
        if not self.root.exists():
            return ()
        for path in sorted(self.root.glob("observations-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if payload.get("record_type") != "expected_outage_acknowledgment":
                        continue
                    acknowledgment = _expected_outage_acknowledgment(payload)
                    if (
                        acknowledgment.matching_window_start <= end
                        and start <= acknowledgment.matching_window_end
                    ):
                        acknowledgments[acknowledgment.acknowledgment_id] = acknowledgment
        return tuple(
            sorted(
                acknowledgments.values(),
                key=lambda item: (item.acknowledged_at, item.acknowledgment_id),
            )
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return recorder health without exposing raw pool values."""

        return {
            "schema_version": SCHEMA_VERSION,
            "retention_days": self.retention.retention_days,
            "checkpoint_minutes": self.retention.checkpoint_interval.total_seconds() / 60.0,
            "records_written_this_runtime": self._records_written,
            "write_errors_this_runtime": self._write_errors,
            "last_recorded_at": self._last_recorded_at.isoformat() if self._last_recorded_at else None,
            "last_error": self._last_error,
        }

    def _append(self, payload: dict[str, Any]) -> None:
        recorded_at = datetime.fromisoformat(payload["recorded_at"])
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"observations-{recorded_at.date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _prune(self, now: datetime) -> None:
        if not self.root.exists():
            return
        cutoff = now.astimezone(UTC).date() - timedelta(days=self.retention.retention_days - 1)
        for path in self.root.glob("observations-*.jsonl"):
            try:
                file_date = datetime.strptime(path.stem.removeprefix("observations-"), "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink(missing_ok=True)


def _observation_payload(observation: PoolObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "value": observation.value,
        "unit": observation.unit,
        "truth_level": observation.truth_level.value,
        "observed_at": observation.observed_at.isoformat() if observation.observed_at else None,
        "source_kind": observation.source_kind.value,
        "source_id": observation.source_id,
        "quality": observation.quality.value,
        "confidence": observation.confidence,
        "evidence": [
            {"description": item.description, "weight": item.weight}
            for item in observation.evidence
        ],
    }


def _metadata_fingerprint(observation: PoolObservation) -> tuple[Any, ...]:
    return (
        observation.unit,
        observation.truth_level.value,
        observation.source_kind.value,
        observation.source_id,
        observation.quality.value,
        observation.confidence,
        tuple((item.description, item.weight) for item in observation.evidence),
    )


def _canonical_health(health: dict[str, Any]) -> dict[str, Any]:
    return json.loads(_canonical_json(health))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _event_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _recorded_event(payload: dict[str, Any]) -> RecordedObservationEvent:
    return RecordedObservationEvent(
        event_id=str(payload["event_id"]),
        recorded_at=datetime.fromisoformat(payload["recorded_at"]),
        kind=str(payload["kind"]),
        changed_observation_ids=tuple(payload["changed_observation_ids"]),
        observations=tuple(payload["observations"]),
        health=dict(payload["health"]),
    )


def _expected_outage_acknowledgment(
    payload: dict[str, Any],
) -> ExpectedOutageAcknowledgment:
    from ..expected_outage import ExpectedOutageClassification, ExpectedOutageSource

    return ExpectedOutageAcknowledgment(
        acknowledgment_id=str(payload["acknowledgment_id"]),
        schema_version=str(payload["schema_version"]),
        acknowledged_at=datetime.fromisoformat(payload["acknowledged_at"]),
        matching_window_start=datetime.fromisoformat(payload["matching_window_start"]),
        matching_window_end=datetime.fromisoformat(payload["matching_window_end"]),
        classification=ExpectedOutageClassification(payload["classification"]),
        source=ExpectedOutageSource(payload["source"]),
        source_id=str(payload["source_id"]),
        reason_code=(
            None if payload.get("reason_code") is None else str(payload["reason_code"])
        ),
    )


__all__ = [
    "ObservationRetentionPolicy",
    "ObservationSignificancePolicy",
    "PersistentObservationRecorder",
    "RecordedObservationEvent",
    "SCHEMA_VERSION",
]
