"""Static contract tests for the Home Assistant climate platform."""

import ast
from pathlib import Path


CLIMATE_PATH = Path(__file__).resolve().parents[1] / "intellicenter" / "climate.py"


def test_climate_uses_public_body_lookup():
    source = CLIMATE_PATH.read_text()

    assert ".api.body(" in source
    assert ".api.get_body(" not in source


def test_climate_module_is_valid_python():
    ast.parse(CLIMATE_PATH.read_text())
