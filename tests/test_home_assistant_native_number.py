"""Contracts for PoolOS native Pool PMPCIRC RPM control."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "number.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_number_platform_is_registered() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert '"number"' in const
    assert SOURCE.is_file()


def test_pool_rpm_number_targets_exact_native_pmpcirc() -> None:
    source = _source()

    assert '_POOL_PMPCIRC_OBJNAM = "p0102"' in source
    assert '_POOL_PMPCIRC_TYPE = "PMPCIRC"' in source
    assert '_RPM_MODE = "RPM"' in source


def test_pool_rpm_number_is_native_authoritative_and_not_optimistic() -> None:
    source = _source()

    assert "independent_intellicenter_transport" in source
    assert "raw_inventory" in source
    assert '"observation_authority": "native_intellicenter"' in source
    assert '"optimistic": False' in source


def test_pool_rpm_number_uses_only_narrow_manual_gateway_for_write() -> None:
    source = _source()

    assert "manual.async_set_pump_circuit_speed(" in source

    for prohibited in (
        "request_changes(",
        "SETPARAMLIST",
        "send_cmd(",
        "set_circuit_state(",
    ):
        assert prohibited not in source


def test_pool_rpm_number_preserves_manual_only_authority() -> None:
    source = _source()

    assert '"manual_command_delivery_enabled"' in source
    assert '"autonomous_command_delivery_enabled": False' in source


def test_pool_rpm_number_distinguishes_setpoint_from_actual_rpm() -> None:
    source = _source()

    assert '"actual_pump_rpm_concept": "pump.rpm"' in source
    assert '"native_speed_setpoint"' in source


def test_manual_gateway_validates_pmpcirc_identity_mode_and_parent() -> None:
    source = (COMPONENT / "manual_intellicenter.py").read_text(
        encoding="utf-8"
    )

    assert "_ALLOWED_PUMP_CIRCUIT_IDS" in source
    assert "PMPCIRC_TYPE" in source
    assert "SELECT_ATTR" in source
    assert "PARENT_ATTR" in source
    assert "PUMP_TYPE" in source
    assert "MIN_ATTR" in source
    assert "MAX_ATTR" in source
    assert "pump_rpm_requires_native_limits" in source
    assert "pump_rpm_requires_explicit_rpm_mode" in source
