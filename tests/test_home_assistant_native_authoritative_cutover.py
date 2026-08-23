"""Contracts and behavioral tests for the PoolOS C5.9 native-authoritative cutover."""

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from poolos.homeassistant.observations import HomeAssistantState
from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"

TEST_PACKAGE = "_poolos_component_c59_test"


def _load_component_module(module_name: str) -> ModuleType:
    """Load a PoolOS component module without executing custom_components.poolos.__init__."""

    if TEST_PACKAGE not in sys.modules:
        package = ModuleType(TEST_PACKAGE)
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        package.__package__ = TEST_PACKAGE
        sys.modules[TEST_PACKAGE] = package

    qualified = f"{TEST_PACKAGE}.{module_name}"

    existing = sys.modules.get(qualified)
    if existing is not None:
        return existing

    path = COMPONENT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


_AUTHORITATIVE = _load_component_module("authoritative")
_CONST = _load_component_module("const")

build_authoritative_snapshot = _AUTHORITATIVE.build_authoritative_snapshot

CONF_GRID_STATUS_ENTITY = _CONST.CONF_GRID_STATUS_ENTITY
CONF_POOL_LIGHT_ENTITY = _CONST.CONF_POOL_LIGHT_ENTITY
CONF_POOL_THERMOSTAT_ENTITY = _CONST.CONF_POOL_THERMOSTAT_ENTITY


def test_authoritative_composer_exists() -> None:
    source = (COMPONENT / "authoritative.py").read_text(encoding="utf-8")

    assert "def build_authoritative_snapshot(" in source
    assert 'authoritative_source="native_intellicenter"' in source
    assert '"poolos.independent_intellicenter"' in source


def test_authoritative_composer_has_no_legacy_pentair_fallback() -> None:
    source = (COMPONENT / "authoritative.py").read_text(encoding="utf-8")

    assert "There is intentionally no fallback" in source
    assert "combined.setdefault(observation.observation_id, observation)" in source
    assert "configured_entity_mapping(options)" in source


def test_grid_remains_required_external_ha_truth() -> None:
    source = (COMPONENT / "authoritative.py").read_text(encoding="utf-8")

    assert "AUTHORITATIVE_REQUIRED_EXTERNAL_CONCEPTS" in source
    assert "ObservationConcept.GRID_AVAILABLE.value" in source
    assert "ObservationConcept.GRID_OUTAGE_ACTIVE.value" in source
    assert "CONF_GRID_STATUS_ENTITY" in source


def test_pool_light_active_is_native_but_metadata_can_remain_external() -> None:
    source = (COMPONENT / "authoritative.py").read_text(encoding="utf-8")

    assert "ObservationConcept.POOL_LIGHT_ACTIVE.value" in source
    assert "ObservationConcept.POOL_LIGHT_COLOR_MODE" in source
    assert "ObservationConcept.POOL_LIGHT_EFFECT" in source
    assert "Pool-light on/off state is native-authoritative" in source


def test_coordinator_preserves_ha_snapshot_only_for_parity() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert "ha_shadow_snapshot = build_snapshot(" in source
    assert "self._refresh_native_intellicenter_parity(" in source
    assert "ha_shadow_snapshot," in source
    assert "snapshot = build_authoritative_snapshot(" in source
    assert "native_snapshot=self.native_intellicenter_snapshot" in source


def test_config_flow_requires_only_external_grid_binding() -> None:
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    required_block = source.split("    required = {", 1)[1].split(
        "    optional = {", 1
    )[0]

    assert "CONF_GRID_STATUS_ENTITY" in required_block
    assert "CONF_POOL_THERMOSTAT_ENTITY" not in required_block
    assert "CONF_SPA_THERMOSTAT_ENTITY" not in required_block
    assert "CONF_PUMP_RPM_ENTITY" not in required_block


def test_snapshot_diagnostics_identify_authoritative_source() -> None:
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")

    assert 'authoritative_source: str = "home_assistant"' in observation
    assert '"authoritative_source": self.authoritative_source' in observation
    assert '"authoritative_source": diagnostics.get(' in sensor


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
GRID_ENTITY = "binary_sensor.test_grid"
POOL_CLIMATE_ENTITY = "climate.legacy_pool"
POOL_LIGHT_ENTITY = "light.legacy_pool_light"


_REQUIRED_NATIVE_DEFAULTS: dict[str, object] = {
    "pool.active": False,
    "spa.active": False,
    "pool.heating_demand_active": False,
    "spa.heating_demand_active": False,
    "pool.command_active": False,
    "spa.command_active": False,
    "pump.rpm": 0.0,
    "pump.power": 0.0,
    "pool.temperature": 86.0,
    "spa.temperature": 86.0,
    "water.temperature": 86.0,
    "pool.target_temperature": 90.0,
    "spa.target_temperature": 98.0,
    "solar.temperature": 70.0,
    "air.temperature": 72.0,
    "heater.active": False,
    "solar.active": False,
    "pool_light.active": False,
    "pool.raw_heater_id": "H0002",
    "spa.raw_heater_id": "H0001",
    "pool.raw_htmode": "0",
    "spa.raw_htmode": "0",
}


def _native_observation(
    concept: str,
    value: object,
    *,
    observed_at: datetime = NOW,
) -> PoolObservation:
    return PoolObservation(
        observation_id=concept,
        value=value,
        observed_at=observed_at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"intellicenter_native:test:{concept}",
        quality=ObservationQuality.GOOD,
    )


def _native_snapshot(
    *,
    overrides: dict[str, object] | None = None,
    observed_at_by_concept: dict[str, datetime] | None = None,
    extra: dict[str, object] | None = None,
) -> NativeIntelliCenterObservationSnapshot:
    values = dict(_REQUIRED_NATIVE_DEFAULTS)
    values.update(overrides or {})
    values.update(extra or {})

    times = observed_at_by_concept or {}

    observations = tuple(
        _native_observation(
            concept,
            value,
            observed_at=times.get(concept, NOW),
        )
        for concept, value in values.items()
    )

    return NativeIntelliCenterObservationSnapshot(
        generated_at=NOW,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="poolos.independent_intellicenter",
        observations=observations,
        missing_concepts=(),
    )


def _ha_state(
    entity_id: str,
    state: str,
    *,
    attributes: dict[str, object] | None = None,
) -> HomeAssistantState:
    return HomeAssistantState(
        entity_id=entity_id,
        state=state,
        last_changed=NOW,
        last_updated=NOW,
        last_reported=NOW,
        attributes=attributes or {},
    )


def _grid_options(**extra: str) -> dict[str, str]:
    return {
        CONF_GRID_STATUS_ENTITY: GRID_ENTITY,
        **extra,
    }


def _observations_by_concept(snapshot: Any) -> dict[str, PoolObservation]:
    return {item.observation_id: item for item in snapshot.observations}


def test_behavior_native_controller_value_is_authoritative_over_legacy_ha() -> None:
    native = _native_snapshot(
        overrides={
            "pool.temperature": 86.0,
            "water.temperature": 86.0,
        }
    )

    options = _grid_options(
        **{CONF_POOL_THERMOSTAT_ENTITY: POOL_CLIMATE_ENTITY}
    )

    states = {
        GRID_ENTITY: _ha_state(GRID_ENTITY, "on"),
        POOL_CLIMATE_ENTITY: _ha_state(
            POOL_CLIMATE_ENTITY,
            "heat",
            attributes={
                "current_temperature": 99.0,
                "temperature": 99.0,
            },
        ),
    }

    snapshot = build_authoritative_snapshot(
        native_snapshot=native,
        options=options,
        states=states,
        now=NOW,
    )

    observations = _observations_by_concept(snapshot)
    pool_temperature = observations["pool.temperature"]

    assert pool_temperature.value == 86.0
    assert pool_temperature.source_id == "intellicenter_native:test:pool.temperature"
    assert snapshot.authoritative_source == "native_intellicenter"


def test_behavior_grid_truth_is_still_supplied_by_home_assistant() -> None:
    snapshot = build_authoritative_snapshot(
        native_snapshot=_native_snapshot(),
        options=_grid_options(),
        states={GRID_ENTITY: _ha_state(GRID_ENTITY, "on")},
        now=NOW,
    )

    observations = _observations_by_concept(snapshot)

    assert observations["grid.available"].value is True
    assert observations["grid.outage_active"].value is False
    assert observations["grid.available"].source_id == f"home_assistant:{GRID_ENTITY}"


def test_behavior_missing_native_has_no_legacy_pentair_fallback() -> None:
    options = _grid_options(
        **{CONF_POOL_THERMOSTAT_ENTITY: POOL_CLIMATE_ENTITY}
    )

    states = {
        GRID_ENTITY: _ha_state(GRID_ENTITY, "on"),
        POOL_CLIMATE_ENTITY: _ha_state(
            POOL_CLIMATE_ENTITY,
            "heat",
            attributes={
                "current_temperature": 99.0,
                "temperature": 99.0,
            },
        ),
    }

    snapshot = build_authoritative_snapshot(
        native_snapshot=None,
        options=options,
        states=states,
        now=NOW,
    )

    observations = _observations_by_concept(snapshot)

    assert "pool.temperature" not in observations
    assert "pool.temperature" in snapshot.missing_required
    assert "poolos.independent_intellicenter" in snapshot.unavailable_entities
    assert snapshot.healthy is False


def test_behavior_optional_native_features_can_be_absent_and_remain_healthy() -> None:
    snapshot = build_authoritative_snapshot(
        native_snapshot=_native_snapshot(),
        options=_grid_options(),
        states={GRID_ENTITY: _ha_state(GRID_ENTITY, "on")},
        now=NOW,
    )

    observations = _observations_by_concept(snapshot)

    for optional in (
        "pump.gpm",
        "waterfall.active",
        "jets.active",
        "slide.active",
    ):
        assert optional not in observations
        assert optional not in snapshot.missing_required

    assert snapshot.missing_required == ()
    assert snapshot.unavailable_entities == ()
    assert snapshot.stale_entities == ()
    assert snapshot.healthy is True


def test_behavior_actual_running_pump_requires_fresh_circulation_data() -> None:
    old = NOW - timedelta(minutes=10)

    native = _native_snapshot(
        overrides={
            "pool.active": False,
            "spa.active": False,
            "pool.command_active": False,
            "spa.command_active": False,
            "solar.active": False,
            "heater.active": False,
            "pump.rpm": 2200.0,
            "pump.power": 900.0,
            "water.temperature": 84.0,
        },
        observed_at_by_concept={
            "pump.rpm": old,
            "pump.power": old,
            "water.temperature": old,
        },
    )

    snapshot = build_authoritative_snapshot(
        native_snapshot=native,
        options=_grid_options(),
        states={GRID_ENTITY: _ha_state(GRID_ENTITY, "on")},
        now=NOW,
        stale_after=timedelta(minutes=5),
    )

    assert "intellicenter_native:test:pump.rpm" in snapshot.stale_entities
    assert "intellicenter_native:test:pump.power" in snapshot.stale_entities
    assert "intellicenter_native:test:water.temperature" in snapshot.stale_entities

    # Freshness degradation is intentionally distinct from structural
    # observation health. The authoritative snapshot remains structurally
    # complete while explicitly reporting stale live-circulation evidence.
    assert snapshot.healthy is True
    assert snapshot.diagnostics()["freshness_warning"] is True


def test_behavior_stopped_pump_does_not_require_fresh_stagnant_water() -> None:
    old = NOW - timedelta(hours=2)

    native = _native_snapshot(
        overrides={
            "pool.active": False,
            "spa.active": False,
            "pool.command_active": False,
            "spa.command_active": False,
            "solar.active": False,
            "heater.active": False,
            "pump.rpm": 0.0,
            "pump.power": 0.0,
            "water.temperature": 79.0,
        },
        observed_at_by_concept={
            "pump.rpm": old,
            "pump.power": old,
            "water.temperature": old,
            "pool.temperature": old,
            "spa.temperature": old,
        },
    )

    snapshot = build_authoritative_snapshot(
        native_snapshot=native,
        options=_grid_options(),
        states={GRID_ENTITY: _ha_state(GRID_ENTITY, "on")},
        now=NOW,
        stale_after=timedelta(minutes=5),
    )

    assert snapshot.stale_entities == ()
    assert snapshot.healthy is True


def test_behavior_native_pool_light_state_coexists_with_ha_metadata() -> None:
    native = _native_snapshot(
        overrides={"pool_light.active": True}
    )

    options = _grid_options(
        **{CONF_POOL_LIGHT_ENTITY: POOL_LIGHT_ENTITY}
    )

    states = {
        GRID_ENTITY: _ha_state(GRID_ENTITY, "on"),
        POOL_LIGHT_ENTITY: _ha_state(
            POOL_LIGHT_ENTITY,
            "on",
            attributes={
                "color_mode": "hs",
                "effect": "Party",
            },
        ),
    }

    snapshot = build_authoritative_snapshot(
        native_snapshot=native,
        options=options,
        states=states,
        now=NOW,
    )

    observations = _observations_by_concept(snapshot)

    assert observations["pool_light.active"].value is True
    assert observations["pool_light.active"].source_id == (
        "intellicenter_native:test:pool_light.active"
    )

    assert observations["pool_light.color_mode"].value == "hs"
    assert observations["pool_light.effect"].value == "Party"
    assert observations["pool_light.color_mode"].source_id == (
        f"home_assistant:{POOL_LIGHT_ENTITY}#color_mode"
    )
    assert observations["pool_light.effect"].source_id == (
        f"home_assistant:{POOL_LIGHT_ENTITY}#effect"
    )
