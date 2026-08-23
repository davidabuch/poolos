#!/usr/bin/env python3
"""Build and validate a self-contained PoolOS HA commissioning ZIP."""

from __future__ import annotations

import argparse
import ast
import hashlib
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

REQUIRED_COMPONENT_FILES = {
    "__init__.py",
    "manifest.json",
    "const.py",
    "coordinator.py",
    "manual_intellicenter.py",
    "translations/en.json",
    "LOCAL_COMMISSIONING.txt",
}

REQUIRED_VENDOR_FILES = {
    "__init__.py",
    "intellicenter_readonly.py",
}


class ArtifactValidationError(RuntimeError):
    """Raised when a commissioning artifact violates the package contract."""


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
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def _registered_platforms(const_source: str) -> tuple[str, ...]:
    tree = ast.parse(const_source)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name) and target.id == "PLATFORMS"
            for target in node.targets
        ):
            continue

        value = ast.literal_eval(node.value)
        if not isinstance(value, tuple) or not all(
            isinstance(item, str) for item in value
        ):
            raise ArtifactValidationError(
                "PLATFORMS must be a tuple of platform names"
            )

        return value

    raise ArtifactValidationError("PLATFORMS assignment not found in const.py")


def _is_prohibited_archive_name(name: str) -> bool:
    path = Path(name)

    if any(part in PROHIBITED_PARTS for part in path.parts):
        return True

    if path.name == ".DS_Store" or path.name.startswith("._"):
        return True

    return path.suffix in PROHIBITED_SUFFIXES


def validate_artifact(path: Path) -> None:
    """Validate one already-built commissioning ZIP."""

    path = path.resolve()

    if not path.is_file():
        raise ArtifactValidationError(f"artifact does not exist: {path}")

    if not zipfile.is_zipfile(path):
        raise ArtifactValidationError(f"artifact is not a valid ZIP: {path}")

    with zipfile.ZipFile(path) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ArtifactValidationError(
                f"ZIP integrity failure at member: {corrupt}"
            )

        names = set(archive.namelist())
        prefix = "custom_components/poolos/"

        for relative in sorted(REQUIRED_COMPONENT_FILES):
            required = prefix + relative
            if required not in names:
                raise ArtifactValidationError(
                    f"missing required component file: {required}"
                )

        for relative in sorted(REQUIRED_VENDOR_FILES):
            required = prefix + "_vendor/poolos/" + relative
            if required not in names:
                raise ArtifactValidationError(
                    f"missing required vendored core file: {required}"
                )

        vendor_python_files = {
            name
            for name in names
            if name.startswith(prefix + "_vendor/poolos/")
            and name.endswith(".py")
        }
        if len(vendor_python_files) < 20:
            raise ArtifactValidationError(
                "vendored PoolOS core is suspiciously incomplete: "
                f"only {len(vendor_python_files)} Python files"
            )

        prohibited = sorted(
            name for name in names if _is_prohibited_archive_name(name)
        )
        if prohibited:
            raise ArtifactValidationError(
                f"prohibited archive content found: {prohibited[0]}"
            )

        manifest = json.loads(
            archive.read(prefix + "manifest.json").decode("utf-8")
        )
        requirements = manifest.get("requirements", [])

        if any(
            isinstance(requirement, str)
            and requirement.startswith("poolos@")
            for requirement in requirements
        ):
            raise ArtifactValidationError(
                "local commissioning manifest still contains PoolOS Git dependency"
            )

        const_source = archive.read(prefix + "const.py").decode("utf-8")
        platforms = _registered_platforms(const_source)

        for platform in platforms:
            platform_file = prefix + f"{platform}.py"
            if platform_file not in names:
                raise ArtifactValidationError(
                    "registered Home Assistant platform is missing from artifact: "
                    f"{platform_file}"
                )


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = Path(str(path) + ".sha256")
    checksum.write_text(f"{digest}\n", encoding="ascii")
    return checksum


def build(output: Path) -> Path:
    """Build, validate, and atomically publish the commissioning ZIP."""

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="poolos-local-ha-") as temporary:
        temporary_root = Path(temporary)
        stage = temporary_root / "stage" / "custom_components" / "poolos"

        shutil.copytree(COMPONENT_SOURCE, stage, ignore=_ignore)

        vendor_core = stage / "_vendor" / "poolos"
        shutil.copytree(CORE_SOURCE, vendor_core, ignore=_ignore)

        _rewrite_manifest(stage)

        (stage / "LOCAL_COMMISSIONING.txt").write_text(
            "PoolOS local commissioning package.\n"
            "The PoolOS core is bundled under _vendor/poolos.\n"
            "No GitHub/HACS PoolOS runtime dependency is required.\n",
            encoding="utf-8",
        )

        candidate = temporary_root / "candidate.zip"

        with zipfile.ZipFile(
            candidate,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive_root = temporary_root / "stage"

            for path in sorted(archive_root.rglob("*")):
                if path.is_file():
                    archive.write(
                        path,
                        path.relative_to(archive_root).as_posix(),
                    )

        validate_artifact(candidate)

        shutil.copy2(candidate, output)

    _write_sha256(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "PoolOS_Local_HA_Commissioning.zip",
    )
    parser.add_argument(
        "--validate",
        type=Path,
        help="Validate an existing commissioning ZIP without building.",
    )
    args = parser.parse_args()

    if args.validate is not None:
        validate_artifact(args.validate)
        print(f"VALID: {args.validate.resolve()}")
        return

    output = build(args.output)
    print(f"BUILT: {output}")
    print(f"SHA256: {output}.sha256")


if __name__ == "__main__":
    main()
