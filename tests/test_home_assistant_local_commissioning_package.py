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
        "poolos@git+https://github.com/davidabuch/poolos.git@v0.10.1",
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
        assert manifest["version"] == "0.10.1"
        assert not any("__pycache__" in name for name in names)
        assert not any(name.endswith((".pyc", ".pyo", ".DS_Store")) for name in names)
        assert not any("/.git/" in f"/{name}" or "/.venv/" in f"/{name}" for name in names)


def test_local_commissioning_documentation_preserves_observation_only_boundary() -> None:
    guide = (ROOT / "docs" / "LOCAL_HOME_ASSISTANT_COMMISSIONING.md").read_text(encoding="utf-8").lower()
    assert "authority: none" in guide
    assert "command delivery: disabled" in guide
    assert "control entities: none" in guide
    assert "existing intellicenter integration remains authoritative" in guide


def test_validator_rejects_artifact_missing_vendor(tmp_path: Path) -> None:
    """Regression: a commissioning ZIP without _vendor must never deploy."""

    bad_zip = tmp_path / "PoolOS_Bad_No_Vendor.zip"

    with zipfile.ZipFile(bad_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(COMPONENT).as_posix()
            if relative.startswith("_vendor/"):
                continue
            archive.write(
                path,
                f"custom_components/poolos/{relative}",
            )

        archive.writestr(
            "custom_components/poolos/LOCAL_COMMISSIONING.txt",
            "deliberately incomplete regression artifact\n",
        )

        manifest = json.loads(
            (COMPONENT / "manifest.json").read_text(encoding="utf-8")
        )
        manifest["requirements"] = [
            requirement
            for requirement in manifest.get("requirements", [])
            if not requirement.startswith("poolos@")
        ]
        archive.writestr(
            "custom_components/poolos/manifest.json",
            json.dumps(manifest),
        )

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--validate",
            str(bad_zip),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "missing required vendored core file" in combined


def test_validator_requires_every_registered_platform(tmp_path: Path) -> None:
    """Regression: PLATFORMS and packaged platform files must stay consistent."""

    good_zip = tmp_path / "PoolOS_Good.zip"

    subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--output",
            str(good_zip),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    broken_zip = tmp_path / "PoolOS_Bad_Missing_Platform.zip"

    with zipfile.ZipFile(good_zip) as source, zipfile.ZipFile(
        broken_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as target:
        for item in source.infolist():
            if item.filename == "custom_components/poolos/light.py":
                continue
            target.writestr(item, source.read(item.filename))

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--validate",
            str(broken_zip),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "registered Home Assistant platform is missing from artifact" in combined


def test_builder_writes_matching_sha256(tmp_path: Path) -> None:
    """The canonical builder must publish a matching SHA256 sidecar."""

    output = tmp_path / "PoolOS_Local_HA_Commissioning.zip"

    subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    checksum = Path(str(output) + ".sha256")

    assert checksum.is_file()

    expected = checksum.read_text(encoding="ascii").strip()

    import hashlib

    actual = hashlib.sha256(output.read_bytes()).hexdigest()

    assert expected == actual
