"""Regression contracts for optional pump-flow telemetry."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_pump_gpm_mapping_is_optional_but_supported() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")

    required = const.split("REQUIRED_ENTITY_OPTIONS = (", 1)[1].split(")", 1)[0]
    optional = const.split("OPTIONAL_ENTITY_OPTIONS = (", 1)[1].split(")", 1)[0]
    assert "CONF_PUMP_GPM_ENTITY" not in required
    assert "CONF_PUMP_GPM_ENTITY" in optional

    required_flow = flow.split("required = {", 1)[1].split("optional = {", 1)[0]
    optional_flow = flow.split("optional = {", 1)[1].split("fields:", 1)[0]
    assert "CONF_PUMP_GPM_ENTITY" not in required_flow
    assert 'CONF_PUMP_GPM_ENTITY: ["sensor"]' in optional_flow

    gpm_line = next(
        line for line in observation.splitlines()
        if "CONF_PUMP_GPM_ENTITY" in line and "EntityMappingSpec" in line
    )
    assert "ObservationConcept.PUMP_GPM" in gpm_line
    assert '"gpm", False' in gpm_line


def test_default_dashboard_omits_gpm_but_keeps_rpm_and_power() -> None:
    dashboard = (ROOT / "dashboards" / "poolos_control_center.yaml").read_text(encoding="utf-8")
    assert "sensor.poolos_control_center_pump_gpm" not in dashboard
    assert "sensor.poolos_control_center_pump_rpm" in dashboard
    assert "sensor.poolos_control_center_pump_power" in dashboard


def test_canonical_pump_gpm_concept_is_retained() -> None:
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert 'PUMP_GPM = "pump.gpm"' in observation
    assert "freshness_required=True" in next(
        line for line in observation.splitlines()
        if "CONF_PUMP_GPM_ENTITY" in line and "EntityMappingSpec" in line
    )
