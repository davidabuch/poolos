"""Home Assistant safety contracts for expected-outage annotation."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
DASHBOARD = ROOT / "dashboards" / "poolos_control_center.yaml"


def test_expected_outage_button_persists_annotation_without_equipment_service() -> None:
    button = (COMPONENT / "button.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "PoolOSAcknowledgeExpectedOutageButton" in button
    assert '"Acknowledge Expected Pentair Outage"' in button
    assert "await self.coordinator.async_acknowledge_expected_outage()" in button
    assert "record_expected_outage_acknowledgment" in coordinator
    assert "force_analysis=True" in coordinator
    assert "self._completed_history_for_date = None" in coordinator
    for prohibited in (
        "hass.services",
        "services.async_call",
        "turn_on",
        "turn_off",
        "climate.",
        "switch.",
    ):
        assert prohibited not in button.lower()


def test_live_health_and_existing_reset_behavior_remain_separate() -> None:
    button = (COMPONENT / "button.py").read_text(encoding="utf-8")
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "PoolOSResetHealthIncidentButton" in button
    assert "self.coordinator.reset_health_incident_latch()" in button
    assert 'self.observation_health_state() != "HEALTHY"' in coordinator
    annotation_method = coordinator.split("async def async_acknowledge_expected_outage", 1)[1]
    annotation_method = annotation_method.split("def expected_outage_annotation_diagnostics", 1)[0]
    assert "reset_health_incident_latch" not in annotation_method
    assert "_unhealthy_seen_since_start = False" not in annotation_method


def test_diagnostic_sensor_and_dashboard_keep_annotation_and_reset_distinct() -> None:
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    yaml.safe_load(dashboard)

    assert '"expected_outage_annotation"' in sensor
    assert "expected_outage_annotation_diagnostics" in sensor
    assert "sensor.poolos_control_center_expected_outage_annotation" in dashboard
    assert "button.poolos_control_center_acknowledge_expected_pentair_outage" in dashboard
    assert "button.poolos_control_center_reset_health_incident" in dashboard
    assert "Acknowledge Expected Outage" in dashboard
    assert "last_acknowledged_at" in dashboard
    assert "matching_window_start" in dashboard
    assert "matching_window_end" in dashboard
    assert "matched_incident_count" in dashboard
    assert "most_recent_matched_outage_start" in dashboard
    assert "most_recent_matched_outage_end" in dashboard
    assert "Neither button controls Pentair" in dashboard


def test_annotation_modules_add_no_control_network_or_vendor_write_imports() -> None:
    for relative in (
        "poolos/expected_outage.py",
        "poolos/observations/persistent.py",
        "poolos/daily_retrospective.py",
        "custom_components/poolos/button.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        assert not any(
            part in {"requests", "aiohttp", "socket", "vendors", "delivery"}
            for name in names
            for part in name.split(".")
        )
