"""Contracts for the PoolOS C5.10 narrow native manual-control gateway."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "manual_intellicenter.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_manual_gateway_is_separate_from_read_only_transport() -> None:
    source = _source()
    readonly = (COMPONENT / "independent_intellicenter.py").read_text(
        encoding="utf-8"
    )

    assert "class ManualIntelliCenterControl" in source
    assert "class _ReadOnlyModelController" not in source
    assert "class ManualIntelliCenterControl" not in readonly


def test_manual_gateway_exposes_only_explicit_manual_operations() -> None:
    source = _source()

    assert "async def async_set_body_active(" in source
    assert "async def async_set_heating_setpoint(" in source
    assert "async def async_set_pool_solar_active(" in source
    assert "async def async_set_circuit_state(" in source
    assert "async def async_set_light_effect(" in source
    assert "async def async_set_pump_circuit_speed(" in source

    for prohibited in (
        "async_set_pump_speed",
        "async_set_chlorinator",
        "async_set_heater_mode",
        "async_request_changes",
        "send_cmd(",
    ):
        assert prohibited not in source


def test_manual_gateway_allows_only_known_pool_and_spa_body_ids() -> None:
    source = _source()

    assert '_ALLOWED_BODY_IDS = frozenset({"B1101", "B1202"})' in source
    assert "unsupported manual-control body" in source


def test_manual_gateway_allows_only_known_feature_circuit_ids() -> None:
    source = _source()

    assert '_ALLOWED_CIRCUIT_IDS = frozenset({"C0002", "C0003", "C0004", "FTR01"})' in source
    assert "unsupported manual-control circuit" in source


def test_manual_gateway_has_explicit_temperature_bounds() -> None:
    source = _source()

    assert "_MIN_TARGET_TEMPERATURE = 40" in source
    assert "_MAX_TARGET_TEMPERATURE = 104" in source
    assert "temperature must be between" in source


def test_manual_gateway_does_not_enable_autonomous_delivery() -> None:
    source = _source()

    assert '"manual_command_delivery_enabled": True' in source
    assert '"autonomous_command_delivery_enabled": False' in source


def test_manual_gateway_uses_pyintellicenter_supported_write_methods() -> None:
    source = _source()

    assert "self._controller.request_changes(" in source
    assert "STATUS_ATTR: STATUS_ON if active else STATUS_OFF" in source
    assert "self._controller.set_heating_setpoint(" in source
    assert "HEATER_ATTR: heater_objnam" in source
    assert '"B1101"' in source
    assert '"H0002"' in source
    assert '"00000"' in source
    assert "self._controller.set_circuit_state(" in source
    assert "self._controller.set_light_effect(" in source
    assert "SPEED_ATTR: str(target)" in source
    assert '"p0102"' in source


def test_manual_gateway_has_no_generic_public_setparamlist_surface() -> None:
    tree = ast.parse(_source())

    public_async_methods: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name.startswith("async_") and not node.name.startswith("async__"):
            public_async_methods.add(node.name)

    assert public_async_methods == {
        "async_start",
        "async_stop",
        "async_set_body_active",
        "async_set_heating_setpoint",
        "async_set_pool_solar_active",
        "async_set_circuit_state",
        "async_set_light_effect",
        "async_set_pump_circuit_speed",
    }


def test_read_only_transport_remains_structurally_guarded() -> None:
    source = (COMPONENT / "independent_intellicenter.py").read_text(
        encoding="utf-8"
    )

    assert "ALLOWED_READ_ONLY_PROTOCOL_OPERATIONS" in source
    assert "class _ReadOnlyModelController" in source
    assert 'self._read_only_guard.require_allowed("SETPARAMLIST")' in source
    assert '"command_delivery_enabled": False' in source
    assert '"physical_delivery_enabled": False' in source
    assert '"read_only_safety_mode": True' in source
