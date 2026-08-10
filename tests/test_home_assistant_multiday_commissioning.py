"""Read-only Home Assistant contracts for milestone 11.6."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
DASHBOARD = ROOT / "dashboards" / "poolos_control_center.yaml"


def test_multiday_core_and_architecture_documents_exist() -> None:
    assert (ROOT / "poolos" / "multiday_commissioning.py").is_file()
    assert (ROOT / "tests" / "test_multiday_commissioning.py").is_file()
    assert (
        ROOT
        / "docs"
        / "adr"
        / "ADR-089-multiday-commissioning-intelligence.md"
    ).is_file()


def test_coordinator_rebuilds_completed_daily_reports_off_event_loop() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    constants = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert "MultiDayCommissioningIntelligence" in source
    assert "multiday_commissioning_report" in source
    assert "_completed_retrospective_history" in source
    assert "complete_day=True" in source
    assert "async_add_executor_job" in source
    assert "MULTIDAY_COMMISSIONING_WINDOW_DAYS = 14" in constants
    assert "self._completed_history_for_date == latest_date" in source
    assert "current_daily_retrospective" in source
    assert "start_date=date.fromisoformat(history[0].report_date)" in source
    assert "end_date=date.fromisoformat(history[-1].report_date)" in source


def test_control_center_publishes_only_four_concise_read_only_diagnostics() -> None:
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    yaml.safe_load(dashboard)

    for key in (
        "commissioning_evidence_status",
        "good_observation_days",
        "usable_solar_learning_days",
        "complete_solar_episodes",
    ):
        assert f'"{key}"' in sensor
    for entity_id in (
        "sensor.poolos_control_center_commissioning_evidence_status",
        "sensor.poolos_control_center_good_observation_days",
        "sensor.poolos_control_center_usable_solar_learning_days",
        "sensor.poolos_control_center_complete_solar_episodes",
    ):
        assert entity_id in dashboard
    assert "_multiday_commissioning_attributes" in sensor
    assert "_multiday_count_attributes" in sensor
    assert '"policy_created": False' in sensor


def test_multiday_publication_adds_no_action_service_or_authority() -> None:
    for relative in (
        "custom_components/poolos/coordinator.py",
        "custom_components/poolos/sensor.py",
        "poolos/multiday_commissioning.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        for prohibited in (
            "hass.services.async_call",
            "services.async_register",
            "switch.turn_on",
            "climate.set_hvac_mode",
            "requests.get",
            "socket.",
        ):
            assert prohibited not in source
    core = (ROOT / "poolos" / "multiday_commissioning.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(core)
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("homeassistant" in item or "vendor" in item for item in imports)
    assert '"authority": "none"' in core
    assert '"policy_created": False' in core
    assert '"command_delivery_enabled": False' in core
