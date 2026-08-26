"""Commissioning contracts for 11.4A high-fidelity observation."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_114a_version_and_adr() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0",
        "pyintellicenter==0.1.20",
    ]
    assert (ROOT / "docs" / "adr" / "ADR-087-high-fidelity-event-driven-observation.md").is_file()


def test_learning_critical_sources_are_required() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    for token in (
        "CONF_POOL_THERMOSTAT_ENTITY",
        "CONF_SPA_THERMOSTAT_ENTITY",
        "CONF_PUMP_RPM_ENTITY",
        "CONF_PUMP_GPM_ENTITY",
        "CONF_PUMP_POWER_ENTITY",
        "CONF_WATER_TEMPERATURE_ENTITY",
        "CONF_SOLAR_TEMPERATURE_ENTITY",
        "CONF_AIR_TEMPERATURE_ENTITY",
        "CONF_SOLAR_ACTIVE_ENTITY",
        "CONF_HEATER_ACTIVE_ENTITY",
        "CONF_POOL_COMMAND_ENTITY",
        "CONF_SPA_COMMAND_ENTITY",
    ):
        assert token in const
    assert "CONF_SOLAR_PREFERRED_ENTITY" not in const
    assert "CONF_WATERFALL_ACTIVE_ENTITY" in const
    assert "CONF_JETS_ACTIVE_ENTITY" in const
    assert "CONF_SLIDE_ACTIVE_ENTITY" in const


def test_thermostat_semantics_separate_body_enabled_from_heating_demand() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert 'POOL_ACTIVE = "pool.active"' in source
    assert 'SPA_ACTIVE = "spa.active"' in source
    assert 'POOL_HEATING_DEMAND_ACTIVE = "pool.heating_demand_active"' in source
    assert 'SPA_HEATING_DEMAND_ACTIVE = "spa.heating_demand_active"' in source
    assert '"Status"' in source
    assert '"hvac_action"' in source
    assert '"heating": True' in source
    assert '"idle": False' in source
    assert '"off": False' in source
    assert 'POOL_RAW_HEATER_ID = "pool.raw_heater_id"' in source
    assert 'POOL_RAW_HTMODE = "pool.raw_htmode"' in source
    assert "freshness_required: bool = False" in source
    assert "spec.freshness_required" in source


def test_attribute_level_provenance_is_first_class() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    core = (ROOT / "poolos" / "homeassistant" / "observations.py").read_text(encoding="utf-8")
    assert "attribute=spec.attribute" in source
    assert 'f"{source_id}#{spec.attribute}"' in source
    assert "value_map=spec.boolean_map" in source
    assert "value_map: Mapping[str, Any] | None = None" in core
    assert "last_reported: datetime | None = None" in core


def test_event_driven_observation_and_periodic_reconciliation_coexist() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    setup = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert "async_track_state_change_event" in coordinator
    assert "configured_entity_ids" in coordinator
    assert "self._async_mapped_state_changed" in coordinator
    assert 'trigger="state_change_event"' in coordinator
    assert 'trigger="periodic_reconciliation"' in coordinator
    assert "self._observation_lock = asyncio.Lock()" in coordinator
    assert "coordinator.async_activate_post_start()" in setup
    assert "async_handle_homeassistant_started" in setup
    assert "await async_activate_poolos_post_start()" in setup
    assert "self.async_start_event_observation()" in coordinator
    assert "entry.async_on_unload(coordinator.async_stop_event_observation)" in setup
    assert '"event_driven_observation_enabled"' in coordinator
    assert '"periodic_reconciliation_enabled": True' in coordinator


def test_expensive_analysis_is_decoupled_from_observation_critical_path() -> None:
    """Derived history analysis must not block serialized observation cadence."""

    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    observe = coordinator.split(
        "async def _async_observe(",
        1,
    )[1].split(
        "def _refresh_native_intellicenter_parity(",
        1,
    )[0]

    worker = coordinator.split(
        "async def _async_analysis_worker(",
        1,
    )[1].split(
        "async def async_stop_independent_intellicenter(",
        1,
    )[0]

    # Primary observation still persists significant evidence.
    assert "self.observation_recorder.record_snapshot" in observe

    # Expensive derived analysis is only scheduled from the observation path.
    assert "self._async_schedule_analysis(snapshot.generated_at)" in observe
    assert "self._infer_and_retro" not in observe

    # The separate serialized worker owns derived inference/retrospective work.
    assert "self._infer_and_retro" in worker
    assert "async_add_executor_job" in worker


def test_significance_policy_bounds_high_frequency_numeric_noise() -> None:
    source = (ROOT / "poolos" / "observations" / "persistent.py").read_text(encoding="utf-8")
    assert '"pump.rpm": 25.0' in source
    assert '"pump.gpm": 1.0' in source
    assert '"pump.power": 50.0' in source
    assert '"water.temperature": 0.1' in source


def test_schedules_and_preset_speeds_are_not_commissioning_inputs() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8").lower()
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8").lower()
    for forbidden in ("schedule_entity", "solar_rpm", "heat_rpm", "pool_rpm"):
        assert forbidden not in const
        assert forbidden not in flow


def test_114a_preserves_no_actuation_boundary() -> None:
    prohibited = (
        "hass.services.async_call",
        "hass.services.call",
        "services.async_register",
        "switch.turn_on",
        "switch.turn_off",
        "climate.set_hvac_mode",
        "climate.turn_on",
        "climate.turn_off",
    )
    for path in COMPONENT.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert all(token not in source for token in prohibited), path.name
    assert '"command_delivery_enabled": False' in (COMPONENT / "coordinator.py").read_text(encoding="utf-8")


def test_114a_component_python_parses_and_roadmap_records_milestone() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.4A | High-fidelity observation coverage + event-driven ingestion | DONE |" in roadmap


def test_freshness_is_state_aware_for_idle_circulation_telemetry() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert "def _freshness_required_now(" in source
    assert "circulation_expected = any(" in source
    assert "ObservationConcept.POOL_COMMAND_ACTIVE" in source
    assert "ObservationConcept.SPA_COMMAND_ACTIVE" in source
    assert "ObservationConcept.WATERFALL_ACTIVE" in source
    assert "ObservationConcept.JETS_ACTIVE" in source
    assert "ObservationConcept.SLIDE_ACTIVE" in source
    assert "if concept is ObservationConcept.POOL_TEMPERATURE:" in source
    assert "return pool_active" in source
    assert "if concept is ObservationConcept.SPA_TEMPERATURE:" in source
    assert "return spa_active" in source
    for concept in (
        "ObservationConcept.PUMP_RPM",
        "ObservationConcept.PUMP_GPM",
        "ObservationConcept.PUMP_POWER",
        "ObservationConcept.WATER_TEMPERATURE",
    ):
        assert concept in source
    assert "return circulation_expected" in source


def test_idle_retained_values_are_not_globally_declared_stale_by_static_policy() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert "freshness_candidates" in source
    assert "_freshness_required_now(spec.concept, observation_values)" in source
    assert "if not _freshness_required_now" in source


def test_environmental_probe_age_does_not_fail_global_health() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    solar_line = next(line for line in source.splitlines() if "CONF_SOLAR_TEMPERATURE_ENTITY" in line and "EntityMappingSpec" in line)
    air_line = next(line for line in source.splitlines() if "CONF_AIR_TEMPERATURE_ENTITY" in line and "EntityMappingSpec" in line)
    assert "freshness_required=True" not in solar_line
    assert "freshness_required=True" not in air_line
    assert 'ObservationConcept.SOLAR_TEMPERATURE' in solar_line
    assert 'ObservationConcept.AIR_TEMPERATURE' in air_line


def test_powerwall_grid_status_is_required_read_only_observation() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    translations = (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    assert 'CONF_GRID_STATUS_ENTITY = "grid_status_entity"' in const
    assert 'CONF_GRID_STATUS_ENTITY: ["binary_sensor"]' in flow
    assert 'GRID_AVAILABLE = "grid.available"' in observation
    assert 'GRID_OUTAGE_ACTIVE = "grid.outage_active"' in observation
    assert 'GRID_AVAILABLE_MAP = MappingProxyType({"on": True, "off": False})' in observation
    assert 'GRID_OUTAGE_MAP = MappingProxyType({"on": False, "off": True})' in observation
    assert "Powerwall grid status entity (1_Powerwall)" in translations


def test_grid_observation_adds_no_outage_actuation() -> None:
    component_source = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in COMPONENT.glob("*.py")
    )
    assert "1800" not in component_source
    assert "hass.services.async_call" not in component_source
    assert "switch.turn_off" not in component_source


def test_pool_light_observation_contract() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert 'CONF_POOL_LIGHT_ENTITY = "pool_light_entity"' in const
    assert 'CONF_POOL_LIGHT_ENTITY: ["light"]' in flow
    for concept in ("pool_light.active", "pool_light.color_mode", "pool_light.effect"):
        assert concept in observation


def test_pool_light_optional_metadata_does_not_fail_observation_health() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert "quality_required: bool = True" in source
    assert 'ObservationConcept.POOL_LIGHT_COLOR_MODE, HomeAssistantValueType.STRING, None, True, "color_mode", quality_required=False' in source
    assert 'ObservationConcept.POOL_LIGHT_EFFECT, HomeAssistantValueType.STRING, None, True, "effect_code", quality_required=False' in source


def test_stale_available_values_are_warning_not_global_health_failure() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    healthy_body = source.split("def healthy", 1)[1].split("def diagnostics", 1)[0]
    assert "not self.missing_required and not self.unavailable_entities" in healthy_body
    assert "not self.stale_entities" not in healthy_body
    assert '"freshness_warning": bool(self.stale_entities)' in source


def test_shadow_runtime_tolerates_partial_startup_snapshot() -> None:
    source = (COMPONENT / "shadow.py").read_text(encoding="utf-8")
    assert "ShadowRuntimeResult | None" in source
    assert "if any(key not in facts or facts[key] is None for key in required):" in source
    assert "return None" in source


def test_native_intellicenter_push_propagation_contract() -> None:
    """Native snapshots must have an immediate coordinator propagation path."""
    coordinator = (
        Path("custom_components/poolos/coordinator.py")
        .read_text()
    )

    assert "self._native_intellicenter_refresh_task" in coordinator
    assert "transport._set_snapshot_update_callback(" in coordinator
    assert "self._async_schedule_native_intellicenter_refresh" in coordinator
    assert (
        "async def _async_native_intellicenter_snapshot_updated(self)"
        in coordinator
    )
    assert 'trigger="native_intellicenter_update"' in coordinator
    assert "self.async_set_updated_data(snapshot)" in coordinator


def test_native_intellicenter_push_propagation_uses_observation_lock() -> None:
    """Native propagation must serialize with all other observations."""
    coordinator = (
        Path("custom_components/poolos/coordinator.py")
        .read_text()
    )

    method = coordinator.split(
        "async def _async_native_intellicenter_snapshot_updated(self)",
        1,
    )[1].split(
        "async def async_stop_independent_intellicenter",
        1,
    )[0]

    assert "async with self._observation_lock:" in method
    assert "self._event_refresh_count += 1" in method
    assert "await self._async_observe(" in method
    assert 'trigger="native_intellicenter_update"' in method
    assert "self.async_set_updated_data(snapshot)" in method


def test_native_intellicenter_push_callback_is_removed_on_stop() -> None:
    """Unload must detach the transport callback and cancel propagation work."""
    coordinator = (
        Path("custom_components/poolos/coordinator.py")
        .read_text()
    )

    method = coordinator.split(
        "async def async_stop_independent_intellicenter(self)",
        1,
    )[1].split(
        "def async_start_event_observation",
        1,
    )[0]

    assert "transport._set_snapshot_update_callback(None)" in method
    assert "refresh_task.cancel()" in method
    assert "await refresh_task" in method
