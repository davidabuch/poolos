"""Regression contracts for PoolOS HA event-loop and unload safety."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from poolos.native_parity_commissioning import NativeParityCommissioningStore

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_native_parity_store_can_defer_history_io(tmp_path: Path) -> None:
    root = tmp_path / "poolos_logs"
    root.mkdir()
    history = root / "native_parity_history.jsonl"
    history.write_text("not-json\n", encoding="utf-8")

    store = NativeParityCommissioningStore(root, load_history=False)

    assert store.loaded is False
    assert store.records == ()
    assert store.last_error is None

    store.load()

    assert store.loaded is True
    assert store.records == ()
    assert store.last_error == "native parity commissioning history is corrupt"


def test_deferred_store_rejects_record_before_load(tmp_path: Path) -> None:
    store = NativeParityCommissioningStore(tmp_path, load_history=False)
    with pytest.raises(RuntimeError, match="must be loaded before recording"):
        from poolos.observation_parity import ObservationParityEngine

        report = ObservationParityEngine().compare(
            (),
            (),
            generated_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            ha_source_available=True,
            native_source_available=True,
        )
        store.record(
            report,
            transport_state="AVAILABLE",
            reconnect_count=0,
            discovery_generation=1,
        )


def test_ha_setup_loads_parity_history_through_executor_before_first_refresh() -> None:
    init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "load_history=False" in coordinator
    assert "async def async_initialize_persistence" in coordinator
    assert "await self.hass.async_add_executor_job(load_and_summarize)" in coordinator
    assert init_source.index("await coordinator.async_initialize_persistence()") < init_source.index(
        "await coordinator.async_config_entry_first_refresh()"
    )


def test_parity_record_computes_one_post_append_summary() -> None:
    source = (ROOT / "poolos" / "native_parity_commissioning.py").read_text(encoding="utf-8")
    record_body = source[source.index("    def record("):source.index("    def summary(")]
    assert "summary = self.summary()" in record_body
    assert "self._write_summary(summary)" in record_body
    assert "return summary" in record_body
    assert "self._write_summary(self.summary())" not in record_body


def test_unload_stops_new_event_observations_and_waits_for_active_work() -> None:
    init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "async def async_prepare_unload" in coordinator
    assert "self._unloading = True" in coordinator
    assert "self.async_stop_event_observation()" in coordinator
    assert "if self._unloading:\n            return" in coordinator
    assert init_source.index("await entry.runtime_data.coordinator.async_prepare_unload()") < init_source.index(
        "async_unload_platforms"
    )


def test_lifecycle_diagnostics_uses_cached_parity_summary() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "self.native_parity_commissioning_store.diagnostics(\n                    summary=self.native_parity_commissioning_summary" in coordinator
