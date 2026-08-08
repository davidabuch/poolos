"""Contract tests for the PoolOS Home Assistant shadow runtime."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_shadow_runtime_files_exist() -> None:
    assert (COMPONENT / "shadow.py").is_file()
    assert (ROOT / "poolos" / "shadow_runtime.py").is_file()
    assert (ROOT / "docs" / "adr" / "ADR-076-home-assistant-shadow-runtime.md").is_file()


def test_component_modules_parse() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_manifest_advances_shadow_runtime_version() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.10.0"
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0"
    ]


def test_coordinator_evaluates_shadow_after_snapshot() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "HomeAssistantShadowRuntime.create()" in source
    assert "self.shadow_runtime.evaluate(snapshot)" in source
    assert '"shadow_runtime_enabled": True' in source
    assert '"command_delivery_enabled": False' in source


def test_shadow_adapter_uses_canonical_observation_snapshot() -> None:
    source = (COMPONENT / "shadow.py").read_text(encoding="utf-8")
    assert "ObservationSnapshot" in source
    assert "ShadowRuntimeInput" in source
    assert "observation_fingerprint" in source


def test_diagnostics_include_shadow_status_without_control() -> None:
    source = (COMPONENT / "diagnostics.py").read_text(encoding="utf-8")
    assert '"shadow_runtime"' in source
    assert '"shadow_runtime_enabled"' in source
    assert '"command_delivery_enabled": False' in source


def test_no_control_platform_or_service_is_added() -> None:
    prohibited = {"switch.py", "number.py", "select.py", "climate.py", "services.yaml"}
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_roadmap_records_11_1d_as_done_and_non_actuating() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.1D | Read-only shadow runtime | DONE |" in roadmap
    assert "invokes no execution proposal" in roadmap
