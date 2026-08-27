"""Contracts for PoolOS C5.10 native Pool/Spa climate entities."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
SOURCE = COMPONENT / "climate.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_climate_platform_is_enabled() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    assert '"climate"' in const
    assert "PLATFORMS" in const


def test_pool_and_spa_thermostats_are_defined() -> None:
    source = _source()

    assert 'key="pool"' in source
    assert 'name="Pool Thermostat"' in source
    assert 'body_objnam="B1101"' in source

    assert 'key="spa"' in source
    assert 'name="Hot Tub Thermostat"' in source
    assert 'body_objnam="B1202"' in source


def test_climate_exposes_only_off_and_heat_modes() -> None:
    source = _source()

    assert "_attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]" in source
    assert "HVACMode.COOL" not in source
    assert "HVACMode.AUTO" not in source


def test_climate_reads_native_authoritative_observations() -> None:
    source = _source()

    assert "native_intellicenter_snapshot" in source
    assert '"pool.active"' in source
    assert '"spa.active"' in source
    assert '"pool.temperature"' in source
    assert '"spa.temperature"' in source
    assert '"pool.target_temperature"' in source
    assert '"spa.target_temperature"' in source
    assert '"pool.heating_demand_active"' in source
    assert '"spa.heating_demand_active"' in source


def test_climate_uses_only_narrow_manual_gateway_for_writes() -> None:
    source = _source()

    assert "manual.async_set_body_active(" in source
    assert "manual.async_set_heating_setpoint(" in source

    for prohibited in (
        "request_changes(",
        "send_cmd(",
        "SETPARAMLIST",
        "async_set_heater_mode",
        "async_set_light_effect",
    ):
        assert prohibited not in source


def test_climate_does_not_enable_autonomous_commands() -> None:
    source = _source()

    assert '"autonomous_command_delivery_enabled": False' in source


def test_runtime_owns_single_manual_gateway() -> None:
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")

    assert "manual_intellicenter: ManualIntelliCenterControl | None" in source
    assert "manual_intellicenter = (" in source
    assert "await manual_intellicenter.async_start()" in source
    assert "await entry.runtime_data.manual_intellicenter.async_stop()" in source


def test_climate_does_not_construct_writable_controller() -> None:
    source = _source()

    assert "ManualIntelliCenterControl(" not in source
    assert "ICModelController(" not in source
    assert "ICConnectionHandler(" not in source


def test_climate_preserves_temperature_bounds() -> None:
    source = _source()

    assert "_attr_min_temp = 40" in source
    assert "_attr_max_temp = 104" in source
    assert "_attr_target_temperature_step = 1" in source


# EXECUTABLE C5.10B THERMOSTAT BEHAVIOR TESTS


def _load_executable_climate_module():
    """Load climate.py with minimal HA stubs for executable unit behavior."""

    import enum
    import importlib.util
    import sys
    import types

    package_name = "_poolos_c510b_executable_climate_test"
    climate_name = f"{package_name}.climate"

    existing = sys.modules.get(climate_name)
    if existing is not None:
        return existing

    module_names = [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.climate",
        "homeassistant.components.climate.const",
        "homeassistant.config_entries",
        "homeassistant.const",
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

        climate_component = types.ModuleType("homeassistant.components.climate")

        class ClimateEntity:
            @property
            def hvac_modes(self):
                return self._attr_hvac_modes

        climate_component.ClimateEntity = ClimateEntity
        sys.modules["homeassistant.components.climate"] = climate_component

        climate_const = types.ModuleType("homeassistant.components.climate.const")

        class ClimateEntityFeature(enum.IntFlag):
            TARGET_TEMPERATURE = 1

        class HVACMode(str, enum.Enum):
            OFF = "off"
            HEAT = "heat"

        class HVACAction(str, enum.Enum):
            OFF = "off"
            IDLE = "idle"
            HEATING = "heating"

        climate_const.ClimateEntityFeature = ClimateEntityFeature
        climate_const.HVACMode = HVACMode
        climate_const.HVACAction = HVACAction
        sys.modules["homeassistant.components.climate.const"] = climate_const

        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigEntry:
            @classmethod
            def __class_getitem__(cls, item):
                del item
                return cls

        config_entries.ConfigEntry = ConfigEntry
        sys.modules["homeassistant.config_entries"] = config_entries

        ha_const = types.ModuleType("homeassistant.const")
        ha_const.ATTR_TEMPERATURE = "temperature"

        class UnitOfTemperature:
            FAHRENHEIT = "°F"

        ha_const.UnitOfTemperature = UnitOfTemperature
        sys.modules["homeassistant.const"] = ha_const

        core = types.ModuleType("homeassistant.core")

        class HomeAssistant:
            pass

        core.HomeAssistant = HomeAssistant
        sys.modules["homeassistant.core"] = core

        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers

        entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
        entity_platform.AddConfigEntryEntitiesCallback = object
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

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

        coordinator_module = types.ModuleType(f"{package_name}.coordinator")

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
        sys.modules[f"{package_name}.manual_intellicenter"] = manual_module

        spec = importlib.util.spec_from_file_location(
            climate_name,
            COMPONENT / "climate.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load PoolOS climate.py")

        module = importlib.util.module_from_spec(spec)
        sys.modules[climate_name] = module
        spec.loader.exec_module(module)
        return module

    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _build_executable_spa_entity(
    *,
    active: bool,
    heating: bool,
    current_temperature: float = 86.0,
    target_temperature: float = 98.0,
    manual_available: bool = True,
    key: str = "spa",
):
    """Build a real body climate entity around fake boundaries."""

    from types import SimpleNamespace

    module = _load_executable_climate_module()

    observations = (
        SimpleNamespace(
            observation_id=f"{key}.active",
            value=active,
        ),
        SimpleNamespace(
            observation_id=f"{key}.temperature",
            value=current_temperature,
        ),
        SimpleNamespace(
            observation_id=f"{key}.target_temperature",
            value=target_temperature,
        ),
        SimpleNamespace(
            observation_id=f"{key}.heating_demand_active",
            value=heating,
        ),
    )

    snapshot = SimpleNamespace(
        available=True,
        observations=observations,
    )

    coordinator = SimpleNamespace(
        native_intellicenter_snapshot=snapshot,
    )

    class FakeManualControl:
        def __init__(self):
            self.available = manual_available
            self.calls = []

        async def async_set_body_active(self, body_objnam, enabled):
            if not self.available:
                raise module.ManualIntelliCenterCommandError(
                    "manual IntelliCenter command connection is unavailable"
                )
            self.calls.append(
                ("body_active", body_objnam, enabled)
            )

        async def async_set_heating_setpoint(
            self,
            body_objnam,
            temperature,
        ):
            if not self.available:
                raise module.ManualIntelliCenterCommandError(
                    "manual IntelliCenter command connection is unavailable"
                )
            self.calls.append(
                ("heating_setpoint", body_objnam, temperature)
            )

    manual = FakeManualControl()

    runtime = SimpleNamespace(
        manual_intellicenter=manual,
    )

    entry = SimpleNamespace(
        runtime_data=runtime,
        entry_id="test_poolos_entry",
    )

    description = next(
        item
        for item in module.CLIMATE_DESCRIPTIONS
        if item.key == key
    )

    entity = module.PoolOSNativeClimate(
        coordinator,
        entry,
        description,
    )

    return module, entity, manual


def test_behavior_spa_active_maps_to_homekit_heat_mode() -> None:
    module, entity, _manual = _build_executable_spa_entity(
        active=True,
        heating=False,
    )

    assert entity.hvac_mode is module.HVACMode.HEAT


def test_behavior_spa_active_without_heating_is_idle() -> None:
    module, entity, _manual = _build_executable_spa_entity(
        active=True,
        heating=False,
    )

    assert entity.hvac_action is module.HVACAction.IDLE


def test_behavior_spa_heating_demand_reports_heating() -> None:
    module, entity, _manual = _build_executable_spa_entity(
        active=True,
        heating=True,
    )

    assert entity.hvac_action is module.HVACAction.HEATING


def test_behavior_siri_style_101_degree_command_targets_spa() -> None:
    import asyncio

    module, entity, manual = _build_executable_spa_entity(
        active=False,
        heating=False,
    )

    asyncio.run(
        entity.async_set_temperature(
            **{module.ATTR_TEMPERATURE: 101}
        )
    )

    assert manual.calls == [
        ("heating_setpoint", "B1202", 101)
    ]


def test_inactive_pool_and_hot_tub_targets_are_configuration_only() -> None:
    import asyncio

    pool_module, pool, pool_manual = _build_executable_spa_entity(
        key="pool",
        active=False,
        heating=False,
        target_temperature=90.0,
    )
    spa_module, spa, spa_manual = _build_executable_spa_entity(
        key="spa",
        active=False,
        heating=False,
        target_temperature=101.0,
    )

    asyncio.run(
        pool.async_set_temperature(**{pool_module.ATTR_TEMPERATURE: 91})
    )
    asyncio.run(
        spa.async_set_temperature(**{spa_module.ATTR_TEMPERATURE: 102})
    )

    assert pool_manual.calls == [("heating_setpoint", "B1101", 91)]
    assert spa_manual.calls == [("heating_setpoint", "B1202", 102)]
    assert all(call[0] != "body_active" for call in pool_manual.calls)
    assert all(call[0] != "body_active" for call in spa_manual.calls)
    assert pool.hvac_mode is pool_module.HVACMode.OFF
    assert spa.hvac_mode is spa_module.HVACMode.OFF


def test_behavior_homekit_heat_and_off_control_spa_body() -> None:
    import asyncio

    module, entity, manual = _build_executable_spa_entity(
        active=False,
        heating=False,
    )

    asyncio.run(
        entity.async_set_hvac_mode(module.HVACMode.HEAT)
    )
    asyncio.run(
        entity.async_set_hvac_mode(module.HVACMode.OFF)
    )

    assert manual.calls == [
        ("body_active", "B1202", True),
        ("body_active", "B1202", False),
    ]


def test_behavior_unavailable_manual_transport_disables_control() -> None:
    import asyncio

    import pytest

    module, entity, manual = _build_executable_spa_entity(
        active=False,
        heating=False,
        manual_available=False,
    )

    assert entity.available is False
    assert manual.calls == []

    with pytest.raises(module.ManualIntelliCenterCommandError):
        asyncio.run(
            entity.async_set_hvac_mode(module.HVACMode.HEAT)
        )

    with pytest.raises(module.ManualIntelliCenterCommandError):
        asyncio.run(
            entity.async_set_temperature(
                **{module.ATTR_TEMPERATURE: 101}
            )
        )

    assert manual.calls == []


def test_native_climate_exposes_parity_body_context_attributes() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert '"Status": self._native_status_attribute' in source
    assert '"HEATER": self._native_heater_attribute' in source
    assert '"HTMODE": self._native_htmode_attribute' in source

    assert 'self._native_body_value("active")' in source
    assert 'self._native_body_value("raw_heater_id")' in source
    assert 'self._native_body_value("raw_htmode")' in source


def test_native_climate_body_context_remains_native_authoritative() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "_native_value(self.coordinator, concept)" in source
    assert "_native_status_attribute" in source
    assert "_native_heater_attribute" in source
    assert "_native_htmode_attribute" in source
