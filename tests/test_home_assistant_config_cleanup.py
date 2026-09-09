"""Regression contracts for retired legacy IntelliCenter HA mappings."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from poolos.observation_parity import ObservationParityEngine, ObservationParityStatus
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
TEST_PACKAGE = "_poolos_component_config_cleanup_test"

RETIRED_KEYS = frozenset(
    {
        "firmware_version_entity",
        "freeze_active_entity",
        "intellichlor_pool_output_entity",
        "intellichlor_salt_entity",
        "intellichlor_spa_output_entity",
        "pool_maximum_temperature_entity",
        "pump_maximum_rpm_entity",
        "pump_minimum_rpm_entity",
        "spa_maximum_temperature_entity",
        "system_mode_entity",
    }
)


def _load_component_module(module_name: str) -> ModuleType:
    if TEST_PACKAGE not in sys.modules:
        package = ModuleType(TEST_PACKAGE)
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        package.__package__ = TEST_PACKAGE
        sys.modules[TEST_PACKAGE] = package

    qualified = f"{TEST_PACKAGE}.{module_name}"
    if existing := sys.modules.get(qualified):
        return existing

    path = COMPONENT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


CONST = _load_component_module("const")
OBSERVATION = _load_component_module("observation")
MIGRATION = _load_component_module("config_entry_migration")


class _ConfigEntries:
    def __init__(self) -> None:
        self.updates: list[tuple[object, dict[str, Any]]] = []

    def async_update_entry(self, entry: object, **changes: Any) -> None:
        self.updates.append((entry, changes))


def _hass() -> SimpleNamespace:
    return SimpleNamespace(config_entries=_ConfigEntries())


def test_retired_selectors_are_absent_while_current_mapping_surface_remains() -> None:
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    translations = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    config_fields = translations["config"]["step"]["user"]["data"]
    option_fields = translations["options"]["step"]["init"]["data"]

    assert CONST.RETIRED_LEGACY_INTELLICENTER_ENTITY_OPTIONS == RETIRED_KEYS
    assert RETIRED_KEYS.isdisjoint(CONST.ALL_ENTITY_OPTIONS)
    assert RETIRED_KEYS.isdisjoint(config_fields)
    assert RETIRED_KEYS.isdisjoint(option_fields)
    assert not any(f'"{key}"' in flow for key in RETIRED_KEYS)

    assert CONST.REQUIRED_ENTITY_OPTIONS == (CONST.CONF_GRID_STATUS_ENTITY,)
    for current in (
        "pool_thermostat_entity",
        "spa_thermostat_entity",
        "pump_rpm_entity",
        "pool_light_entity",
        "intellicenter_host",
        "intellicenter_transport",
    ):
        assert current in config_fields
        assert current in option_fields


def test_retired_mappings_cannot_create_shadow_observations_or_subscriptions() -> None:
    retired_options = {
        key: f"sensor.retired_{index}" for index, key in enumerate(sorted(RETIRED_KEYS))
    }
    retired_options[CONST.CONF_GRID_STATUS_ENTITY] = "binary_sensor.grid"

    configured = OBSERVATION.configured_entity_mapping(retired_options)

    assert configured == {CONST.CONF_GRID_STATUS_ENTITY: "binary_sensor.grid"}
    assert OBSERVATION.configured_entity_ids(retired_options) == (
        "binary_sensor.grid",
    )
    assert RETIRED_KEYS.isdisjoint(
        spec.option_key for spec in OBSERVATION.MAPPING_SPECS
    )


def test_migration_removes_only_retired_data_and_options() -> None:
    data = {
        "operating_mode": "OBSERVE",
        "diagnostics_enabled": False,
        "grid_status_entity": "binary_sensor.grid",
        "pool_thermostat_entity": "climate.pool",
        **{key: f"data:{key}" for key in RETIRED_KEYS},
    }
    options = {
        "preferred_filtration_catchup_start": "21:15",
        "intellicenter_host": "controller.local",
        "intellicenter_transport": "tcp",
        "pump_rpm_entity": "sensor.pump_rpm",
        **{key: f"option:{key}" for key in RETIRED_KEYS},
    }
    entry = SimpleNamespace(version=2, minor_version=0, data=data, options=options)
    hass = _hass()

    assert MIGRATION.migrate_config_entry(hass, entry) is True
    assert len(hass.config_entries.updates) == 1
    updated_entry, changes = hass.config_entries.updates[0]
    assert updated_entry is entry
    assert changes == {
        "data": {
            "operating_mode": "OBSERVE",
            "diagnostics_enabled": False,
            "grid_status_entity": "binary_sensor.grid",
            "pool_thermostat_entity": "climate.pool",
        },
        "options": {
            "preferred_filtration_catchup_start": "21:15",
            "intellicenter_host": "controller.local",
            "intellicenter_transport": "tcp",
            "pump_rpm_entity": "sensor.pump_rpm",
        },
        "version": 2,
        "minor_version": 1,
    }


def test_migration_is_idempotent_and_rejects_unsupported_schema_versions() -> None:
    current = SimpleNamespace(
        version=2,
        minor_version=1,
        data={"operating_mode": "OBSERVE"},
        options={"diagnostics_enabled": True},
    )
    hass = _hass()

    assert MIGRATION.migrate_config_entry(hass, current) is True
    assert hass.config_entries.updates == []

    for entry in (
        SimpleNamespace(version=1, minor_version=0, data={}, options={}),
        SimpleNamespace(version=3, minor_version=0, data={}, options={}),
        SimpleNamespace(version=2, minor_version=2, data={}, options={}),
    ):
        assert MIGRATION.migrate_config_entry(hass, entry) is False
    assert hass.config_entries.updates == []


def test_config_flow_and_supported_migration_publish_schema_2_1() -> None:
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    integration = (COMPONENT / "__init__.py").read_text(encoding="utf-8")

    assert CONST.CONFIG_ENTRY_VERSION == 2
    assert CONST.CONFIG_ENTRY_MINOR_VERSION == 1
    assert "VERSION = CONFIG_ENTRY_VERSION" in flow
    assert "MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION" in flow
    assert "async def async_migrate_entry(" in integration
    assert "return migrate_config_entry(hass, entry)" in integration


def test_native_concepts_remain_without_circular_ha_mapping() -> None:
    concepts = {concept.value for concept in OBSERVATION.ObservationConcept}
    expected = {
        "freeze.active",
        "intellicenter.firmware_version",
        "intellicenter.system_mode",
        "intellichlor.pool_output_percent",
        "intellichlor.salt_ppm",
        "intellichlor.spa_output_percent",
        "pool.maximum_temperature",
        "pump.maximum_rpm",
        "pump.minimum_rpm",
        "spa.maximum_temperature",
    }
    assert expected <= concepts
    assert RETIRED_KEYS.isdisjoint(
        spec.option_key for spec in OBSERVATION.MAPPING_SPECS
    )

    native_surface = "\n".join(
        (COMPONENT / filename).read_text(encoding="utf-8")
        for filename in ("sensor.py", "binary_sensor.py", "number.py")
    )
    for concept in expected:
        assert concept in native_surface
    assert "async_set_intellichlor_output" in (
        COMPONENT / "number.py"
    ).read_text(encoding="utf-8")


def test_absent_retired_parity_inputs_are_deterministic_missing_reference_only() -> None:
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    native_concepts = (
        "freeze.active",
        "intellicenter.firmware_version",
        "intellicenter.system_mode",
        "intellichlor.pool_output_percent",
        "intellichlor.salt_ppm",
        "intellichlor.spa_output_percent",
        "pool.maximum_temperature",
        "pump.maximum_rpm",
        "pump.minimum_rpm",
        "spa.maximum_temperature",
    )
    native = tuple(
        PoolObservation(
            observation_id=concept,
            value=False,
            observed_at=now,
            source_kind=ObservationSourceKind.LIVE,
            source_id=f"intellicenter_native:test:{concept}",
            quality=ObservationQuality.GOOD,
        )
        for concept in native_concepts
    )

    report = ObservationParityEngine().compare(
        (),
        native,
        generated_at=now,
        ha_source_available=True,
        native_source_available=True,
    )

    assert report.native_source_available is True
    assert report.missing_ha_count == len(native_concepts)
    assert report.match_count == 0
    assert report.mismatch_count == 0
    assert {detail.status for detail in report.details} == {
        ObservationParityStatus.MISSING_HA
    }
