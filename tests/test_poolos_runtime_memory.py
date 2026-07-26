from datetime import datetime, timedelta, timezone

import pytest

from poolos.clock import FixedClock
from poolos.runtime_memory import MemorySample, RuntimeMemory


def make_memory(retention=3):
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    return RuntimeMemory(clock=FixedClock(now), retention_per_metric=retention)


def test_observe_and_summary():
    memory = make_memory()
    for value in (10, 20, 30):
        memory.observe("pump.prime_seconds", value)
    summary = memory.summary("pump.prime_seconds")
    assert summary.count == 3
    assert summary.mean == 20
    assert summary.median == 20
    assert summary.percentile_95 == 30


def test_retention_is_bounded_per_metric():
    memory = make_memory(retention=2)
    for value in (1, 2, 3):
        memory.observe("metric", value)
    assert [sample.value for sample in memory.samples("metric")] == [2, 3]


def test_recommended_delay_uses_p95_after_minimum_history():
    memory = make_memory(retention=10)
    default = timedelta(seconds=60)
    assert memory.recommended_delay("heater.ignition_seconds", default) == default
    for value in (20, 24, 30):
        memory.observe("heater.ignition_seconds", value)
    assert memory.recommended_delay(
        "heater.ignition_seconds", default, safety_factor=1.5
    ) == timedelta(seconds=45)


def test_snapshot_and_restore_preserve_samples():
    memory = make_memory(retention=10)
    memory.observe("valve.move_seconds", 12, tags={"valve": "spa"})
    restored = make_memory(retention=10)
    restored.restore(sample for values in memory.snapshot().values() for sample in values)
    assert restored.samples("valve.move_seconds") == memory.samples("valve.move_seconds")


def test_invalid_configuration_and_naive_timestamp_are_rejected():
    with pytest.raises(ValueError):
        RuntimeMemory(retention_per_metric=0)
    with pytest.raises(ValueError):
        MemorySample("x", 1, datetime(2026, 1, 1))
