"""Contracts for PoolOS native IntelliCenter Pool Light control."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "light.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_light_platform_is_enabled() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert (
        'PLATFORMS = '
        '("sensor", "binary_sensor", "button", "climate", "switch", "light")'
        in const
    )


def test_pool_light_uses_exact_native_object_and_concept() -> None:
    source = _source()

    assert '_POOL_LIGHT_OBJNAM = "C0002"' in source
    assert '_POOL_LIGHT_CONCEPT = "pool_light.active"' in source
    assert 'self._attr_name = "Pool Light"' not in source
    assert '_attr_name = "Pool Light"' in source


def test_pool_light_state_is_native_authoritative() -> None:
    source = _source()

    assert "native_intellicenter_snapshot" in source
    assert "_native_value(" in source
    assert "_POOL_LIGHT_CONCEPT" in source
    assert '"observation_authority": "native_intellicenter"' in source
    assert '"optimistic": False' in source


def test_pool_light_uses_only_narrow_manual_gateway_for_writes() -> None:
    source = _source()

    assert "manual.async_set_circuit_state(" in source
    assert "_POOL_LIGHT_OBJNAM" in source

    for prohibited in (
        "request_changes(",
        "send_cmd(",
        "SETPARAMLIST",
        "ACT_ATTR",
        "USE_ATTR",
        "async_set_light_effect",
    ):
        assert prohibited not in source


def test_pool_light_is_on_off_only_for_first_milestone() -> None:
    source = _source()

    assert "_attr_supported_color_modes = {ColorMode.ONOFF}" in source
    assert "_attr_color_mode = ColorMode.ONOFF" in source
    assert '"effect_control_enabled": False' in source
    assert "effect_list" not in source
    assert "async_set_effect" not in source


def test_manual_gateway_explicitly_allows_pool_light_circuit() -> None:
    source = (COMPONENT / "manual_intellicenter.py").read_text(
        encoding="utf-8"
    )

    assert (
        '_ALLOWED_CIRCUIT_IDS = '
        'frozenset({"C0002", "C0003", "C0004", "FTR01"})'
        in source
    )
