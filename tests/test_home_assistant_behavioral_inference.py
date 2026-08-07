"""Home Assistant commissioning contracts for 11.3C behavioral inference."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_113c_core_and_adr_exist() -> None:
    assert (ROOT / "poolos" / "behavioral_inference.py").is_file()
    assert (ROOT / "tests" / "test_behavioral_inference.py").is_file()
    assert (ROOT / "docs" / "adr" / "ADR-085-behavioral-inference-engine.md").is_file()


def test_manifest_advances_to_080_and_matching_core_tag() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0"
    ]
    assert manifest["iot_class"] == "calculated"


def test_inference_runs_from_durable_history_off_event_loop() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "BehavioralInferenceEngine" in source
    assert "behavioral_inference_report" in source
    assert "self._record_infer_and_retro" in source
    assert "async_add_executor_job" in source
    assert "timedelta(days=7)" in source
    assert "self.observation_recorder.query" in source
    assert '"behavioral_inference": (' in source


def test_control_center_exposes_inference_as_read_only_diagnostics() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    assert '"inferred_operating_state"' in source
    assert '"solar_behavior_inference"' in source
    assert "current_state.value" in source
    assert "solar.assessment" in source


def test_hacs_validation_is_automatic_and_manual() -> None:
    workflow = (ROOT / ".github" / "workflows" / "hacs.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "workflow_dispatch:" in workflow
    assert "hacs/action@main" in workflow


def test_inference_language_stays_provisional() -> None:
    source = (ROOT / "poolos" / "behavioral_inference.py").read_text(encoding="utf-8")
    assert "provisional hysteresis pattern" in source
    assert "more repeated-day evidence is required" in source
    assert "controller threshold" in source


def test_113c_preserves_no_actuation_boundary() -> None:
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


def test_roadmap_marks_113c_done_and_113d_next() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.3C | Behavioral inference engine | DONE |" in roadmap
    assert "| 11.3D | Daily operational retrospective + counterfactual report | DONE |" in roadmap
    assert "provisional activation/deactivation differential" in roadmap
