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


def test_cold_start_defers_reactive_poolos_background_work_until_ha_started() -> None:
    init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    first_refresh = init_source.index(
        "await coordinator.async_config_entry_first_refresh()"
    )
    platforms = init_source.index(
        "await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)"
    )
    startup_branch = init_source.index("if hass.is_running:")

    assert first_refresh < platforms < startup_branch
    assert "EVENT_HOMEASSISTANT_STARTED" in init_source
    assert "async_handle_homeassistant_started" in init_source
    assert "await async_activate_poolos_post_start()" in init_source

    cold_setup = init_source[first_refresh:startup_branch]
    assert "coordinator.async_start_event_observation()" not in cold_setup
    assert "coordinator.async_start_independent_intellicenter()" not in cold_setup

    schedule = coordinator.split(
        "def _async_schedule_analysis", 1
    )[1].split(
        "async def _async_analysis_worker", 1
    )[0]
    assert "self._analysis_dirty = True" in schedule
    assert "self._async_start_analysis_if_ready()" in schedule
    assert "not self._post_start_active" in schedule


def test_post_start_activation_starts_deferred_poolos_facilities_once() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    body = coordinator.split(
        "def async_activate_post_start", 1
    )[1].split(
        "async def async_handle_homeassistant_started", 1
    )[0]

    assert "if self._unloading or self._post_start_active:" in body
    assert "self._post_start_active = True" in body
    assert "self.async_start_event_observation()" in body
    assert "self.async_start_independent_intellicenter()" in body
    assert "self._async_start_analysis_if_ready()" in body
    assert "self._async_start_native_intellicenter_refresh_if_ready()" in body


def test_running_reload_activates_without_waiting_for_started_event() -> None:
    init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")

    branch = init_source.split("if hass.is_running:", 1)[1].split(
        "return True", 1
    )[0]

    assert "await async_activate_poolos_post_start()" in branch
    assert "EVENT_HOMEASSISTANT_STARTED" in branch


def test_startup_analysis_coalescing_preserves_latest_request() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    schedule = coordinator.split(
        "def _async_schedule_analysis", 1
    )[1].split(
        "def _async_start_analysis_if_ready", 1
    )[0]

    assert "recorded_at > self._analysis_requested_at" in schedule
    assert "self._analysis_requested_at = recorded_at" in schedule
    assert "self._analysis_dirty = True" in schedule

    worker = coordinator.split(
        "async def _async_analysis_worker", 1
    )[1].split(
        "async def async_stop_independent_intellicenter", 1
    )[0]

    assert "recorded_at = self._analysis_requested_at" in worker
    assert "while self._analysis_dirty:" in worker


def test_unload_prevents_deferred_post_start_work_from_starting() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    unload = coordinator.split(
        "async def async_prepare_unload", 1
    )[1].split(
        "async def async_handle_homeassistant_stop", 1
    )[0]

    activation = coordinator.split(
        "def async_activate_post_start", 1
    )[1].split(
        "async def async_handle_homeassistant_started", 1
    )[0]

    assert "self._unloading = True" in unload
    assert "self._post_start_active = False" in unload
    assert "if self._unloading or self._post_start_active:" in activation


def test_native_snapshot_propagation_is_deferred_during_cold_start() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    schedule = coordinator.split(
        "def _async_schedule_native_intellicenter_refresh", 1
    )[1].split(
        "def _publish_latest_native_intellicenter_snapshot", 1
    )[0]

    assert "self._native_intellicenter_refresh_dirty = True" in schedule
    assert "if not self._post_start_active:" in schedule
    assert "PoolOS native IntelliCenter snapshot propagation" in schedule



def test_home_assistant_stop_quiesces_poolos_before_final_shutdown() -> None:
    init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "EVENT_HOMEASSISTANT_STOP" in init_source
    assert "hass.bus.async_listen_once(" in init_source
    assert "coordinator.async_handle_homeassistant_stop" in init_source
    assert "async def async_handle_homeassistant_stop" in coordinator
    stop_body = coordinator.split(
        "async def async_handle_homeassistant_stop", 1
    )[1].split("async def _async_mapped_state_changed", 1)[0]
    assert "await self.async_prepare_unload()" in stop_body


def test_commissioning_append_is_flushed_to_disk_before_return() -> None:
    source = (ROOT / "poolos" / "native_parity_commissioning.py").read_text(
        encoding="utf-8"
    )
    append_body = source.split("def _append_history", 1)[1].split(
        "def _rewrite_history", 1
    )[0]
    assert "handle.flush()" in append_body
    assert "os.fsync(handle.fileno())" in append_body
