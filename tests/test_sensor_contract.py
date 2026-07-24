"""Static contracts for the Home Assistant sensor platform migration."""

import ast
from pathlib import Path


SENSOR_PATH = Path(__file__).resolve().parents[1] / "intellicenter" / "sensor.py"


def test_sensor_module_is_valid_python():
    ast.parse(SENSOR_PATH.read_text())


def test_sensor_state_reads_use_immutable_api():
    source = SENSOR_PATH.read_text()
    native_value_source = source[source.index("class PoolSensor"):]

    assert "coordinator.api" in source
    assert "self._pool_object[self._attribute_key]" not in native_value_source


def test_actual_pump_rpm_uses_pump_state_rpm():
    source = SENSOR_PATH.read_text()

    assert '(RPM_ATTR, "rpm"' in source
