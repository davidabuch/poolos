"""Contract tests for the PoolOS read-only Control Center."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
DASHBOARD = ROOT / "dashboards" / "poolos_control_center.yaml"


def test_control_center_files_exist() -> None:
    assert (COMPONENT / "sensor.py").is_file()
    assert DASHBOARD.is_file()
    assert (ROOT / "docs" / "adr" / "ADR-077-poolos-control-center.md").is_file()


def test_sensor_module_parses_and_declares_read_only_diagnostics() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    ast.parse(source)
    for key in (
        "operating_mode", "commissioning_stage", "observation_health",
        "shadow_runtime_status", "last_evaluation", "last_plan",
        "current_objective", "inferred_operating_state", "solar_behavior_inference",
        "daily_operational_retrospective", "daily_counterfactual_report",
        "operator_recommendation", "last_explanation",
    ):
        assert f'"{key}"' in source
    assert "EntityCategory.DIAGNOSTIC" in source
    assert "command_delivery_enabled" in source


def test_integration_forwards_only_sensor_platform() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ("sensor",)' in const
    assert "async_forward_entry_setups(entry, PLATFORMS)" in init
    assert "async_unload_platforms(entry, PLATFORMS)" in init


def test_manifest_advances_control_center_version() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0"
    ]


def test_dashboard_is_valid_and_read_only() -> None:
    dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["title"] == "PoolOS Control Center"
    text = DASHBOARD.read_text(encoding="utf-8")
    for entity in (
        "sensor.poolos_operating_mode", "sensor.poolos_commissioning_stage",
        "sensor.poolos_observation_health", "sensor.poolos_shadow_runtime_status",
        "sensor.poolos_last_evaluation", "sensor.poolos_current_objective",
        "sensor.poolos_last_plan", "sensor.poolos_inferred_operating_state",
        "sensor.poolos_solar_behavior_inference",
        "sensor.poolos_daily_operational_retrospective",
        "sensor.poolos_daily_counterfactual_report",
        "sensor.poolos_operator_recommendation", "sensor.poolos_last_explanation",
    ):
        assert entity in text
    for prohibited in ("button.", "switch.", "service:", "tap_action:"):
        assert prohibited not in text


def test_control_center_adds_no_actuating_platform() -> None:
    prohibited = {"switch.py", "button.py", "number.py", "select.py", "climate.py", "services.yaml"}
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_roadmap_records_11_1e_done() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.1E | Operator shadow diagnostics and dashboard | DONE |" in roadmap
    assert "### Epic 11.1E — PoolOS Control Center" in roadmap
