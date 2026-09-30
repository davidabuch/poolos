"""Regression contract for conditional filtration scheduling options."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "custom_components" / "poolos" / "config_flow.py"


def test_filtration_start_times_are_not_simultaneously_editable() -> None:
    source = FLOW.read_text(encoding="utf-8")

    mapping = source.split(
        "def _mapping_schema(current: dict[str, Any]) -> vol.Schema:", 1
    )[1]
    assert "CONF_FILTRATION_SCHEDULING_MODE" in mapping
    assert "CONF_PREFERRED_FILTRATION_CATCHUP_START" not in mapping
    assert "CONF_TRADITIONAL_FILTRATION_START" not in mapping

    schedule = source.split(
        "def _filtration_schedule_schema(", 1
    )[1].split(
        "def _mapping_schema(", 1
    )[0]
    assert 'if mode == "traditional_time_based":' in schedule
    assert "CONF_TRADITIONAL_FILTRATION_START" in schedule
    assert "CONF_PREFERRED_FILTRATION_CATCHUP_START" in schedule


def test_both_config_and_options_flows_use_conditional_schedule_step() -> None:
    source = FLOW.read_text(encoding="utf-8")

    assert source.count("async def async_step_filtration_schedule(") == 2
    assert source.count("data_schema=_filtration_schedule_schema(pending, mode)") == 2
    assert "self._pending_options = {**dict(self.config_entry.options), **user_input}" in source
