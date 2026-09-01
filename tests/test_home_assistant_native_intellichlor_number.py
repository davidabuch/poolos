"""Executable behavior for native-authoritative IntelliChlor output numbers."""

from __future__ import annotations

import asyncio
import importlib.util
import math
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def _load_module():
    package_name = "_poolos_intellichlor_number_test"
    module_name = f"{package_name}.number"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    names = (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.number",
        "homeassistant.config_entries",
        "homeassistant.helpers",
        "homeassistant.helpers.entity",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
    )
    previous = {name: sys.modules.get(name) for name in names}
    try:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []
        sys.modules["homeassistant"] = ha
        components = types.ModuleType("homeassistant.components")
        components.__path__ = []
        sys.modules["homeassistant.components"] = components
        number = types.ModuleType("homeassistant.components.number")

        class NumberEntity:
            pass

        class NumberMode:
            BOX = "box"

        number.NumberEntity = NumberEntity
        number.NumberMode = NumberMode
        sys.modules["homeassistant.components.number"] = number
        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigEntry:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

        config_entries.ConfigEntry = ConfigEntry
        sys.modules["homeassistant.config_entries"] = config_entries
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers
        entity = types.ModuleType("homeassistant.helpers.entity")

        class EntityCategory:
            CONFIG = "config"

        entity.EntityCategory = EntityCategory
        sys.modules["homeassistant.helpers.entity"] = entity
        entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
        entity_platform.AddConfigEntryEntitiesCallback = object
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
        update = types.ModuleType("homeassistant.helpers.update_coordinator")

        class CoordinatorEntity:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

            def __init__(self, coordinator):
                self.coordinator = coordinator

        update.CoordinatorEntity = CoordinatorEntity
        sys.modules["homeassistant.helpers.update_coordinator"] = update
        package = types.ModuleType(package_name)
        package.__path__ = [str(COMPONENT)]
        package.PoolOSRuntimeData = object
        sys.modules[package_name] = package
        const = types.ModuleType(f"{package_name}.const")
        const.DOMAIN = "poolos"
        const.INTEGRATION_VERSION = "test"
        sys.modules[f"{package_name}.const"] = const
        coordinator = types.ModuleType(f"{package_name}.coordinator")
        coordinator.PoolOSCoordinator = object
        sys.modules[f"{package_name}.coordinator"] = coordinator
        manual = types.ModuleType(f"{package_name}.manual_intellicenter")

        class ManualIntelliCenterCommandError(RuntimeError):
            pass

        manual.ManualIntelliCenterCommandError = ManualIntelliCenterCommandError
        sys.modules[f"{package_name}.manual_intellicenter"] = manual
        spec = importlib.util.spec_from_file_location(
            module_name,
            COMPONENT / "number.py",
        )
        assert spec is not None and spec.loader is not None
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


def _entity(*, pool: int | None = 52, spa: int | None = 4, manual_available=True):
    module = _load_module()
    chlorinator = SimpleNamespace(
        native_id="CHR01",
        pool_output_percent=pool,
        spa_output_percent=spa,
    )
    snapshot = SimpleNamespace(
        connected=True,
        intellichlors=(chlorinator,),
        raw_inventory=(),
    )
    coordinator = SimpleNamespace(
        independent_intellicenter_transport=SimpleNamespace(
            latest_snapshot=snapshot,
        ),
        native_intellicenter_snapshot=SimpleNamespace(available=True),
    )
    manual = SimpleNamespace(
        available=manual_available,
        async_set_intellichlor_output=AsyncMock(),
    )
    entry = SimpleNamespace(
        entry_id="entry",
        runtime_data=SimpleNamespace(
            coordinator=coordinator,
            manual_intellicenter=manual,
        ),
    )
    entities = {
        description.key: module.PoolOSNativeIntelliCenterIntelliChlorOutput(
            coordinator,
            entry,
            description,
        )
        for description in module._INTELLICHLOR_OUTPUTS
    }
    return module, entities, manual, chlorinator


def test_numbers_display_only_native_readback_and_are_not_optimistic() -> None:
    module, entities, manual, chlorinator = _entity()
    del module

    assert entities["pool"].available is True
    assert entities["spa"].available is True
    assert entities["pool"].native_value == 52
    assert entities["spa"].native_value == 4

    asyncio.run(entities["pool"].async_set_native_value(60.0))
    manual.async_set_intellichlor_output.assert_awaited_once_with("B1101", 60)
    assert entities["pool"].native_value == 52

    chlorinator.pool_output_percent = 60
    assert entities["pool"].native_value == 60


def test_command_failure_does_not_mutate_observed_number_state() -> None:
    module, entities, manual, _chlorinator = _entity()
    manual.async_set_intellichlor_output.side_effect = (
        module.ManualIntelliCenterCommandError("synthetic failure")
    )

    with pytest.raises(module.ManualIntelliCenterCommandError):
        asyncio.run(entities["pool"].async_set_native_value(60.0))

    assert entities["pool"].native_value == 52


@pytest.mark.parametrize(
    ("key", "body", "value"),
    (
        ("pool", "B1101", 0.0),
        ("pool", "B1101", 100.0),
        ("spa", "B1202", 0.0),
        ("spa", "B1202", 100.0),
        ("spa", "B1202", 37.0),
    ),
)
def test_number_bounds_and_exact_body_delivery(key: str, body: str, value: float) -> None:
    _module, entities, manual, _chlorinator = _entity()

    asyncio.run(entities[key].async_set_native_value(value))

    manual.async_set_intellichlor_output.assert_awaited_once_with(body, int(value))


@pytest.mark.parametrize("value", (-1.0, 101.0, 4.5, math.inf, math.nan))
def test_number_rejects_invalid_values(value: float) -> None:
    _module, entities, manual, _chlorinator = _entity()

    with pytest.raises(ValueError):
        asyncio.run(entities["pool"].async_set_native_value(value))

    manual.async_set_intellichlor_output.assert_not_awaited()


def test_number_availability_requires_native_readback_and_manual_transport() -> None:
    _module, entities, _manual, _chlorinator = _entity(
        pool=None,
        manual_available=True,
    )
    assert entities["pool"].available is False

    _module, entities, _manual, _chlorinator = _entity(
        pool=52,
        manual_available=False,
    )
    assert entities["pool"].available is False


def test_number_availability_fails_closed_for_multiple_chlorinators() -> None:
    _module, entities, _manual, _chlorinator = _entity()
    snapshot = entities["pool"].coordinator.independent_intellicenter_transport.latest_snapshot
    snapshot.intellichlors = (
        *snapshot.intellichlors,
        SimpleNamespace(
            native_id="CHR02",
            pool_output_percent=50,
            spa_output_percent=5,
        ),
    )

    assert entities["pool"].available is False
    assert entities["pool"].native_value is None

def test_number_surface_contains_no_super_chlorinate_or_autonomous_authority() -> None:
    source = (COMPONENT / "number.py").read_text(encoding="utf-8")

    assert '"super_chlorinate_supported": False' in source
    assert '"autonomous_chemistry_delivery_enabled": False' in source
    assert "async_set_intellichlor_output(" in source
    assert "set_super_chlorinate" not in source
    assert "SUPER_ATTR" not in source
