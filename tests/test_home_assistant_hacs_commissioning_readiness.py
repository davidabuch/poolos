"""HACS packaging and current PoolOS runtime safety contract tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
EXPECTED_VERSION = "1.0.25"
EXPECTED_CORE_REQUIREMENT = "poolos@git+https://github.com/davidabuch/poolos.git@v1.0.25"
EXPECTED_PROTOCOL_REQUIREMENT = "pyintellicenter==0.1.20"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_hacs_root_metadata_and_brand_asset_exist() -> None:
    assert _json(ROOT / "hacs.json") == {"name": "PoolOS"}
    icon = COMPONENT / "brand" / "icon.png"
    assert icon.is_file()
    assert icon.stat().st_size > 0


def test_repository_contains_exactly_one_hacs_integration() -> None:
    directories = sorted(path.name for path in (ROOT / "custom_components").iterdir() if path.is_dir())
    assert directories == ["poolos"]


def test_manifest_is_hacs_complete_and_release_pinned() -> None:
    manifest = _json(COMPONENT / "manifest.json")
    for key in ("domain", "documentation", "issue_tracker", "codeowners", "name", "version", "iot_class"):
        assert key in manifest
    assert manifest["domain"] == "poolos"
    assert manifest["version"] == EXPECTED_VERSION
    assert manifest["iot_class"] == "local_push"
    assert manifest["requirements"] == [
        EXPECTED_CORE_REQUIREMENT,
        EXPECTED_PROTOCOL_REQUIREMENT,
    ]
    assert "@main" not in EXPECTED_CORE_REQUIREMENT


def test_manifest_and_runtime_version_remain_synchronized() -> None:
    manifest = _json(COMPONENT / "manifest.json")
    source = (COMPONENT / "const.py").read_text(encoding="utf-8")
    assert f'INTEGRATION_VERSION = "{manifest["version"]}"' in source


def test_component_only_publishes_read_only_diagnostic_platforms() -> None:
    source = (COMPONENT / "const.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ("sensor", "binary_sensor", "button", "climate", "switch", "light", "number", "select")' in source
    prohibited = {"services.yaml"}
    assert not any((COMPONENT / name).exists() for name in prohibited)


def test_component_registers_no_home_assistant_service_calls() -> None:
    prohibited_calls = (
        "hass.services.async_call",
        "hass.services.call",
        "hass.services.async_register",
        "hass.services.register",
        "services.async_register",
        "service_registry",
    )
    for path in COMPONENT.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert all(token not in source for token in prohibited_calls), path.name


def test_control_status_reports_scoped_runtime_instead_of_global_disabled_flag() -> None:
    source = (COMPONENT / "control_status.py").read_text(encoding="utf-8")
    health = (COMPONENT / "system_health.py").read_text(encoding="utf-8")
    assert '"SCOPED_LIVE"' in source
    assert '"MANUAL_CONTROL"' in source
    assert '"OBSERVE_ONLY"' in source
    assert '"autonomous_domains"' in source
    assert "runtime_control_status" in health


def test_legacy_observe_config_is_retired() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    assert 'RETIRED_LEGACY_RUNTIME_OPTIONS = frozenset({"operating_mode"})' in const
    assert "DEFAULT_OPERATING_MODE" not in const
    assert '"operating_mode":' not in flow


def test_all_component_python_modules_parse_after_packaging_changes() -> None:
    for path in COMPONENT.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_hacs_validation_workflow_runs_automatically_and_manually() -> None:
    workflow = (ROOT / ".github" / "workflows" / "hacs.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "- main" in workflow
    assert "category: integration" in workflow
    assert "hacs/action@main" in workflow
    assert "github.event.repository.private == false" in workflow


def test_hassfest_validation_runs_on_repository_changes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "hassfest.yml").read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "home-assistant/actions/hassfest@master" in workflow


def test_current_deployment_documentation_records_scoped_live_boundary() -> None:
    guide = (ROOT / "docs" / "HOME_ASSISTANT_HACS_COMMISSIONING.md").read_text(encoding="utf-8")
    lowered = guide.lower()
    assert "scoped live control" in lowered
    assert "manual_control" in lowered
    assert "observe_only" in lowered
    assert "maintenance mode" in lowered
    assert "physical-control domains" in lowered


def test_adr_records_single_source_core_and_pinned_release_strategy() -> None:
    adr = (ROOT / "docs" / "adr" / "ADR-083-hacs-packaging-and-safe-ha-commissioning.md").read_text(encoding="utf-8")
    lowered = adr.lower()
    assert "single-sourced" in lowered
    assert "poolos@git+https://github.com/davidabuch/poolos.git@v0.6.0" in adr
    assert "authority `none`" in lowered
    assert "command delivery disabled" in lowered
