"""Regression: delegated thermostat authority cannot expire at day rollover."""
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "poolos"

def test_handoff_converts_transient_restraints_to_durable_operator_restraints():
    source = (COMPONENT / "__init__.py").read_text()
    service = source.split("async def _set_manual_thermostat_delivery(", 1)[1].split('hass.services.async_register(', 1)[0]
    assert "PoolAutomaticControlSuppressionSource.OPERATOR_RESTRAINT" in service
    assert "SpaAutomaticControlSuppressionSource.OPERATOR_RESTRAINT" in service
    assert service.index("pool_automatic_control.suppress(") < service.index("async_set_manual_thermostat_delivery(enabled)")
    assert service.index("spa_automatic_control.suppress(") < service.index("async_set_manual_thermostat_delivery(enabled)")

def test_autonomy_resume_refuses_delegated_manual_thermostats():
    source = (COMPONENT / "switch.py").read_text()
    for kind in ("pool", "spa"):
        block = source.split(f"self._runtime.{kind}_automatic_control.resume(resumed_at=datetime.now(UTC))")
        assert len(block) >= 2
        assert "not manual.manual_thermostat_delivery_enabled" in block[-2][-350:]
