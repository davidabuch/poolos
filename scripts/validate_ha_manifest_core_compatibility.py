#!/usr/bin/env python3
"""Validate the HA integration against its manifest-pinned PoolOS core.

This gate intentionally does NOT import the repository checkout PoolOS package.
It installs the exact PoolOS requirement declared by the Home Assistant
manifest into an isolated target directory, then verifies every static
"from poolos... import ..." used by the integration against that installed
package.

The purpose is to catch integration/core skew before a Home Assistant restart.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
MANIFEST = COMPONENT / "manifest.json"

_POOLOS_REQUIREMENT_PREFIX = "poolos@git+https://github.com/davidabuch/poolos.git@"
_IMMUTABLE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CompatibilityGateError(RuntimeError):
    """Raised when the HA integration and manifest-pinned core are incompatible."""


def manifest_poolos_requirement(manifest_path: Path = MANIFEST) -> str:
    """Return and validate the single immutable PoolOS core requirement."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    requirements = [
        value
        for value in manifest.get("requirements", [])
        if isinstance(value, str) and value.startswith("poolos@")
    ]
    if len(requirements) != 1:
        raise CompatibilityGateError(
            "manifest must declare exactly one PoolOS runtime requirement"
        )

    requirement = requirements[0]
    if not requirement.startswith(_POOLOS_REQUIREMENT_PREFIX):
        raise CompatibilityGateError(
            "PoolOS requirement must use the canonical GitHub repository"
        )

    revision = requirement.removeprefix(_POOLOS_REQUIREMENT_PREFIX)
    if not _IMMUTABLE_SHA_RE.fullmatch(revision):
        raise CompatibilityGateError(
            "PoolOS runtime requirement must be pinned to an immutable 40-character SHA"
        )
    return requirement


def collect_poolos_imports(component: Path = COMPONENT) -> dict[str, set[str]]:
    """Collect static imports from PoolOS core used by the HA integration."""

    imports: dict[str, set[str]] = {}
    for path in sorted(component.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module
            if module is None or not (
                module == "poolos" or module.startswith("poolos.")
            ):
                continue
            names = imports.setdefault(module, set())
            for alias in node.names:
                if alias.name == "*":
                    raise CompatibilityGateError(
                        "wildcard PoolOS import is not supported by compatibility gate: "
                        f"{path}"
                    )
                names.add(alias.name)

    if not imports:
        raise CompatibilityGateError("no PoolOS core imports found in HA integration")
    return imports


def install_requirement(requirement: str, target: Path) -> None:
    """Install the manifest-pinned core into an isolated target directory."""

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--target",
            str(target),
            requirement,
        ],
        cwd=target,
        check=True,
    )


def validate_imports(imports: dict[str, set[str]], target: Path) -> None:
    """Validate modules and symbols in a clean interpreter using only target."""

    payload = {module: sorted(names) for module, names in sorted(imports.items())}
    checker = r"""
import importlib
import json
import sys

target = sys.argv[1]
imports = json.loads(sys.argv[2])
sys.path[:] = [target] + [p for p in sys.path if p and "site-packages" not in p]

failures = []
for module_name, names in imports.items():
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        failures.append(f"{module_name}: import failed: {exc!r}")
        continue
    for name in names:
        if not hasattr(module, name):
            failures.append(f"{module_name}: missing imported symbol {name}")

if failures:
    print("HA manifest/core compatibility FAILED", file=sys.stderr)
    for failure in failures:
        print(f" - {failure}", file=sys.stderr)
    raise SystemExit(1)

print(
    f"Validated {sum(len(v) for v in imports.values())} imported symbols "
    f"across {len(imports)} PoolOS modules."
)
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-I", "-c", checker, str(target), json.dumps(payload)],
        cwd=target,
        env=env,
        check=True,
    )


def main() -> None:
    requirement = manifest_poolos_requirement()
    imports = collect_poolos_imports()

    with tempfile.TemporaryDirectory(prefix="poolos-ha-core-gate-") as tmp:
        target = Path(tmp) / "site"
        target.mkdir()
        install_requirement(requirement, target)
        validate_imports(imports, target)

    revision = requirement.rsplit("@", 1)[1]
    symbol_count = sum(len(names) for names in imports.values())
    print(
        "PASS: HA integration is compatible with manifest-pinned PoolOS core "
        f"{revision} ({symbol_count} imported symbols checked)."
    )


if __name__ == "__main__":
    main()
