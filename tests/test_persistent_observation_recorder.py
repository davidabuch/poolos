"""Persistent observation recorder contracts for milestone 11.3B."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    ObservationRetentionPolicy,
    PersistentObservationRecorder,
    PoolObservation,
)


def obs(observation_id: str, value: object, at: datetime) -> PoolObservation:
    return PoolObservation(
        observation_id=observation_id,
        value=value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"sensor.{observation_id.replace('.', '_')}",
        quality=ObservationQuality.GOOD,
    )


def health(healthy: bool = True) -> dict[str, object]:
    return {"healthy": healthy, "missing_required": [], "unavailable_entities": [], "stale_entities": []}


def test_records_baseline_then_suppresses_unchanged_poll(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    observations = (obs("pool.active", False, now), obs("pump.rpm", 0, now))
    assert recorder.record_snapshot(recorded_at=now, observations=observations, health=health())
    assert not recorder.record_snapshot(recorded_at=now + timedelta(seconds=30), observations=observations, health=health())
    events = recorder.query(start=now - timedelta(seconds=1), end=now + timedelta(minutes=1))
    assert len(events) == 1
    assert events[0].kind == "baseline"
    assert events[0].changed_observation_ids == ("pool.active", "pump.rpm")


def test_records_boolean_and_rpm_transition_immediately(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=now, observations=(obs("pool.active", False, now), obs("pump.rpm", 0, now)), health=health())
    later = now + timedelta(seconds=30)
    assert recorder.record_snapshot(recorded_at=later, observations=(obs("pool.active", True, later), obs("pump.rpm", 2500, later)), health=health())
    events = recorder.query(start=now, end=later + timedelta(seconds=1))
    assert events[-1].kind == "transition"
    assert events[-1].changed_observation_ids == ("pool.active", "pump.rpm")


def test_small_numeric_noise_waits_for_checkpoint(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=now, observations=(obs("pump.power", 1000.0, now),), health=health())
    assert not recorder.record_snapshot(recorded_at=now + timedelta(minutes=1), observations=(obs("pump.power", 1020.0, now + timedelta(minutes=1)),), health=health())
    checkpoint = now + timedelta(minutes=5)
    assert recorder.record_snapshot(recorded_at=checkpoint, observations=(obs("pump.power", 1020.0, checkpoint),), health=health())
    events = recorder.query(start=now, end=checkpoint + timedelta(seconds=1))
    assert [event.kind for event in events] == ["baseline", "checkpoint"]


def test_health_transition_is_durable_without_value_change(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    observations = (obs("pool.active", False, now),)
    recorder.record_snapshot(recorded_at=now, observations=observations, health=health())
    assert recorder.record_snapshot(recorded_at=now + timedelta(seconds=30), observations=observations, health=health(False))
    events = recorder.query(start=now, end=now + timedelta(minutes=1))
    assert events[-1].kind == "health_transition"


def test_restart_writes_new_baseline_and_preserves_prior_history(tmp_path: Path) -> None:
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    first = PersistentObservationRecorder(tmp_path)
    first.record_snapshot(recorded_at=now, observations=(obs("pool.active", True, now),), health=health())
    second = PersistentObservationRecorder(tmp_path)
    second.record_snapshot(recorded_at=now + timedelta(minutes=1), observations=(obs("pool.active", True, now + timedelta(minutes=1)),), health=health())
    events = second.query(start=now, end=now + timedelta(minutes=2))
    assert [event.kind for event in events] == ["baseline", "baseline"]
    assert events[0].event_id != events[1].event_id


def test_retention_prunes_whole_utc_day_files(tmp_path: Path) -> None:
    policy = ObservationRetentionPolicy(retention_days=2)
    recorder = PersistentObservationRecorder(tmp_path, retention=policy)
    old = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=old, observations=(obs("pool.active", False, old),), health=health())
    recorder = PersistentObservationRecorder(tmp_path, retention=policy)
    new = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=new, observations=(obs("pool.active", False, new),), health=health())
    assert not (tmp_path / "observations-2026-08-05.jsonl").exists()
    assert (tmp_path / "observations-2026-08-07.jsonl").exists()


def test_event_identity_is_deterministic_for_same_payload(tmp_path: Path) -> None:
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    left = PersistentObservationRecorder(tmp_path / "left")
    right = PersistentObservationRecorder(tmp_path / "right")
    observations = (obs("solar.active", True, now),)
    left.record_snapshot(recorded_at=now, observations=observations, health=health())
    right.record_snapshot(recorded_at=now, observations=observations, health=health())
    left_event = left.query(start=now, end=now + timedelta(seconds=1))[0]
    right_event = right.query(start=now, end=now + timedelta(seconds=1))[0]
    assert left_event.event_id == right_event.event_id


def test_jsonl_preserves_raw_observation_provenance(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=now, observations=(obs("solar.active", True, now),), health=health())
    payload = json.loads((tmp_path / "observations-2026-08-07.jsonl").read_text().strip())
    stored = payload["observations"][0]
    assert stored["observation_id"] == "solar.active"
    assert stored["source_kind"] == "live"
    assert stored["source_id"] == "sensor.solar_active"
    assert stored["quality"] == "good"
    assert stored["observed_at"] == now.isoformat()


def test_gpm_noise_is_bounded_but_meaningful_flow_transition_is_immediate(tmp_path: Path) -> None:
    recorder = PersistentObservationRecorder(tmp_path)
    now = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    recorder.record_snapshot(recorded_at=now, observations=(obs("pump.gpm", 40.0, now),), health=health())
    quiet = now + timedelta(seconds=1)
    assert not recorder.record_snapshot(
        recorded_at=quiet,
        observations=(obs("pump.gpm", 40.4, quiet),),
        health=health(),
    )
    changed = now + timedelta(seconds=2)
    assert recorder.record_snapshot(
        recorded_at=changed,
        observations=(obs("pump.gpm", 42.0, changed),),
        health=health(),
    )
    events = recorder.query(start=now, end=changed + timedelta(seconds=1))
    assert [event.kind for event in events] == ["baseline", "transition"]
    assert events[-1].changed_observation_ids == ("pump.gpm",)
