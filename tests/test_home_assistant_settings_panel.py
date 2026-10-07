"""Structural regression tests for the dedicated PoolOS settings panel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
PANEL_BACKEND = COMPONENT / "settings_panel.py"
PANEL_FRONTEND = COMPONENT / "settings_panel.js"
MANIFEST = COMPONENT / "manifest.json"
INIT = COMPONENT / "__init__.py"
CONFIG_FLOW = COMPONENT / "config_flow.py"


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
    assert "_settings_schema(current)" in source


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


def test_settings_panel_exposes_only_commissioned_gpm_purposes() -> None:
    backend = PANEL_BACKEND.read_text(encoding="utf-8")
    frontend = PANEL_FRONTEND.read_text(encoding="utf-8")

    for key in (
        "pump_filtration_unit",
        "pump_filtration_gpm",
        "pump_solar_heating_unit",
        "pump_solar_heating_gpm",
        "pump_gas_heating_unit",
        "pump_gas_heating_gpm",
        "pump_temperature_probe_unit",
        "pump_temperature_probe_gpm",
        "sanitation_unit",
        "sanitation_gpm",
    ):
        assert key in frontend
    assert "_settings_schema(current)" in backend
    assert "_validate_live_gpm_settings" in backend
    assert "pump_target_capabilities" in backend
    assert 'pump_capability_profile(body="pool")' in backend
    assert 'pump_capability_profile(body="hot_tub")' in backend
    assert '"evidence_source"' in backend
    assert '"provider"' in backend

    # Priming and outage intentionally remain RPM-only safety/startup slices.
    for forbidden in (
        "pump_priming_unit",
        "pump_priming_gpm",
        "pump_grid_outage_unit",
        "pump_grid_outage_gpm",
    ):
        assert forbidden not in frontend


def test_settings_panel_gpm_selector_uses_live_native_limits() -> None:
    source = PANEL_FRONTEND.read_text(encoding="utf-8")
    assert "capability?.minimum_gpm" in source
    assert "capability?.maximum_gpm" in source
    assert "unitSelector(Boolean(filtrationGpm.supported))" in source
    assert "unitSelector(Boolean(solarGpm.supported))" in source
    assert "unitSelector(Boolean(gasGpm.supported))" in source
    assert "unitSelector(Boolean(probeGpm.supported))" in source
    assert "unitSelector(Boolean(sanitationGpm.supported))" in source
    assert "pump_target_capabilities" in source


def test_settings_schema_has_one_effective_definition_with_full_gpm_commissioning_surface() -> None:
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert source.count("def _settings_schema(") == 1
    assert source.count("def _positive_whole_gpm(") == 1
    for symbol in (
        "CONF_POOL_COMMISSIONED_PUMP_MODE",
        "CONF_POOL_COMMISSIONED_PUMP_MIN_GPM",
        "CONF_POOL_COMMISSIONED_PUMP_MAX_GPM",
        "CONF_SPA_COMMISSIONED_PUMP_MODE",
        "CONF_SPA_COMMISSIONED_PUMP_MIN_GPM",
        "CONF_SPA_COMMISSIONED_PUMP_MAX_GPM",
        "CONF_PUMP_FILTRATION_UNIT",
        "CONF_PUMP_FILTRATION_GPM",
        "CONF_PUMP_SOLAR_HEATING_UNIT",
        "CONF_PUMP_SOLAR_HEATING_GPM",
        "CONF_PUMP_GAS_HEATING_UNIT",
        "CONF_PUMP_GAS_HEATING_GPM",
        "CONF_PUMP_TEMPERATURE_PROBE_UNIT",
        "CONF_PUMP_TEMPERATURE_PROBE_GPM",
        "CONF_SANITATION_UNIT",
        "CONF_SANITATION_GPM",
    ):
        assert symbol in source
