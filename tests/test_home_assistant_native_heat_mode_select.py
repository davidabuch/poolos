"""Contracts for PoolOS requested body heat-mode selectors."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "select.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_select_platform_is_enabled() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert '"select"' in const
    assert "PLATFORMS" in const


def test_exact_user_heat_mode_options() -> None:
    source = _source()

    assert 'HEAT_MODE_OFF = "Off"' in source
    assert 'HEAT_MODE_SOLAR = "Solar"' in source
    assert 'HEAT_MODE_GAS = "Gas"' in source
    assert 'HEAT_MODE_SOLAR_PREFERRED = "Solar Preferred"' in source


def test_pool_and_hot_tub_defaults_are_body_specific() -> None:
    source = _source()

    assert 'key="pool"' in source
    assert 'body_objnam="B1101"' in source
    assert "default_mode=HEAT_MODE_SOLAR" in source

    assert 'key="hot_tub"' in source
    assert 'body_objnam="B1202"' in source
    assert "default_mode=HEAT_MODE_SOLAR_PREFERRED" in source


def test_direct_modes_map_only_to_empirically_commissioned_ids() -> None:
    source = _source()

    assert 'HEAT_MODE_OFF: "00000"' in source
    assert 'HEAT_MODE_GAS: "H0001"' in source
    assert 'HEAT_MODE_SOLAR: "H0002"' in source

    assert '"HXSLR"' not in source
    assert "async_set_body_heat_source(" in source


def test_solar_preferred_is_poolos_policy_not_pentair_mode() -> None:
    source = _source()

    assert '"solar_preferred_owner": "poolos"' in source
    assert '"pentair_solar_preferred_used": False' in source
    assert '"solar_preferred_autonomous_delivery_enabled": False' in source

    solar_preferred_branch = (
        "if option == HEAT_MODE_SOLAR_PREFERRED:"
    )
    assert solar_preferred_branch in source


def test_requested_mode_is_restored_without_startup_command() -> None:
    source = _source()

    assert "RestoreEntity" in source
    assert "async_get_last_state()" in source
    assert "previous.state in HEAT_MODE_OPTIONS" in source


def test_requested_and_effective_state_are_separate() -> None:
    source = _source()

    assert '"requested_heat_mode"' in source
    assert '"effective_heat_source"' in source
    assert '"effective_native_heater_id"' in source
    assert "self._requested_mode = option" in source
    assert "_native_value(" in source


def test_direct_htmode_writes_are_forbidden() -> None:
    source = _source()
    manual = (
        COMPONENT / "manual_intellicenter.py"
    ).read_text(encoding="utf-8")

    assert '"direct_htmode_write_enabled": False' in source

    method = manual.split(
        "async def async_set_body_heat_source",
        1,
    )[1].split(
        "async def async_set_pool_solar_active",
        1,
    )[0]

    assert "HEATER_ATTR" in method
    assert "HTMODE" not in method
