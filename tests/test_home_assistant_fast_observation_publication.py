"""Regression contract for low-latency PoolOS Control Center publication."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "poolos" / "coordinator.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_event_observations_have_single_caller_owned_publication() -> None:
    source = _source()

    native_start = source.index(
        "async def _async_native_intellicenter_snapshot_updated"
    )
    native_end = source.index("def _async_schedule_analysis", native_start)
    native_worker = source[native_start:native_end]
    assert native_worker.count("self.async_set_updated_data(snapshot)") == 1

    mapped_start = source.index("async def _async_mapped_state_changed")
    mapped_end = source.index("async def _async_observe", mapped_start)
    mapped_worker = source[mapped_start:mapped_end]
    assert mapped_worker.count("self.async_set_updated_data(snapshot)") == 1

    observe_start = source.index("async def _async_observe")
    observe_end = source.index("async def _async_persist_observation", observe_start)
    observe = source[observe_start:observe_end]
    assert "self.async_set_updated_data(snapshot)" not in observe

    # Durable work remains scheduled into PoolOSBackgroundTasks rather than
    # awaited inline, so the caller can publish before persistence executes.
    assert "self.background_tasks.create(" in observe
    assert "self._async_persist_observation(snapshot, observed_at)" in observe


def test_periodic_reconciliation_owns_its_separate_publication_path() -> None:
    source = _source()

    backstop_start = source.index(
        "async def _async_native_reconciliation_backstop_loop"
    )
    backstop_end = source.index(
        "def async_start_independent_intellicenter",
        backstop_start,
    )
    backstop = source[backstop_start:backstop_end]

    assert "snapshot = await self._async_update_data()" in backstop
    assert "self.async_set_updated_data(snapshot)" in backstop

    observe_start = source.index("async def _async_observe")
    observe_end = source.index("async def _async_persist_observation", observe_start)
    observe = source[observe_start:observe_end]
    assert '"periodic_reconciliation"' not in observe


def test_durable_observation_recording_remains_present() -> None:
    source = _source()

    assert "self.observation_recorder.record_snapshot" in source
    assert "self._async_schedule_analysis(snapshot.generated_at)" in source
