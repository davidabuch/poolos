"""Home Assistant commissioning contracts for the 11.3B durable recorder."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_113b_files_and_adr_exist() -> None:
    assert (ROOT / "poolos" / "observations" / "persistent.py").is_file()
    assert (ROOT / "tests" / "test_persistent_observation_recorder.py").is_file()
    assert (ROOT / "docs" / "adr" / "ADR-084-persistent-observation-event-recorder.md").is_file()


def test_manifest_advances_to_070_and_matching_core_tag() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0"
    ]
    assert manifest["iot_class"] == "calculated"


def test_solar_learning_inputs_are_available_as_optional_mappings() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    translation = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    for token in ("CONF_SOLAR_TEMPERATURE_ENTITY", "CONF_AIR_TEMPERATURE_ENTITY"):
        assert token in const
        assert token in observation
        assert token in flow
    assert 'SOLAR_TEMPERATURE = "solar.temperature"' in observation
    assert 'AIR_TEMPERATURE = "air.temperature"' in observation
    config_data = translation["config"]["step"]["user"]["data"]
    assert "solar_temperature_entity" in config_data
    assert "air_temperature_entity" in config_data
    assert 'VERSION = 2' in flow
    assert 'vol.Required(\n            CONF_DIAGNOSTICS_ENABLED,' in flow


def test_coordinator_persists_off_event_loop_and_fails_open() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "PersistentObservationRecorder" in source
    assert 'hass.config.path(".storage", DOMAIN, entry.entry_id)' in source
    assert 'PersistentObservationRecorder(storage_root / "observations")' in source
    assert "async_add_executor_job" in source
    assert "partial(" in source
    assert "except (OSError, TypeError, ValueError)" in source
    assert "return snapshot" in source
    assert '"persistent_observation_recorder": self.observation_recorder.diagnostics()' in source


def test_113b_preserves_no_actuation_boundary() -> None:
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
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert '"command_delivery_enabled": False' in coordinator


def test_component_python_still_parses() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_roadmap_marks_113b_done_and_113c_next() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.3B | Persistent observation + event recorder | DONE |" in roadmap
    assert "| 11.3C | Behavioral inference engine | DONE |" in roadmap
    assert "unchanged 30-second polls" in roadmap
