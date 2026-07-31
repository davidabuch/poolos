from __future__ import annotations

import tomllib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTELLICENTER_ROOT = REPOSITORY_ROOT / "intellicenter"
INTELLICENTER_API_ROOT = INTELLICENTER_ROOT / "api"

EXPECTED_API_FILES = {
    "__init__.py",
    "body.py",
    "chemistry.py",
    "circuit.py",
    "cover.py",
    "models.py",
    "panel.py",
    "pump.py",
    "system.py",
    "temperature.py",
}

FORBIDDEN_API_FILES = {
    "binary_sensor.py",
    "climate.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "diagnostics.py",
    "light.py",
    "manifest.json",
    "number.py",
    "pyproject.toml",
    "select.py",
    "sensor.py",
    "strings.json",
    "switch.py",
}

REQUIRED_INTEGRATION_FILES = {
    "__init__.py",
    "binary_sensor.py",
    "climate.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "cover.py",
    "diagnostics.py",
    "light.py",
    "manifest.json",
    "number.py",
    "select.py",
    "sensor.py",
    "strings.json",
    "switch.py",
}


def test_intellicenter_api_contains_only_read_model_sources() -> None:
    actual_files = {
        path.name
        for path in INTELLICENTER_API_ROOT.iterdir()
        if path.is_file() and not path.name.startswith(".")
    }

    assert actual_files == EXPECTED_API_FILES
    assert actual_files.isdisjoint(FORBIDDEN_API_FILES)


def test_intellicenter_root_contains_deployable_integration_files() -> None:
    actual_files = {path.name for path in INTELLICENTER_ROOT.iterdir() if path.is_file()}

    assert REQUIRED_INTEGRATION_FILES <= actual_files
    assert (INTELLICENTER_ROOT / "translations" / "en.json").is_file()
    assert INTELLICENTER_API_ROOT.is_dir()


def test_root_distribution_packages_only_poolos() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    included_packages = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]

    assert included_packages == ["poolos*"]
