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
    assert (COMPONENT / "button.py").is_file()
    assert DASHBOARD.is_file()
    assert (ROOT / "docs" / "adr" / "ADR-077-poolos-control-center.md").is_file()


def test_sensor_module_parses_and_declares_read_only_diagnostics() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    ast.parse(source)
    for key in (
        "operating_mode", "commissioning_stage", "observation_health",
        "health_incident_since_restart",
        "observation_quality", "observation_coverage", "observation_incidents_today",
        "solar_transitions_today", "solar_learning_quality",
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


def test_integration_forwards_only_control_center_platforms() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ("sensor", "binary_sensor", "button", "climate", "switch", "light", "number", "select")' in const
    assert "async_forward_entry_setups(entry, PLATFORMS)" in init
    assert "async_unload_platforms(entry, PLATFORMS)" in init


def test_manifest_advances_control_center_version() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.1"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.1",
        "pyintellicenter==0.1.20",
    ]


def test_dashboard_is_valid_and_read_only() -> None:
    dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["title"] == "PoolOS Operations Center"
    text = DASHBOARD.read_text(encoding="utf-8")
    for entity in (
        "sensor.poolos_control_center_operating_mode", "sensor.poolos_control_center_commissioning_stage",
        "sensor.poolos_control_center_observation_health", "sensor.poolos_control_center_health_incident_since_restart",
        "sensor.poolos_control_center_observation_quality",
        "sensor.poolos_control_center_observation_coverage",
        "sensor.poolos_control_center_observation_incidents_today",
        "sensor.poolos_control_center_shadow_runtime_status",
        "sensor.poolos_control_center_last_evaluation", "sensor.poolos_control_center_current_shadow_objective",
        "sensor.poolos_control_center_last_shadow_plan", "sensor.poolos_control_center_inferred_operating_state",
        "sensor.poolos_control_center_solar_behavior_inference",
        "sensor.poolos_control_center_solar_transitions_today",
        "sensor.poolos_control_center_solar_learning_quality",
        "sensor.poolos_control_center_daily_operational_retrospective",
        "sensor.poolos_control_center_daily_counterfactual_report",
        "sensor.poolos_control_center_operator_recommendation", "sensor.poolos_control_center_last_shadow_explanation",
        "sensor.poolos_control_center_grid_available", "sensor.poolos_control_center_grid_outage_active",
        "sensor.poolos_control_center_pool_light_active", "sensor.poolos_control_center_pool_light_color_mode",
        "sensor.poolos_control_center_pool_light_scene_effect",
    ):
        assert entity in text
    assert "button.poolos_control_center_reset_health_incident" in text
    assert "perform_action: button.press" in text
    for prohibited in ("switch.", "service:"):
        assert prohibited not in text
    assert "sensor.poolos_observation_health" not in text
    assert "sensor.poolos_pump_rpm" not in text


def test_control_center_adds_no_equipment_actuating_platform() -> None:
    prohibited = {"services.yaml"}
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
    assert "evaluate_durable_health_confirmation" in coordinator
    assert "self._update_durable_health_confirmation(snapshot" in coordinator
    assert 'def health_incident_diagnostics' in coordinator
    assert '"last_unhealthy_at"' in coordinator
    assert '"last_unhealthy_missing_required"' in coordinator
    assert '"last_unhealthy_unavailable_entities"' in coordinator
    assert '"health_incident_since_restart"' in sensor
    assert '"UNHEALTHY SEEN"' in sensor
    assert 'else "NO INCIDENTS"' in sensor
    assert "sensor.poolos_control_center_health_incident_since_restart" in dashboard


def test_startup_health_grace_suppresses_transient_incident_latching() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")

    assert "STARTUP_HEALTH_GRACE = timedelta(seconds=60)" in const
    assert "self._startup_health_grace_until" in coordinator
    assert "def in_startup_health_grace" in coordinator
    assert "def observation_health_state" in coordinator
    assert 'return "INITIALIZING"' in coordinator
    assert "in_startup_grace=self.in_startup_health_grace(observed_at)" in coordinator
    assert "startup_grace_active" in sensor


def test_health_incident_latch_has_non_actuating_manual_reset() -> None:
    button = (COMPONENT / "button.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    assert "def reset_health_incident_latch" in coordinator
    assert 'self.observation_health_state() != "HEALTHY"' in coordinator
    assert "self._unhealthy_seen_since_start = False" in coordinator
    assert '"tracking_since"' in coordinator
    assert "PoolOSResetHealthIncidentButton" in button
    assert "self.coordinator.reset_health_incident_latch()" in button
    assert "services.async_call" not in button
    assert "button.poolos_control_center_reset_health_incident" in dashboard
    assert "Health Incident Since Reset" in dashboard


def test_dashboard_uses_concise_operator_facing_entity_names() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")
    for label in (
        "name: Pool Temperature",
        "name: Pool Target",
        "name: Spa Temperature",
        "name: Spa Target",
        "name: Water Temperature",
        "name: Solar Roof Temperature",
        "name: Air Temperature",
        "name: Solar Active",
        "name: Gas Heater",
        "name: Pool Heating Demand",
        "name: Spa Heating Demand",
        "name: Waterfall",
        "name: Jets",
        "name: Slide",
        "name: RPM",
        "name: Power",
    ):
        assert label in text

    # Dashboard aliases should prevent long generated friendly names from
    # obscuring the useful part of labels in cards and graph legends.
    assert "name: PoolOS Control Center" not in text

def test_recorder_facing_diagnostics_do_not_embed_bulk_evidence() -> None:
    """HA sensor attributes stay summaries; durable stores retain full evidence."""

    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")

    quality = source.split("def _quality_attributes(", 1)[1]
    quality = quality.split("def _incidents_attributes(", 1)[0]
    assert "startup_evidence_ids" not in quality
    assert "source_evidence_ids" not in quality
    assert "soak_quality.to_dict()" not in quality

    retrospective = source.split("def _retrospective_attributes(", 1)[1]
    retrospective = retrospective.split("def _quality_attributes(", 1)[0]
    assert '"soak_quality": data["soak_quality"]' not in retrospective
    assert '"incidents": data["incidents"]' not in retrospective
    assert '"solar_learning": data["solar_learning"]' not in retrospective
    assert '"incident_count"' in retrospective
    assert '"solar_learning_quality"' in retrospective
