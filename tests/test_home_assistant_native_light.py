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
    assert "manual.async_set_light_effect(" in source
    assert "_POOL_LIGHT_OBJNAM" in source

    for prohibited in (
        "request_changes(",
        "send_cmd(",
        "SETPARAMLIST",
        "ACT_ATTR",
        "USE_ATTR",
    ):
        assert prohibited not in source


def test_pool_light_exposes_native_intellibrite_effects() -> None:
    source = _source()

    assert "_attr_supported_color_modes = {ColorMode.ONOFF}" in source
    assert "_attr_color_mode = ColorMode.ONOFF" in source
    assert "_attr_supported_features = LightEntityFeature.EFFECT" in source
    assert "_attr_effect_list = list(LIGHT_EFFECTS.values())" in source
    assert '_POOL_LIGHT_EFFECT_CONCEPT = "pool_light.effect"' in source
    assert "def effect(self)" in source
    assert "LIGHT_EFFECTS.get(effect_code)" in source
    assert "manual.async_set_light_effect(" in source
    assert '"effect_control_enabled": True' in source


def test_manual_gateway_explicitly_allows_pool_light_circuit() -> None:
    source = (COMPONENT / "manual_intellicenter.py").read_text(
        encoding="utf-8"
    )

    assert (
        '_ALLOWED_CIRCUIT_IDS = '
        'frozenset({"C0002", "C0003", "C0004", "FTR01"})'
        in source
    )


def test_pool_light_declares_20_second_transition_lockout() -> None:
    source = _source()

    assert "_POOL_LIGHT_TRANSITION_SECONDS = 20" in source
    assert '"transition_lockout_seconds": _POOL_LIGHT_TRANSITION_SECONDS' in source
    assert '"transitioning": self._transitioning' in source


def test_pool_light_becomes_temporarily_unavailable_during_transition() -> None:
    source = _source()

    assert "not self._transitioning" in source
    assert "self._transitioning = True" in source
    assert "self._transitioning = False" in source
    assert "async_call_later(" in source


def test_pool_light_lockout_begins_only_after_successful_on_command() -> None:
    source = _source()

    command = (
        "await manual.async_set_circuit_state(\n"
        "            _POOL_LIGHT_OBJNAM,\n"
        "            True,\n"
        "        )"
    )
    lockout = "self._begin_transition_lockout()"

    assert command in source
    assert lockout in source
    assert source.index(command) < source.index(lockout)


def test_pool_light_off_does_not_start_transition_lockout() -> None:
    source = _source()

    off_block = source.split(
        "async def async_turn_off",
        1,
    )[1].split(
        "def _begin_transition_lockout",
        1,
    )[0]

    assert "_begin_transition_lockout()" not in off_block


def test_pool_light_effect_selection_uses_narrow_gateway_before_turn_on() -> None:
    source = _source()

    effect_call = "await manual.async_set_light_effect("
    on_call = "await manual.async_set_circuit_state("

    assert effect_call in source
    assert on_call in source
    assert source.index(effect_call) < source.index(on_call)


def test_pool_light_effect_change_uses_same_transition_lockout() -> None:
    source = _source()

    turn_on = source.split(
        "async def async_turn_on",
        1,
    )[1].split(
        "async def async_turn_off",
        1,
    )[0]

    assert "manual.async_set_light_effect(" in turn_on
    assert "self._begin_transition_lockout()" in turn_on


def test_pool_light_effect_state_remains_native_authoritative() -> None:
    source = _source()

    assert '_POOL_LIGHT_EFFECT_CONCEPT = "pool_light.effect"' in source
    assert "_native_value(" in source
    assert "LIGHT_EFFECTS.get(effect_code)" in source
    assert '"optimistic": False' in source


def test_pool_light_exposes_native_effect_code_for_parity() -> None:
    source = _source()

    assert "def native_effect_code(self)" in source
    assert '"effect_code": self.native_effect_code' in source
    assert "_POOL_LIGHT_EFFECT_CONCEPT" in source


def test_pool_light_ui_effect_remains_friendly_while_parity_uses_native_code() -> None:
    source = _source()
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")

    assert "return LIGHT_EFFECTS.get(effect_code)" in source
    assert '"effect_code", quality_required=False' in observation
    assert '"effect", quality_required=False' not in observation
