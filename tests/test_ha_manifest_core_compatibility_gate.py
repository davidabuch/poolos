"""Regression coverage for the HA manifest/core deployment gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_ha_manifest_core_compatibility import (
    CompatibilityGateError,
    collect_poolos_attribute_references,
    collect_poolos_imports,
    manifest_poolos_requirement,
)


def test_live_manifest_uses_immutable_poolos_sha() -> None:
    requirement = manifest_poolos_requirement()
    revision = requirement.rsplit("@", 1)[1]
    assert len(revision) == 40
    assert set(revision) <= set("0123456789abcdef")


def test_gate_scans_known_integration_core_imports() -> None:
    imports = collect_poolos_imports()
    assert "poolos.filtration_policy" in imports
    assert "FiltrationSchedulingMode" in imports["poolos.filtration_policy"]
    assert "poolos.native_parity_commissioning" in imports
    assert (
        "NativeParityCommissioningStore"
        in imports["poolos.native_parity_commissioning"]
    )


def test_gate_rejects_mutable_poolos_requirement(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"requirements": ['
        '"poolos@git+https://github.com/davidabuch/poolos.git@main"'
        ']}',
        encoding="utf-8",
    )
    with pytest.raises(CompatibilityGateError, match="immutable"):
        manifest_poolos_requirement(manifest)


def test_gate_scans_referenced_enum_members() -> None:
    attributes = collect_poolos_attribute_references()
    assert (
        "poolos.physical_command_authority",
        "AutomaticThermalDispatchPurpose",
        "SPA_EXIT_POOL_RESTORE_CLEANUP",
    ) in attributes
