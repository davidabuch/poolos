"""Sustained native parity commissioning tests for milestone 12.0C3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from poolos.native_parity_commissioning import (
    NativeParityCommissioningStatus,
    NativeParityCommissioningStore,
)
from poolos.observation_parity import ObservationParityEngine
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _observation(
    concept: str,
    value: object,
    at: datetime,
    *,
    native: bool,
) -> PoolObservation:
    return PoolObservation(
        observation_id=concept,
        value=value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=("intellicenter_native:panel:" if native else "home_assistant:sensor.")
        + concept,
        quality=ObservationQuality.GOOD,
    )


def _report(
    at: datetime,
    *,
    ha_value: object = 101.0,
    native_value: object = 101.0,
    native_available: bool = True,
):
    ha = (_observation("solar.temperature", ha_value, at, native=False),)
    native = (
        (_observation("solar.temperature", native_value, at, native=True),)
        if native_available
        else ()
    )
    return ObservationParityEngine().compare(
        ha,
        native,
        generated_at=at,
        ha_source_available=True,
        native_source_available=native_available,
        ha_sampled_at_by_concept={"solar.temperature": at},
    )


def _record(
    store: NativeParityCommissioningStore,
    at: datetime,
    *,
    ha_value: object = 101.0,
    native_value: object = 101.0,
    available: bool = True,
    reconnects: int = 0,
    generation: int = 1,
):
    return store.record(
        _report(
            at,
            ha_value=ha_value,
            native_value=native_value,
            native_available=available,
        ),
        transport_state="AVAILABLE" if available else "UNAVAILABLE",
        reconnect_count=reconnects,
        discovery_generation=generation,
    )


def test_cycle_persists_and_restart_recovers_equivalent_summary(tmp_path) -> None:
    root = tmp_path / "poolos_logs"
    store = NativeParityCommissioningStore(root)
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1), ha_value=101.0, native_value=100.0)
    before = store.summary()

    recovered = NativeParityCommissioningStore(root)

    assert recovered.records == store.records
    assert recovered.summary() == before
    assert recovered.summary().total_comparison_cycles == 2
    history = root / "native_parity_history.jsonl"
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2
    assert json.loads((root / "native_parity_commissioning.json").read_text())["authority"] == "none"


def test_corrupt_history_fails_closed_then_repairs_with_new_valid_evidence(
    tmp_path,
) -> None:
    root = tmp_path / "poolos_logs"
    root.mkdir()
    history = root / "native_parity_history.jsonl"
    history.write_text(
        '{"stale_or_corrupt_secret":"must-not-survive"}\nnot-json\n',
        encoding="utf-8",
    )

    store = NativeParityCommissioningStore(root)

    # Corrupt historical evidence is rejected completely, while persistence
    # remains available so a subsequent valid cycle can self-heal the store.
    assert store.records == ()
    assert store.persistence_available is True
    assert store.last_error == "native parity commissioning history is corrupt"

    summary = _record(store, NOW)

    assert summary.total_comparison_cycles == 1
    assert summary.status is NativeParityCommissioningStatus.COLLECTING
    assert store.last_error is None

    repaired_text = history.read_text(encoding="utf-8")
    assert "must-not-survive" not in repaired_text
    assert "not-json" not in repaired_text
    assert len(repaired_text.splitlines()) == 1

    # A fresh process/reload must recover only the newly established clean
    # commissioning evidence.
    recovered = NativeParityCommissioningStore(root)

    assert recovered.last_error is None
    assert recovered.persistence_available is True
    assert recovered.records == store.records
    assert recovered.summary().total_comparison_cycles == 1


def test_write_failure_is_isolated_and_keeps_in_memory_evidence(tmp_path, monkeypatch) -> None:
    store = NativeParityCommissioningStore(tmp_path)

    def fail(_record):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "_append_history", fail)
    summary = _record(store, NOW)

    assert summary.total_comparison_cycles == 1
    assert store.last_error == "native parity commissioning persistence failed"

    monkeypatch.undo()
    _record(store, NOW + timedelta(minutes=1))
    recovered = NativeParityCommissioningStore(tmp_path)
    assert recovered.summary().total_comparison_cycles == 2


def test_retention_covers_target_and_removes_old_records(tmp_path) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(hours=1),
        retention=timedelta(hours=2),
        maximum_records=4,
        maximum_continuous_gap=timedelta(hours=1),
    )
    for hours in range(6):
        _record(store, NOW + timedelta(hours=hours))

    assert len(store.records) == 3
    assert store.records[0].generated_at == NOW + timedelta(hours=3)
    assert store.records[-1].generated_at == NOW + timedelta(hours=5)


def test_72_hour_continuous_window_reconstructs_as_ready_for_review(tmp_path) -> None:
    store = NativeParityCommissioningStore(tmp_path)
    for interval in range(865):
        _record(store, NOW + timedelta(minutes=5 * interval))

    recovered = NativeParityCommissioningStore(tmp_path)
    summary = recovered.summary()

    assert summary.minimum_duration_reached is True
    assert summary.continuous_evidence_seconds == 72 * 3600
    assert summary.progress_percent == 100.0
    assert summary.status is NativeParityCommissioningStatus.READY_FOR_REVIEW
    assert summary.total_comparison_cycles == 865


def test_review_status_is_duration_only_then_degraded_by_persistent_evidence(
    tmp_path,
) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(minutes=2),
    )
    _record(store, NOW)
    collecting = _record(store, NOW + timedelta(minutes=1))
    _record(store, NOW + timedelta(minutes=2), native_value=100.0)
    _record(store, NOW + timedelta(minutes=3), native_value=100.0)
    degraded = _record(store, NOW + timedelta(minutes=4), native_value=100.0)

    assert collecting.status is NativeParityCommissioningStatus.INSUFFICIENT_DURATION
    assert degraded.minimum_duration_reached is True
    assert degraded.status is NativeParityCommissioningStatus.DEGRADED
    assert degraded.persistent_mismatch_concepts == ("solar.temperature",)


def test_per_concept_mismatch_runs_and_numeric_delta_metrics(tmp_path) -> None:
    store = NativeParityCommissioningStore(tmp_path)
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1), native_value=100.0)
    _record(store, NOW + timedelta(minutes=2), native_value=99.0)
    summary = _record(store, NOW + timedelta(minutes=3), native_value=100.4)
    statistic = summary.concept_statistics[0]

    assert statistic.observation_count == 4
    assert statistic.match_count == 1
    assert statistic.value_mismatch_count == 3
    assert statistic.current_consecutive_mismatch_count == 3
    assert statistic.longest_consecutive_mismatch_count == 3
    assert statistic.current_mismatch_duration_seconds == 120.0
    assert statistic.longest_mismatch_duration_seconds == 120.0
    assert statistic.seconds_since_last_match == 180.0
    assert statistic.current_absolute_delta == 0.6
    assert statistic.maximum_absolute_delta == 2.0
    assert statistic.average_absolute_delta == 1.2
    assert summary.persistent_mismatch_concepts == ("solar.temperature",)


def test_nonnumeric_mismatch_has_no_numeric_delta(tmp_path) -> None:
    store = NativeParityCommissioningStore(tmp_path)
    summary = _record(store, NOW, ha_value="enabled", native_value="disabled")
    statistic = summary.concept_statistics[0]

    assert statistic.value_mismatch_count == 1
    assert statistic.current_absolute_delta is None
    assert statistic.maximum_absolute_delta is None
    assert statistic.average_absolute_delta is None


def test_all_parity_failure_statuses_are_accounted(tmp_path) -> None:
    old = NOW - timedelta(minutes=6)
    ha = (
        _observation("pool.active", True, NOW, native=False),
        _observation("solar.temperature", 10.0, NOW, native=False),
        _observation("pool.raw_htmode", True, NOW, native=False),
        _observation("pump.rpm", 1, NOW, native=False),
        _observation("water.temperature", 1, NOW, native=False),
        _observation("air.temperature", 1, old, native=False),
    )
    native = (
        _observation("pool.active", True, NOW, native=True),
        _observation("solar.temperature", 12.0, NOW, native=True),
        _observation("pool.raw_htmode", "on", NOW, native=True),
        _observation("pump.gpm", 1, NOW, native=True),
        _observation("water.temperature", 1, old, native=True),
        _observation("air.temperature", 1, NOW, native=True),
    )
    report = ObservationParityEngine().compare(
        ha,
        native,
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
        ha_sampled_at_by_concept={
            item.observation_id: NOW
            for item in ha
            if item.observation_id != "air.temperature"
        },
    )
    store = NativeParityCommissioningStore(tmp_path)
    store.persistence_available = False
    summary = store.record(
        report,
        transport_state="AVAILABLE",
        reconnect_count=0,
        discovery_generation=1,
    )

    assert summary.status_totals == {
        "MATCH": 1,
        "MISSING_HA": 1,
        "MISSING_NATIVE": 1,
        "STALE_HA": 1,
        "STALE_NATIVE": 1,
        "TYPE_MISMATCH": 1,
        "VALUE_MISMATCH": 1,
    }


def test_transport_stability_and_continuity_evidence(tmp_path) -> None:
    store = NativeParityCommissioningStore(tmp_path)
    _record(store, NOW, reconnects=0, generation=1)
    _record(store, NOW + timedelta(minutes=1), reconnects=2, generation=2)
    _record(store, NOW + timedelta(minutes=2), available=False, reconnects=2, generation=2)
    summary = _record(
        store,
        NOW + timedelta(minutes=10),
        reconnects=0,
        generation=1,
    )

    assert summary.reconnect_events_observed == 2
    assert summary.discovery_generation_changes == 2
    assert summary.transport_unavailable_cycles == 1
    assert summary.maximum_evidence_gap_seconds == 480.0
    assert summary.continuous_evidence_seconds == 0.0


def test_diagnostics_are_bounded_privacy_safe_and_non_authoritative(tmp_path) -> None:
    store = NativeParityCommissioningStore(tmp_path)
    _record(store, NOW, native_value=100.0)
    diagnostics = store.diagnostics()
    encoded = json.dumps(diagnostics, sort_keys=True)
    history = store.history_path.read_text(encoding="utf-8").lower()
    summary = store.summary_path.read_text(encoding="utf-8").lower()

    assert len(encoded.encode("utf-8")) < 8_000
    assert "concept_statistics" not in diagnostics
    assert "details" not in diagnostics
    assert diagnostics["authority"] == "none"
    assert diagnostics["command_delivery_enabled"] is False
    assert diagnostics["read_only_safety_mode"] is True
    for sensitive in (
        "192.168.",
        "host",
        "address",
        "email",
        "phone",
        "password",
        "token",
        "coordinates",
    ):
        assert sensitive not in history
        assert sensitive not in summary


def test_non_intellicenter_concepts_are_not_persisted_as_failures(tmp_path) -> None:
    report = ObservationParityEngine().compare(
        (
            _observation("grid.available", True, NOW, native=False),
            _observation("solar.temperature", 101.0, NOW, native=False),
        ),
        (_observation("solar.temperature", 101.0, NOW, native=True),),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
        ha_sampled_at_by_concept={"grid.available": NOW, "solar.temperature": NOW},
    )
    store = NativeParityCommissioningStore(tmp_path)
    summary = store.record(
        report,
        transport_state="AVAILABLE",
        reconnect_count=0,
        discovery_generation=1,
    )

    assert summary.total_concept_comparisons == 1
    assert "grid.available" not in store.history_path.read_text(encoding="utf-8")


def test_production_commissioning_path_has_no_control_or_network_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8").lower()
        for path in (
            "poolos/native_parity_commissioning.py",
            "custom_components/poolos/coordinator.py",
            "custom_components/poolos/sensor.py",
        )
    )
    for prohibited in (
        "hass.services",
        "async_call",
        "turn_on",
        "turn_off",
        "set_temperature",
        "set_speed",
        "send_command",
        "write_command",
        "socket.",
        ".send(",
    ):
        assert prohibited not in source

def test_out_of_order_evidence_rewrites_chronologically_and_survives_restart(
    tmp_path,
) -> None:
    root = tmp_path / "poolos_logs"
    store = NativeParityCommissioningStore(root)
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=2))
    _record(store, NOW + timedelta(minutes=1))

    generated = [
        json.loads(line)["generated_at"]
        for line in (root / "native_parity_history.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert generated == sorted(generated)

    recovered = NativeParityCommissioningStore(root)
    assert recovered.last_error is None
    assert len(recovered.records) == 3
    assert recovered.records == store.records


def test_incomplete_trailing_append_preserves_valid_prefix_and_repairs(
    tmp_path,
) -> None:
    root = tmp_path / "poolos_logs"
    store = NativeParityCommissioningStore(root)
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1))

    history = root / "native_parity_history.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":1')

    recovered = NativeParityCommissioningStore(root)
    assert len(recovered.records) == 2
    assert recovered.last_error == (
        "native parity commissioning history had incomplete trailing record"
    )

    _record(recovered, NOW + timedelta(minutes=2))
    assert recovered.last_error is None
    repaired = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert len(repaired) == 3
    assert [item["generated_at"] for item in repaired] == sorted(
        item["generated_at"] for item in repaired
    )

def test_transient_incomplete_cycle_within_gap_preserves_continuity(tmp_path) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(minutes=10),
        maximum_continuous_gap=timedelta(minutes=5),
    )
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1))
    _record(store, NOW + timedelta(minutes=2), available=False)
    summary = _record(store, NOW + timedelta(minutes=3))

    assert summary.continuous_evidence_seconds == 3 * 60
    assert summary.transport_unavailable_cycles == 1


def test_incomplete_run_longer_than_gap_resets_on_recovery(tmp_path) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(minutes=10),
        maximum_continuous_gap=timedelta(minutes=5),
    )
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1))
    _record(store, NOW + timedelta(minutes=3), available=False)
    _record(store, NOW + timedelta(minutes=5), available=False)
    summary = _record(store, NOW + timedelta(minutes=7))

    assert summary.continuous_evidence_seconds == 0


def test_current_incomplete_cycle_within_gap_holds_continuity(tmp_path) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(minutes=10),
        maximum_continuous_gap=timedelta(minutes=5),
    )
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=2))
    summary = _record(store, NOW + timedelta(minutes=4), available=False)

    assert summary.continuous_evidence_seconds == 4 * 60


def test_current_incomplete_run_beyond_gap_breaks_continuity(tmp_path) -> None:
    store = NativeParityCommissioningStore(
        tmp_path,
        target_duration=timedelta(minutes=10),
        maximum_continuous_gap=timedelta(minutes=5),
    )
    _record(store, NOW)
    _record(store, NOW + timedelta(minutes=1))
    _record(store, NOW + timedelta(minutes=4), available=False)
    summary = _record(store, NOW + timedelta(minutes=7), available=False)

    assert summary.continuous_evidence_seconds == 0
