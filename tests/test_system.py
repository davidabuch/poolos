from dataclasses import FrozenInstanceError

import pytest


def test_system_state_normalizes_controller_values(
    api_modules, system_object_factory
):
    system = system_object_factory(
        service="TIME OUT",
        mode="  NORMAL  ",
        vacation="ON",
        version=" 2.017 ",
    )

    state = api_modules.panel.build_system_state(system)

    assert state.id == "SYSTM"
    assert state.name == "IntelliCenter"
    assert state.operating_mode is api_modules.models.SystemMode.TIMEOUT
    assert state.raw_operating_mode == "TIME OUT"
    assert state.controller_mode == "NORMAL"
    assert state.vacation_mode is True
    assert state.firmware_version == "2.017"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AUTO", "AUTO"),
        ("service", "SERVICE"),
        ("TIMOUT", "TIMEOUT"),
        ("timeout", "TIMEOUT"),
        ("unexpected", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
def test_system_mode_aliases(api_modules, system_object_factory, raw, expected):
    state = api_modules.panel.build_system_state(system_object_factory(service=raw))
    assert state.operating_mode is getattr(api_modules.models.SystemMode, expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ON", True),
        ("1", True),
        (1, True),
        ("OFF", False),
        ("0", False),
        ("false", False),
        (None, False),
    ],
)
def test_vacation_mode_boolean_normalization(
    api_modules, system_object_factory, raw, expected
):
    state = api_modules.panel.build_system_state(system_object_factory(vacation=raw))
    assert state.vacation_mode is expected


def test_missing_optional_values_are_none(api_modules, system_object_factory):
    state = api_modules.panel.build_system_state(
        system_object_factory(mode="", version=None)
    )

    assert state.controller_mode is None
    assert state.firmware_version is None


def test_system_state_is_immutable(api_modules, system_object_factory):
    state = api_modules.panel.build_system_state(system_object_factory())

    with pytest.raises(FrozenInstanceError):
        state.vacation_mode = True


def test_api_exposes_system_and_prefers_object_firmware(
    api_modules, coordinator_factory, system_object_factory
):
    system = system_object_factory(version="3.2.1")
    coordinator = coordinator_factory([system])
    coordinator.system_info.sw_version = "fallback"

    api = api_modules.system.IntelliCenterAPI(coordinator)
    snapshot = api.refresh()

    assert api.system is snapshot.system
    assert api.system is not None
    assert api.system.id == "SYSTM"
    assert snapshot.software_version == "3.2.1"


def test_api_uses_system_info_firmware_when_system_value_missing(
    api_modules, coordinator_factory, system_object_factory
):
    system = system_object_factory(version=None)
    coordinator = coordinator_factory([system])
    coordinator.system_info.sw_version = "fallback"

    snapshot = api_modules.system.IntelliCenterAPI(coordinator).refresh()

    assert snapshot.system is not None
    assert snapshot.system.firmware_version is None
    assert snapshot.software_version == "fallback"


def test_api_allows_missing_system_object(api_modules, coordinator_factory):
    snapshot = api_modules.system.IntelliCenterAPI(coordinator_factory([])).refresh()

    assert snapshot.system is None
    assert snapshot.software_version == "9.9.9"
