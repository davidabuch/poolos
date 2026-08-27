"""Regression contract for low-latency PoolOS Control Center publication."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "poolos" / "coordinator.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_event_observations_publish_before_durable_recording() -> None:
    source = _source()

    early_publish = source.index(
        'if trigger in {'
        '\n            "state_change_event",'
        '\n            "native_intellicenter_update",'
    )

    publish = source.index(
        "self.async_set_updated_data(snapshot)",
        early_publish,
    )

    durable_record = source.index(
        "self.observation_recorder.record_snapshot",
        publish,
    )

    assert publish < durable_record


def test_periodic_reconciliation_is_not_early_published() -> None:
    source = _source()

    block_start = source.index('if trigger in {')
    block_end = source.index("health = {", block_start)
    block = source[block_start:block_end]

    assert '"state_change_event"' in block
    assert '"native_intellicenter_update"' in block
    assert '"periodic_reconciliation"' not in block


def test_durable_observation_recording_remains_present() -> None:
    source = _source()

    assert "self.observation_recorder.record_snapshot" in source
    assert "self._async_schedule_analysis(snapshot.generated_at)" in source
