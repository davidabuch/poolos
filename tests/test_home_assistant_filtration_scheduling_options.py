"""Regression contract for filtration scheduling options."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "custom_components" / "poolos" / "config_flow.py"


def test_both_filtration_time_controls_remain_on_options_form() -> None:
    source = FLOW.read_text(encoding="utf-8")
    mapping = source.split(
        "def _mapping_schema(current: dict[str, Any]) -> vol.Schema:", 1
    )[1]

    assert "CONF_FILTRATION_SCHEDULING_MODE" in mapping
    assert "CONF_PREFERRED_FILTRATION_CATCHUP_START" in mapping
    assert "CONF_TRADITIONAL_FILTRATION_START" in mapping
    assert mapping.count("selector.TimeSelector()") >= 2


def test_options_flow_saves_from_single_form() -> None:
    source = FLOW.read_text(encoding="utf-8")

    options = source.split("class PoolOSOptionsFlow", 1)[1].split(
        "def _entity_selector", 1
    )[0]
    assert "async_step_filtration_schedule" not in options
    assert "return self.async_create_entry(data=user_input)" in options
