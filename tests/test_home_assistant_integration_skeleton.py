"""Contract tests for the PoolOS Home Assistant integration skeleton."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_required_integration_files_exist() -> None:
    expected = {
        "__init__.py",
        "config_flow.py",
        "const.py",
        "coordinator.py",
        "diagnostics.py",
        "manifest.json",
        "strings.json",
        "system_health.py",
        "translations/en.json",
    }
    assert {str(path.relative_to(COMPONENT)) for path in COMPONENT.rglob("*") if path.is_file() and "__pycache__" not in path.parts} == expected


def test_manifest_declares_safe_single_entry_config_flow() -> None:
    manifest = _read_json(COMPONENT / "manifest.json")
    assert manifest["domain"] == "poolos"
    assert manifest["name"] == "PoolOS"
    assert manifest["config_flow"] is True
    assert manifest["single_config_entry"] is True
    assert manifest["requirements"] == []
    assert manifest["version"] == "0.1.0"


def test_strings_and_english_translation_are_identical() -> None:
    assert _read_json(COMPONENT / "strings.json") == _read_json(
        COMPONENT / "translations" / "en.json"
    )


def test_all_python_modules_parse() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_config_flow_is_single_instance_and_observe_only() -> None:
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    assert "self._async_current_entries()" in source
    assert '"operating_mode": DEFAULT_OPERATING_MODE' in source
    assert "single_instance_allowed" in source
    assert "CONF_DIAGNOSTICS_ENABLED" in source
    assert "command" not in source.lower()


def test_setup_uses_runtime_data_and_idle_first_refresh() -> None:
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert "type PoolOSConfigEntry = ConfigEntry[PoolOSRuntimeData]" in source
    assert "entry.runtime_data = PoolOSRuntimeData" in source
    assert "async_config_entry_first_refresh" in source


def test_coordinator_performs_no_external_io_and_disables_actuation() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert "update_interval=None" in source
    assert '"observation_enabled": False' in source
    assert '"command_delivery_enabled": False' in source
    forbidden = ("aiohttp", "requests", "websocket", "async_track", "service_call")
    assert all(token not in source for token in forbidden)


def test_diagnostics_redact_future_connection_secrets() -> None:
    source = (COMPONENT / "diagnostics.py").read_text(encoding="utf-8")
    for key in ("access_token", "token", "api_key", "host", "url"):
        assert key in source
    assert "async_redact_data" in source


def test_no_entity_platform_or_service_files_are_present() -> None:
    prohibited = {
        "sensor.py",
        "binary_sensor.py",
        "switch.py",
        "number.py",
        "select.py",
        "climate.py",
        "services.yaml",
    }
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_adr_and_roadmap_record_no_operational_behavior() -> None:
    adr = (ROOT / "docs" / "adr" / "ADR-074-home-assistant-integration-skeleton.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "no entity discovery" in adr.lower()
    assert "no IntelliCenter discovery" in roadmap
    assert "| 11.1B | Home Assistant integration skeleton | DONE |" in roadmap
