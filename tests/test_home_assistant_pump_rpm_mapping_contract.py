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


def test_hot_tub_rpm_number_is_body_specific_manual_setpoint() -> None:
    source = (COMPONENT / "number.py").read_text(encoding="utf-8")

    assert "class PoolOSNativeIntelliCenterHotTubRPM" in source
    assert '_attr_name = "Hot Tub RPM"' in source
    assert "body=NativeBodyKind.SPA" in source
    assert 'manual_body="hot_tub"' in source
    assert "_native_intellicenter_hot_tub_rpm" in source


def test_pool_and_hot_tub_rpm_controls_require_active_body() -> None:
    source = (COMPONENT / "number.py").read_text(encoding="utf-8")

    assert 'observation.observation_id == "pool.active"' in source
    assert 'observation.observation_id == "spa.active"' in source
    assert "pool_active" in source
    assert "spa_active" in source
