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
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0"
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
    assert "CONF_SOLAR_PREFERRED_ENTITY" in const
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
    assert "coordinator.async_start_event_observation()" in setup
    assert "entry.async_on_unload(coordinator.async_stop_event_observation)" in setup
    assert '"event_driven_observation_enabled"' in coordinator
    assert '"periodic_reconciliation_enabled": True' in coordinator


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
