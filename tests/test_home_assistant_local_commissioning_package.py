"""Local-only Home Assistant commissioning package contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
BUILDER = ROOT / "scripts" / "build_local_ha_package.py"


def test_local_vendor_bootstrap_runs_before_coordinator_import() -> None:
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert "_enable_local_vendored_core()" in source
    assert 'Path(__file__).resolve().parent / "_vendor"' in source
    assert source.index("_enable_local_vendored_core()") < source.index("from .coordinator import PoolOSCoordinator")


def test_source_manifest_remains_release_pinned_for_future_distribution() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requirements"] == [
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.0",
        "pyintellicenter==0.1.20",
    ]


def test_local_builder_produces_self_contained_custom_component(tmp_path: Path) -> None:
    output = tmp_path / "PoolOS_Local_HA_Commissioning.zip"
    subprocess.run(
        [sys.executable, str(BUILDER), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.is_file()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "custom_components/poolos/__init__.py" in names
        assert "custom_components/poolos/_vendor/poolos/__init__.py" in names
        assert "custom_components/poolos/LOCAL_COMMISSIONING.txt" in names
        manifest = json.loads(archive.read("custom_components/poolos/manifest.json"))
        assert manifest["requirements"] == ["pyintellicenter==0.1.20"]
        assert manifest["version"] == "0.10.0"
        assert not any("__pycache__" in name for name in names)
        assert not any(name.endswith((".pyc", ".pyo", ".DS_Store")) for name in names)
        assert not any("/.git/" in f"/{name}" or "/.venv/" in f"/{name}" for name in names)


def test_local_commissioning_documentation_preserves_observation_only_boundary() -> None:
    guide = (ROOT / "docs" / "LOCAL_HOME_ASSISTANT_COMMISSIONING.md").read_text(encoding="utf-8").lower()
    assert "authority: none" in guide
    assert "command delivery: disabled" in guide
    assert "control entities: none" in guide
    assert "existing intellicenter integration remains authoritative" in guide
