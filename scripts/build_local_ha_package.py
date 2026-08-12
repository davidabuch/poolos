#!/usr/bin/env python3
"""Build a self-contained, local-only PoolOS Home Assistant commissioning ZIP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_SOURCE = ROOT / "custom_components" / "poolos"
CORE_SOURCE = ROOT / "poolos"

PROHIBITED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "__MACOSX",
}
PROHIBITED_SUFFIXES = {".pyc", ".pyo"}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in PROHIBITED_PARTS or name == ".DS_Store" or name.startswith("._"):
            ignored.add(name)
        elif Path(name).suffix in PROHIBITED_SUFFIXES:
            ignored.add(name)
    return ignored


def _rewrite_manifest(component: Path) -> None:
    manifest_path = component / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requirements"] = [
        requirement
        for requirement in manifest.get("requirements", [])
        if not requirement.startswith("poolos@")
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build(output: Path) -> Path:
    """Build and return the local commissioning ZIP path."""

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="poolos-local-ha-") as temporary:
        stage = Path(temporary) / "custom_components" / "poolos"
        shutil.copytree(COMPONENT_SOURCE, stage, ignore=_ignore)
        vendor_core = stage / "_vendor" / "poolos"
        shutil.copytree(CORE_SOURCE, vendor_core, ignore=_ignore)
        _rewrite_manifest(stage)
        (stage / "LOCAL_COMMISSIONING.txt").write_text(
            "PoolOS local observation-only commissioning package.\n"
            "The PoolOS core is bundled under _vendor/poolos.\n"
            "No GitHub/HACS runtime dependency is required.\n",
            encoding="utf-8",
        )

        if output.exists():
            output.unlink()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            root = Path(temporary)
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "PoolOS_Local_HA_Commissioning.zip",
    )
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
