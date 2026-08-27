"""Contracts and executable behavior for PoolOS native feature switches."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "switch.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_switch_platform_is_enabled() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert '"switch"' in const
    assert "PLATFORMS" in const


def test_exact_feature_switch_contract() -> None:
    source = _source()

    assert 'key="jets"' in source
    assert 'objnam="C0003"' in source
    assert 'active_concept="jets.active"' in source

    assert 'key="slide"' in source
    assert 'objnam="C0004"' in source
    assert 'active_concept="slide.active"' in source

    assert 'key="waterfall"' in source
    assert 'objnam="FTR01"' in source
    assert 'active_concept="waterfall.active"' in source

    assert "class PoolOSNativeIntelliCenterSolarSwitch" in source
    assert '"solar.active"' in source
    assert '"B1101"' in source
    assert '"H0002"' in source
    assert '"00000"' in source


def test_switches_use_only_manual_gateway_for_writes() -> None:
    source = _source()

    assert "manual.async_set_circuit_state(" in source
    assert "manual.async_set_pool_solar_active(" in source

    for prohibited in (
        "request_changes(",
        "send_cmd(",
        "SETPARAMLIST",
        "ICModelController(",
        "ICConnectionHandler(",
    ):
        assert prohibited not in source


def test_switches_are_native_observation_backed_not_optimistic() -> None:
    source = _source()

    assert "native_intellicenter_snapshot" in source
    assert '"jets.active"' in source
    assert '"slide.active"' in source
    assert '"waterfall.active"' in source
    assert '"optimistic": False' in source


def test_feature_switches_have_explicit_parent_safety_gates() -> None:
    source = _source()

    assert 'required_parent_concept="spa.active"' in source
    assert 'required_parent_name="Spa"' in source
    assert 'required_parent_concept="pool.active"' in source
    assert 'required_parent_name="Pool"' in source
    assert "cannot be turned on" in source
    assert "_async_enforce_parent_interlock" in source


def test_no_autonomous_command_delivery_is_enabled() -> None:
    source = _source()

    assert '"autonomous_command_delivery_enabled": False' in source


def _load_executable_switch_module():
    """Load switch.py using the same lightweight HA-stub pattern as climate tests."""

    package_name = "_poolos_feature_switch_test"
    switch_name = f"{package_name}.switch"

    existing = sys.modules.get(switch_name)
    if existing is not None:
        return existing

    module_names = [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.switch",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
    ]

    previous = {name: sys.modules.get(name) for name in module_names}

    try:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []
        sys.modules["homeassistant"] = ha

        components = types.ModuleType("homeassistant.components")
        components.__path__ = []
        sys.modules["homeassistant.components"] = components

        switch_component = types.ModuleType("homeassistant.components.switch")

        class SwitchEntity:
            pass

        switch_component.SwitchEntity = SwitchEntity
        sys.modules["homeassistant.components.switch"] = switch_component

        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigEntry:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

        config_entries.ConfigEntry = ConfigEntry
        sys.modules["homeassistant.config_entries"] = config_entries

        core = types.ModuleType("homeassistant.core")

        class HomeAssistant:
            pass

        core.HomeAssistant = HomeAssistant
        sys.modules["homeassistant.core"] = core

        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers

        entity_platform = types.ModuleType(
            "homeassistant.helpers.entity_platform"
        )
        entity_platform.AddConfigEntryEntitiesCallback = object
        sys.modules[
            "homeassistant.helpers.entity_platform"
        ] = entity_platform

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

        update_coordinator.CoordinatorEntity = CoordinatorEntity
        sys.modules[
            "homeassistant.helpers.update_coordinator"
        ] = update_coordinator

        package = types.ModuleType(package_name)
        package.__path__ = [str(COMPONENT)]
        package.__package__ = package_name

        class PoolOSRuntimeData:
            pass

        package.PoolOSRuntimeData = PoolOSRuntimeData
        sys.modules[package_name] = package

        const_module = types.ModuleType(f"{package_name}.const")
        const_module.DOMAIN = "poolos"
        const_module.INTEGRATION_VERSION = "test"
        sys.modules[f"{package_name}.const"] = const_module

        coordinator_module = types.ModuleType(
            f"{package_name}.coordinator"
        )

        class PoolOSCoordinator:
            pass

        coordinator_module.PoolOSCoordinator = PoolOSCoordinator
        sys.modules[f"{package_name}.coordinator"] = coordinator_module

        manual_module = types.ModuleType(
            f"{package_name}.manual_intellicenter"
        )

        class ManualIntelliCenterCommandError(RuntimeError):
            pass

        manual_module.ManualIntelliCenterCommandError = (
            ManualIntelliCenterCommandError
        )
        sys.modules[
            f"{package_name}.manual_intellicenter"
        ] = manual_module

        spec = importlib.util.spec_from_file_location(
            switch_name,
            SOURCE,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load PoolOS switch.py")

        module = importlib.util.module_from_spec(spec)
        sys.modules[switch_name] = module
        spec.loader.exec_module(module)

        return module

    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class _Observation:
    def __init__(self, observation_id: str, value: object) -> None:
        self.observation_id = observation_id
        self.value = value


class _Snapshot:
    available = True

    def __init__(self, values: dict[str, object]) -> None:
        self.observations = tuple(
            _Observation(concept, value)
            for concept, value in values.items()
        )


class _Coordinator:
    def __init__(self, values: dict[str, object]) -> None:
        self.native_intellicenter_snapshot = _Snapshot(values)


class _Manual:
    available = True

    def __init__(self) -> None:
        self.async_set_circuit_state = AsyncMock()
        self.async_set_pool_solar_active = AsyncMock()


class _Entry:
    entry_id = "test-entry"

    def __init__(
        self,
        coordinator: _Coordinator,
        manual: _Manual,
    ) -> None:
        self.runtime_data = SimpleNamespace(
            coordinator=coordinator,
            manual_intellicenter=manual,
        )


def _description(module, key: str):
    return next(
        item
        for item in module.SWITCH_DESCRIPTIONS
        if item.key == key
    )


def test_exact_objects_receive_exact_manual_commands() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": False,
                "slide.active": True,
                "waterfall.active": False,
                "spa.active": True,
                "pool.active": True,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )
        slide = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "slide"),
        )
        waterfall = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "waterfall"),
        )

        assert jets.is_on is False
        assert slide.is_on is True
        assert waterfall.is_on is False

        await jets.async_turn_on()
        manual.async_set_circuit_state.assert_awaited_once_with(
            "C0003",
            True,
        )

        manual.async_set_circuit_state.reset_mock()

        await slide.async_turn_off()
        manual.async_set_circuit_state.assert_awaited_once_with(
            "C0004",
            False,
        )

        manual.async_set_circuit_state.reset_mock()

        await waterfall.async_turn_on()
        manual.async_set_circuit_state.assert_awaited_once_with(
            "FTR01",
            True,
        )

    asyncio.run(run())


def test_jets_on_fails_closed_when_spa_is_off() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": False,
                "spa.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )

        with pytest.raises(
            module.ManualIntelliCenterCommandError,
            match="unless Spa is active",
        ):
            await jets.async_turn_on()

        manual.async_set_circuit_state.assert_not_awaited()

    asyncio.run(run())


def test_jets_on_fails_closed_when_spa_state_unknown() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )

        with pytest.raises(
            module.ManualIntelliCenterCommandError,
            match="unless Spa is active",
        ):
            await jets.async_turn_on()

        manual.async_set_circuit_state.assert_not_awaited()

    asyncio.run(run())


def test_jets_off_remains_allowed_when_spa_is_off() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": True,
                "spa.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )

        await jets.async_turn_off()

        manual.async_set_circuit_state.assert_awaited_once_with(
            "C0003",
            False,
        )

    asyncio.run(run())


def test_command_does_not_optimistically_mutate_switch_state() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "slide.active": False,
                "spa.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        slide = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "slide"),
        )

        assert slide.is_on is False

        await slide.async_turn_on()

        # No optimistic state is written by the entity.
        # Until a new native observation arrives, state remains OFF.
        assert slide.is_on is False

        coordinator.native_intellicenter_snapshot = _Snapshot(
            {
                "slide.active": True,
                "spa.active": False,
            }
        )

        assert slide.is_on is True

    asyncio.run(run())


def test_parent_interlock_contracts_are_exact() -> None:
    module = _load_executable_switch_module()

    jets = _description(module, "jets")
    slide = _description(module, "slide")
    waterfall = _description(module, "waterfall")

    assert jets.required_parent_concept == "spa.active"
    assert jets.required_parent_name == "Spa"

    assert waterfall.required_parent_concept == "pool.active"
    assert waterfall.required_parent_name == "Pool"

    assert slide.required_parent_concept is None
    assert slide.required_parent_name is None


def test_spillway_on_fails_closed_when_pool_is_off() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "waterfall.active": False,
                "pool.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        spillway = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "waterfall"),
        )

        with pytest.raises(
            module.ManualIntelliCenterCommandError,
            match="unless Pool is active",
        ):
            await spillway.async_turn_on()

        manual.async_set_circuit_state.assert_not_awaited()

    asyncio.run(run())


def test_spillway_on_fails_closed_when_pool_state_unknown() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "waterfall.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        spillway = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "waterfall"),
        )

        with pytest.raises(
            module.ManualIntelliCenterCommandError,
            match="unless Pool is active",
        ):
            await spillway.async_turn_on()

        manual.async_set_circuit_state.assert_not_awaited()

    asyncio.run(run())


def test_jets_are_forced_off_when_spa_becomes_inactive() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": True,
                "spa.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )

        await jets._async_enforce_parent_interlock()

        manual.async_set_circuit_state.assert_awaited_once_with(
            "C0003",
            False,
        )

    asyncio.run(run())


def test_spillway_is_forced_off_when_pool_becomes_inactive() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "waterfall.active": True,
                "pool.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        spillway = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "waterfall"),
        )

        await spillway._async_enforce_parent_interlock()

        manual.async_set_circuit_state.assert_awaited_once_with(
            "FTR01",
            False,
        )

    asyncio.run(run())


def test_parent_interlock_never_turns_child_on() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": False,
                "spa.active": False,
                "waterfall.active": False,
                "pool.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )
        spillway = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "waterfall"),
        )

        await jets._async_enforce_parent_interlock()
        await spillway._async_enforce_parent_interlock()

        manual.async_set_circuit_state.assert_not_awaited()

    asyncio.run(run())


def test_interlock_does_not_repeat_off_before_native_confirmation() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "jets.active": True,
                "spa.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        jets = module.PoolOSNativeIntelliCenterSwitch(
            coordinator,
            entry,
            _description(module, "jets"),
        )

        await jets._async_enforce_parent_interlock()
        await jets._async_enforce_parent_interlock()

        manual.async_set_circuit_state.assert_awaited_once_with(
            "C0003",
            False,
        )

        coordinator.native_intellicenter_snapshot = _Snapshot(
            {
                "jets.active": False,
                "spa.active": False,
            }
        )

        await jets._async_enforce_parent_interlock()

        assert jets._safety_interlock_off_pending is False

    asyncio.run(run())

def test_solar_switch_exact_manual_commands_and_native_state() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "solar.active": True,
                "pool.active": True,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        solar = module.PoolOSNativeIntelliCenterSolarSwitch(
            coordinator,
            entry,
        )

        assert solar.is_on is True

        await solar.async_turn_off()
        manual.async_set_pool_solar_active.assert_awaited_once_with(False)

        manual.async_set_pool_solar_active.reset_mock()

        coordinator.native_intellicenter_snapshot = _Snapshot(
            {
                "solar.active": False,
                "pool.active": True,
            }
        )

        assert solar.is_on is False

        await solar.async_turn_on()
        manual.async_set_pool_solar_active.assert_awaited_once_with(True)

    asyncio.run(run())


def test_solar_on_fails_closed_when_pool_is_off() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "solar.active": False,
                "pool.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        solar = module.PoolOSNativeIntelliCenterSolarSwitch(
            coordinator,
            entry,
        )

        with pytest.raises(
            module.ManualIntelliCenterCommandError,
            match="unless Pool is active",
        ):
            await solar.async_turn_on()

        manual.async_set_pool_solar_active.assert_not_awaited()

    asyncio.run(run())


def test_solar_off_remains_allowed_when_pool_is_off() -> None:
    async def run() -> None:
        module = _load_executable_switch_module()

        coordinator = _Coordinator(
            {
                "solar.active": True,
                "pool.active": False,
            }
        )
        manual = _Manual()
        entry = _Entry(coordinator, manual)

        solar = module.PoolOSNativeIntelliCenterSolarSwitch(
            coordinator,
            entry,
        )

        await solar.async_turn_off()
        manual.async_set_pool_solar_active.assert_awaited_once_with(False)

    asyncio.run(run())
