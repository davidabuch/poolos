"""Structural regression tests for the dedicated PoolOS settings panel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
PANEL_BACKEND = COMPONENT / "settings_panel.py"
PANEL_FRONTEND = COMPONENT / "settings_panel.js"
MANIFEST = COMPONENT / "manifest.json"
INIT = COMPONENT / "__init__.py"


def test_settings_panel_is_registered_from_poolos_setup() -> None:
    source = INIT.read_text(encoding="utf-8")
    assert "from .settings_panel import async_setup_settings_panel" in source
    assert "await async_setup_settings_panel(hass)" in source


def test_settings_panel_exposes_guarded_websocket_read_and_update() -> None:
    source = PANEL_BACKEND.read_text(encoding="utf-8")
    assert '"poolos/settings/get"' in source
    assert '"poolos/settings/update"' in source
    assert source.count("@websocket_api.require_admin") == 2
    assert "hass.config_entries.async_update_entry(entry, options=validated)" in source
    assert "_mapping_schema(current)" in source


def test_settings_panel_uses_native_ha_form_conditional_visibility() -> None:
    source = PANEL_FRONTEND.read_text(encoding="utf-8")
    assert "<ha-form id=\"form\"></ha-form>" in source
    assert 'field: "filtration_scheduling_mode"' in source
    assert 'value: "solar_tou_optimized"' in source
    assert 'value: "traditional_time_based"' in source
    assert 'name: "preferred_filtration_catchup_start"' in source
    assert 'name: "traditional_filtration_start"' in source


def test_settings_panel_keeps_full_configuration_groups() -> None:
    source = PANEL_FRONTEND.read_text(encoding="utf-8")
    for title in (
        'title: "Filtration"',
        'title: "Thermal"',
        'title: "Pump & Safety"',
        'title: "Sanitation"',
        'title: "Entity & Hardware Mapping"',
        'title: "Advanced"',
    ):
        assert title in source


def test_settings_panel_dependencies_are_declared() -> None:
    source = MANIFEST.read_text(encoding="utf-8")
    for dependency in ('"frontend"', '"http"', '"panel_custom"', '"websocket_api"'):
        assert dependency in source
