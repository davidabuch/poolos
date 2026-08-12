"""Contract tests for PoolOS Home Assistant observation commissioning."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_observation_bridge_files_exist() -> None:
    assert (COMPONENT / "observation.py").is_file()
    assert (ROOT / "docs" / "adr" / "ADR-075-home-assistant-observation-bridge.md").is_file()


def test_all_component_python_modules_parse() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_manifest_advances_observation_bridge_version() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0",
        "pyintellicenter==0.1.20",
    ]
    assert manifest["single_config_entry"] is True


def test_config_flow_exposes_required_and_optional_entity_mappings() -> None:
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    for key in (
        "CONF_POOL_THERMOSTAT_ENTITY",
        "CONF_SPA_THERMOSTAT_ENTITY",
        "CONF_PUMP_RPM_ENTITY",
        "CONF_PUMP_GPM_ENTITY",
        "CONF_PUMP_POWER_ENTITY",
        "CONF_WATER_TEMPERATURE_ENTITY",
        "CONF_HEATER_ACTIVE_ENTITY",
        "CONF_SOLAR_ACTIVE_ENTITY",
        "CONF_SOLAR_TEMPERATURE_ENTITY",
        "CONF_AIR_TEMPERATURE_ENTITY",
        "CONF_POOL_COMMAND_ENTITY",
        "CONF_SPA_COMMAND_ENTITY",
    ):
        assert key in source
    assert "EntitySelector" in source
    assert "DEFAULT_OPERATING_MODE" in source


def test_observation_mapping_uses_existing_canonical_models() -> None:
    source = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert "HomeAssistantObservationMapper" in source
    assert "HomeAssistantObservationBinding" in source
    assert "PoolObservation" in source
    assert "ObservationFreshness" in source
    assert "ObservationSnapshot" in source
    assert "MappingProxyType" in source


def test_coordinator_is_read_only_and_uses_home_assistant_state_machine() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "self.hass.states.get" in source
    assert "OBSERVATION_UPDATE_INTERVAL" in source
    assert '"observation_enabled": True' in source
    assert '"command_delivery_enabled": False' in source
    forbidden = (
        "services.async_call",
        "async_call(",
        "requests",
        "aiohttp",
        "websocket",
        "switch.turn_",
        "climate.set_",
    )
    assert all(token not in source for token in forbidden)


def test_diagnostics_report_mapping_health_without_state_values() -> None:
    source = (COMPONENT / "diagnostics.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    assert "snapshot.diagnostics()" in source
    assert '"observation_count"' in observation
    assert '"missing_required"' in observation
    assert '"unavailable_entities"' in observation
    assert '"stale_entities"' in observation
    assert '"value"' not in observation.split("def diagnostics", 1)[1].split("def configured_entity_mapping", 1)[0]


def test_runtime_translation_is_present_without_core_build_strings() -> None:
    assert not (COMPONENT / "strings.json").exists()
    translation = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert "config" in translation
    description = translation["config"]["step"]["user"]["description"]
    assert "OBSERVE" in description
    assert "cannot send commands" in description


def test_no_control_platform_or_service_is_added() -> None:
    prohibited = {
        "switch.py",
        "number.py",
        "select.py",
        "climate.py",
        "services.yaml",
    }
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_roadmap_records_11_1c_as_done_and_read_only() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.1C | Live observation bridge commissioning | DONE |" in roadmap
    assert "no Home Assistant service call" in roadmap
