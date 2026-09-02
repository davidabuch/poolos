"""Contracts for PoolOS requested body heat-mode selectors."""

from __future__ import annotations

from pathlib import Path

import pytest


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
    source = (COMPONENT / "manual_thermal.py").read_text(encoding="utf-8")

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
    source = (COMPONENT / "configured_thermal.py").read_text(encoding="utf-8")
    manual = (COMPONENT / "manual_thermal.py").read_text(encoding="utf-8")

    assert 'ThermalRequestedMode.OFF: "00000"' in source
    assert 'ThermalRequestedMode.GAS: "H0001"' in source
    assert 'ThermalRequestedMode.SOLAR: "H0002"' in source
    assert "ThermalRequestedMode.SOLAR_PREFERRED:" not in source

    assert '"HXSLR"' not in source
    assert "configured_heater_intent_for_direct_requested_mode(mode)" in manual
    assert "async_set_body_heat_source(" in manual


def test_solar_preferred_is_poolos_policy_not_pentair_mode() -> None:
    source = _source()
    canonical = (COMPONENT / "manual_thermal.py").read_text(encoding="utf-8")

    assert '"solar_preferred_owner": "poolos"' in source
    assert '"pentair_solar_preferred_used": False' in source
    assert '"solar_preferred_autonomous_delivery_enabled": False' in source

    assert "ThermalRequestedMode.SOLAR_PREFERRED" in canonical
    assert "async_set_body_heat_source" not in canonical.split(
        "if mode is ThermalRequestedMode.SOLAR_PREFERRED:", 1
    )[1].split("manual =", 1)[0]


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
    assert "requested_heat_mode(" in source
    assert "async_request_heat_mode(" in source
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
        "async def async_set_intellichlor_output",
        1,
    )[0]

    assert "HEATER_ATTR" in method
    assert "HTMODE" not in method


def _load_executable_select_module():
    """Load select.py with minimal Home Assistant boundary stubs."""

    import importlib.util
    import sys
    import types

    package_name = "_poolos_inactive_body_select_test"
    module_name = f"{package_name}.select"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    module_names = [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.select",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.restore_state",
        "homeassistant.helpers.update_coordinator",
    ]
    previous = {name: sys.modules.get(name) for name in module_names}
    try:
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []
        sys.modules["homeassistant"] = homeassistant

        components = types.ModuleType("homeassistant.components")
        components.__path__ = []
        sys.modules["homeassistant.components"] = components

        select_component = types.ModuleType("homeassistant.components.select")

        class SelectEntity:
            def async_write_ha_state(self):
                self.write_count = getattr(self, "write_count", 0) + 1

        select_component.SelectEntity = SelectEntity
        sys.modules["homeassistant.components.select"] = select_component

        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigEntry:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

        config_entries.ConfigEntry = ConfigEntry
        sys.modules["homeassistant.config_entries"] = config_entries

        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        sys.modules["homeassistant.core"] = core

        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers

        entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
        entity_platform.AddConfigEntryEntitiesCallback = object
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

        restore_state = types.ModuleType("homeassistant.helpers.restore_state")

        class RestoreEntity:
            pass

        restore_state.RestoreEntity = RestoreEntity
        sys.modules["homeassistant.helpers.restore_state"] = restore_state

        update_coordinator = types.ModuleType(
            "homeassistant.helpers.update_coordinator"
        )

        class CoordinatorEntity:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

            def __init__(self, coordinator):
                self.coordinator = coordinator

            async def async_added_to_hass(self):
                return None

        update_coordinator.CoordinatorEntity = CoordinatorEntity
        sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

        package = types.ModuleType(package_name)
        package.__path__ = [str(COMPONENT)]
        package.PoolOSRuntimeData = object
        sys.modules[package_name] = package

        const_module = types.ModuleType(f"{package_name}.const")
        const_module.DOMAIN = "poolos"
        const_module.INTEGRATION_VERSION = "test"
        sys.modules[f"{package_name}.const"] = const_module

        coordinator_module = types.ModuleType(f"{package_name}.coordinator")
        coordinator_module.PoolOSCoordinator = object
        sys.modules[f"{package_name}.coordinator"] = coordinator_module

        manual_module = types.ModuleType(f"{package_name}.manual_intellicenter")

        class ManualIntelliCenterCommandError(RuntimeError):
            pass

        manual_module.ManualIntelliCenterCommandError = ManualIntelliCenterCommandError
        sys.modules[f"{package_name}.manual_intellicenter"] = manual_module

        spec = importlib.util.spec_from_file_location(
            module_name,
            COMPONENT / "select.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load PoolOS select.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _build_select_entities(*, pool_active: bool, spa_active: bool):
    import types

    module = _load_executable_select_module()
    observations = (
        types.SimpleNamespace(observation_id="pool.active", value=pool_active),
        types.SimpleNamespace(observation_id="spa.active", value=spa_active),
        types.SimpleNamespace(observation_id="pool.raw_heater_id", value="00000"),
        types.SimpleNamespace(observation_id="spa.raw_heater_id", value="00000"),
        types.SimpleNamespace(observation_id="pool.target_temperature", value=90.0),
        types.SimpleNamespace(observation_id="spa.target_temperature", value=101.0),
    )
    coordinator = types.SimpleNamespace(
        native_intellicenter_snapshot=types.SimpleNamespace(
            available=True,
            observations=observations,
        )
    )

    class FakeManual:
        available = True

        def __init__(self):
            self.calls = []

        async def async_set_body_heat_source(self, body_objnam, heater_objnam):
            self.calls.append(("body_heat_source", body_objnam, heater_objnam))

    manual = FakeManual()

    class FakeThermalRuntime:
        def __init__(self):
            self.requested_modes = {}
            self.pool_requested_mode = module.ThermalRequestedMode.SOLAR
            self.hot_tub_requested_mode = (
                module.ThermalRequestedMode.SOLAR_PREFERRED
            )

        def set_requested_mode(self, body, mode, *, publish=True):
            del publish
            self.requested_modes[body] = mode
            if body is module.ThermalBody.POOL:
                self.pool_requested_mode = mode
            else:
                self.hot_tub_requested_mode = mode

    thermal_runtime = FakeThermalRuntime()
    entry = types.SimpleNamespace(
        runtime_data=types.SimpleNamespace(
            manual_intellicenter=manual,
            thermal_runtime=thermal_runtime,
        ),
        entry_id="test-entry",
    )
    entities = {
        description.key: module.PoolOSHeatModeSelect(
            coordinator,
            entry,
            description,
        )
        for description in module.HEAT_MODE_DESCRIPTIONS
    }
    return module, entities, manual, observations


def test_direct_sources_are_configurable_for_inactive_pool_and_hot_tub() -> None:
    import asyncio

    module, entities, manual, _observations = _build_select_entities(
        pool_active=False,
        spa_active=False,
    )

    asyncio.run(entities["pool"].async_select_option(module.HEAT_MODE_SOLAR))
    asyncio.run(entities["pool"].async_select_option(module.HEAT_MODE_GAS))
    asyncio.run(entities["hot_tub"].async_select_option(module.HEAT_MODE_SOLAR))
    asyncio.run(entities["hot_tub"].async_select_option(module.HEAT_MODE_GAS))

    assert manual.calls == [
        ("body_heat_source", "B1101", "H0002"),
        ("body_heat_source", "B1101", "H0001"),
        ("body_heat_source", "B1202", "H0002"),
        ("body_heat_source", "B1202", "H0001"),
    ]
    assert entities["pool"].current_option == module.HEAT_MODE_GAS
    assert entities["hot_tub"].current_option == module.HEAT_MODE_GAS


def test_cross_body_requested_configuration_ignores_other_body_activity() -> None:
    import asyncio

    module, pool_running, manual_a, observations_a = _build_select_entities(
        pool_active=True,
        spa_active=False,
    )
    asyncio.run(
        pool_running["hot_tub"].async_select_option(module.HEAT_MODE_SOLAR)
    )

    module, spa_running, manual_b, observations_b = _build_select_entities(
        pool_active=False,
        spa_active=True,
    )
    asyncio.run(spa_running["pool"].async_select_option(module.HEAT_MODE_GAS))

    assert manual_a.calls == [("body_heat_source", "B1202", "H0002")]
    assert manual_b.calls == [("body_heat_source", "B1101", "H0001")]
    assert [item.value for item in observations_a] == [True, False, "00000", "00000", 90.0, 101.0]
    assert [item.value for item in observations_b] == [False, True, "00000", "00000", 90.0, 101.0]


def test_solar_preferred_is_inactive_body_configuration_only() -> None:
    import asyncio

    module, entities, manual, observations = _build_select_entities(
        pool_active=False,
        spa_active=False,
    )

    asyncio.run(
        entities["pool"].async_select_option(module.HEAT_MODE_SOLAR_PREFERRED)
    )
    asyncio.run(
        entities["hot_tub"].async_select_option(module.HEAT_MODE_SOLAR_PREFERRED)
    )

    assert entities["pool"].current_option == module.HEAT_MODE_SOLAR_PREFERRED
    assert entities["hot_tub"].current_option == module.HEAT_MODE_SOLAR_PREFERRED
    assert manual.calls == []
    assert [item.value for item in observations[:2]] == [False, False]


def test_configuring_one_body_never_optimistically_mutates_the_other() -> None:
    import asyncio

    module, entities, manual, observations = _build_select_entities(
        pool_active=False,
        spa_active=False,
    )
    spa_mode_before = entities["hot_tub"].current_option

    asyncio.run(entities["pool"].async_select_option(module.HEAT_MODE_SOLAR))

    assert manual.calls == [("body_heat_source", "B1101", "H0002")]
    assert entities["hot_tub"].current_option == spa_mode_before
    assert entities["pool"].effective_native_heater_id == "00000"
    assert entities["hot_tub"].effective_native_heater_id == "00000"
    assert [item.value for item in observations] == [False, False, "00000", "00000", 90.0, 101.0]


def test_restore_updates_requested_intent_without_delivering_command() -> None:
    import asyncio
    from types import SimpleNamespace

    module, entities, manual, _observations = _build_select_entities(
        pool_active=False,
        spa_active=False,
    )
    entity = entities["pool"]

    async def last_state():
        return SimpleNamespace(state=module.HEAT_MODE_GAS)

    entity.async_get_last_state = last_state
    asyncio.run(entity.async_added_to_hass())

    assert entity.current_option == module.HEAT_MODE_GAS
    assert manual.calls == []


def test_failed_direct_command_does_not_change_requested_intent() -> None:
    import asyncio

    module, entities, manual, _observations = _build_select_entities(
        pool_active=True,
        spa_active=False,
    )
    entity = entities["pool"]
    original = entity.current_option

    async def fail(body_objnam, heater_objnam):
        del body_objnam, heater_objnam
        raise RuntimeError("synthetic failure")

    manual.async_set_body_heat_source = fail

    with pytest.raises(RuntimeError, match="synthetic failure"):
        asyncio.run(entity.async_select_option(module.HEAT_MODE_GAS))

    assert entity.current_option == original
    assert entity.effective_native_heater_id == "00000"


def test_unknown_native_heater_is_explicit_not_guessed() -> None:
    _module, entities, _manual, observations = _build_select_entities(
        pool_active=True,
        spa_active=False,
    )
    observations[2].value = "H9999"

    assert entities["pool"].effective_native_heater_id == "H9999"
    assert entities["pool"].effective_heat_source == "Unknown (H9999)"


def test_selector_has_no_activity_prerequisite_but_reports_no_implicit_activation() -> None:
    source = _source()

    assert "active_concept" not in source
    assert "unless its body is active" not in source
    assert '"configuration_independent_of_body_activity": True' in source
    assert '"configuration_activates_body": False' in source
