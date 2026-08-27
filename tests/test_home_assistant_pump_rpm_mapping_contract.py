"""Regression contract for PoolOS actual pump RPM mapping."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_pump_rpm_selector_accepts_sensor_only() -> None:
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    assert 'CONF_PUMP_RPM_ENTITY: ["sensor"],' in source
    assert 'CONF_PUMP_RPM_ENTITY: ["sensor", "number"],' not in source


def test_pool_rpm_number_remains_command_setpoint_not_observation() -> None:
    source = (COMPONENT / "number.py").read_text(encoding="utf-8")

    assert '_attr_name = "Pool RPM"' in source
    assert '"actual_pump_rpm_concept": "pump.rpm"' in source
    assert '"optimistic": False' in source
