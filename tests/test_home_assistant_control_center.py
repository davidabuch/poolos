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
        "health_incident_since_restart",
        "shadow_runtime_status", "last_evaluation", "last_plan",
        "current_objective", "inferred_operating_state", "solar_behavior_inference",
        "daily_operational_retrospective", "daily_counterfactual_report",
        "operator_recommendation", "recorder_status", "last_explanation",
    ):
        assert f'"{key}"' in source
    assert "EntityCategory.DIAGNOSTIC" in source
    assert "command_delivery_enabled" in source


def test_observation_health_exposes_actionable_snapshot_diagnostics() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    for field in (
        '"healthy"',
        '"missing_required"',
        '"unavailable_entities"',
        '"stale_entities"',
        '"diagnostic_reason"',
    ):
        assert field in source
    assert 'diagnostics.get("issues", [])' not in source


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
    assert dashboard["title"] == "PoolOS Operations Center"
    text = DASHBOARD.read_text(encoding="utf-8")
    for entity in (
        "sensor.poolos_control_center_operating_mode", "sensor.poolos_control_center_commissioning_stage",
        "sensor.poolos_control_center_observation_health", "sensor.poolos_control_center_health_incident_since_restart",
        "sensor.poolos_control_center_shadow_runtime_status",
        "sensor.poolos_control_center_last_evaluation", "sensor.poolos_control_center_current_shadow_objective",
        "sensor.poolos_control_center_last_shadow_plan", "sensor.poolos_control_center_inferred_operating_state",
        "sensor.poolos_control_center_solar_behavior_inference",
        "sensor.poolos_control_center_daily_operational_retrospective",
        "sensor.poolos_control_center_daily_counterfactual_report",
        "sensor.poolos_control_center_operator_recommendation", "sensor.poolos_control_center_last_shadow_explanation",
        "sensor.poolos_control_center_grid_available", "sensor.poolos_control_center_grid_outage_active",
        "sensor.poolos_control_center_pool_light_active", "sensor.poolos_control_center_pool_light_color_mode",
        "sensor.poolos_control_center_pool_light_scene_effect",
    ):
        assert entity in text
    for prohibited in ("button.", "switch.", "service:", "tap_action:"):
        assert prohibited not in text
    assert "sensor.poolos_observation_health" not in text
    assert "sensor.poolos_pump_rpm" not in text


def test_control_center_adds_no_actuating_platform() -> None:
    prohibited = {"switch.py", "button.py", "number.py", "select.py", "climate.py", "services.yaml"}
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_roadmap_records_11_1e_done() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.1E | Operator shadow diagnostics and dashboard | DONE |" in roadmap
    assert "### Epic 11.1E — PoolOS Control Center" in roadmap


def test_dashboard_explains_future_powerwall_conservation_without_actuation() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")
    assert "Grid & Resilience" in text
    assert "1800 RPM" in text
    assert "observation-only" in text


def test_control_center_normalizes_boolean_and_pool_light_display_values() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    assert "def _display_observation_value" in source
    assert 'return "ON" if value else "OFF"' in source
    assert 'observation_id in {"pool_light.color_mode", "pool_light.effect"}' in source
    assert 'if light_active is False:' in source
    assert 'return "OFF"' in source
    assert '_display_observation_value(coordinator, observation_id)' in source


def test_health_incident_since_restart_is_latched_and_diagnostic() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    assert 'self._unhealthy_seen_since_start = False' in coordinator
    assert 'if not snapshot.healthy:' in coordinator
    assert 'self._unhealthy_seen_since_start = True' in coordinator
    assert 'def health_incident_diagnostics' in coordinator
    assert '"last_unhealthy_at"' in coordinator
    assert '"last_unhealthy_missing_required"' in coordinator
    assert '"last_unhealthy_unavailable_entities"' in coordinator
    assert '"health_incident_since_restart"' in sensor
    assert '"UNHEALTHY SEEN"' in sensor
    assert 'else "OK"' in sensor
    assert "sensor.poolos_control_center_health_incident_since_restart" in dashboard
