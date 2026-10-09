"""Manual thermostat authority cutover invariants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "poolos"

def test_manual_body_delivery_guard_is_rechecked_under_lock():
    source = (ROOT / "manual_intellicenter.py").read_text()
    dispatch = source.split("async def _async_deliver(", 1)[1]
    assert "self._require_manual_thermostat_authority(request)" in dispatch
    assert dispatch.index("async with self._command_lock:") < dispatch.rindex("self._require_manual_thermostat_authority(request)")
    assert 'request.operation in {"body_active", "heating_setpoint"}' in source
    assert "request.source is PhysicalRequestSource.MANUAL" in source
    assert "async def async_set_manual_thermostat_delivery" in source

def test_operator_off_suppression_is_not_armed_after_relinquishment():
    source = (ROOT / "manual_intellicenter.py").read_text()
    method = source.split("async def async_set_body_active(", 1)[1].split("async def async_set_circuit_state(", 1)[0]
    assert method.index("not self._manual_thermostat_delivery_enabled") < method.index("pool_off_requested(datetime.now(UTC))")

def test_ha_service_and_observation_attest_relinquishment():
    setup = (ROOT / "__init__.py").read_text()
    climate = (ROOT / "climate.py").read_text()
    assert '"set_manual_thermostat_delivery"' in setup
    assert "coordinator.async_update_listeners()" in setup
    assert "and manual.manual_thermostat_delivery_enabled" in climate
