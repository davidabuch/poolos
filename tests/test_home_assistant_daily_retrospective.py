"""Home Assistant commissioning contracts for 11.3D daily retrospectives."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_113d_core_tests_and_adr_exist() -> None:
    assert (ROOT / "poolos" / "daily_retrospective.py").is_file()
    assert (ROOT / "tests" / "test_daily_retrospective.py").is_file()
    assert (ROOT / "docs" / "adr" / "ADR-086-daily-operational-retrospective-counterfactual-report.md").is_file()


def test_manifest_advances_to_090_and_matching_core_tag() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.9.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.9.0"
    ]
    assert manifest["iot_class"] == "calculated"


def test_retrospective_runs_from_durable_history_off_event_loop() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "DailyOperationalRetrospectiveEngine" in source
    assert "current_daily_retrospective" in source
    assert "latest_completed_daily_retrospective" in source
    assert "self._record_infer_and_retro" in source
    assert "async_add_executor_job" in source
    assert "self.observation_recorder.query" in source
    assert "PersistentRecommendationRecorder" in source
    assert "self.recommendation_recorder.query" in source
    assert "self.recommendation_recorder.record" in source
    assert "ZoneInfo(hass.config.time_zone)" in source
    assert '"current_daily_retrospective": (' in source
    assert '"latest_completed_daily_retrospective": (' in source
    assert '"persistent_recommendation_recorder": self.recommendation_recorder.diagnostics()' in source


def test_counterfactual_uses_only_window_scoped_recommendation_evidence() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "operator_recommendation_published_at" in source
    assert "_recommendation_for_window" in source
    assert "start <= published_at < end" in source


def test_control_center_exposes_daily_actual_and_counterfactual_read_only() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    assert '"daily_operational_retrospective"' in source
    assert '"daily_counterfactual_report"' in source
    assert "pump_runtime_seconds" in source
    assert "runtime_by_mode_seconds" in source
    assert "pump_energy_kwh" in source
    assert "exact_differences" not in source or "counterfactual.to_dict" in source
    dashboard = (ROOT / "dashboards" / "poolos_control_center.yaml").read_text(encoding="utf-8")
    assert "sensor.poolos_daily_operational_retrospective" in dashboard
    assert "sensor.poolos_daily_counterfactual_report" in dashboard
    assert "No actuation occurs" in dashboard


def test_retrospective_language_refuses_unsupported_daily_differences() -> None:
    source = (ROOT / "poolos" / "daily_retrospective.py").read_text(encoding="utf-8")
    assert "does not encode a daily runtime target" in source
    assert "those differences are not invented" in source
    assert "only differences directly supported" in source


def test_113d_preserves_no_actuation_boundary() -> None:
    prohibited = (
        "hass.services.async_call",
        "hass.services.call",
        "services.async_register",
        "switch.turn_on",
        "switch.turn_off",
        "climate.set_hvac_mode",
        "climate.turn_on",
        "climate.turn_off",
    )
    for path in COMPONENT.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert all(token not in source for token in prohibited), path.name
    core = (ROOT / "poolos" / "daily_retrospective.py").read_text(encoding="utf-8").lower()
    assert "command_delivery_enabled\": false" in core
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert '"command_delivery_enabled": False' in coordinator


def test_component_python_still_parses() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_roadmap_marks_113d_done_and_commissioning_is_next_decision() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.3D | Daily operational retrospective + counterfactual report | DONE |" in roadmap
    assert "### Epic 11.3D — Daily Operational Retrospective + Counterfactual Report" in roadmap
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    assert '"11.3A", "11.3B", "11.3C", "11.3D"' in sensor
    assert 'lambda coordinator, runtime: "PRE_INSTALL_READY"' in sensor
    assert '"next_stage": "HA_COMMISSIONING_DECISION"' in sensor
