"""Regression coverage for PoolOS Settings panel asset versioning."""

from pathlib import Path

PANEL_BACKEND = Path("custom_components/poolos/settings_panel.py")


def test_settings_panel_cache_key_tracks_frontend_content() -> None:
    source = PANEL_BACKEND.read_text(encoding="utf-8")

    assert "from hashlib import sha256" in source
    assert "module_bytes = await hass.async_add_executor_job(module_path.read_bytes)" in source
    assert "sha256(module_bytes).hexdigest()[:12]" in source
    assert '+ "-"' in source
    assert "+ asset_version" in source
    assert '"asset_version": asset_version' in source


def test_settings_panel_custom_element_tracks_frontend_content() -> None:
    backend = PANEL_BACKEND.read_text(encoding="utf-8")
    frontend = PANEL_FRONTEND.read_text(encoding="utf-8")
    assert '_PANEL_ELEMENT_PREFIX = "poolos-settings-panel-"' in backend
    assert "webcomponent_name=_PANEL_ELEMENT_PREFIX + asset_version" in backend
    assert "const moduleUrl = new URL(import.meta.url);" in frontend
    assert "const elementName =" in frontend
    assert "customElements.define(elementName, PoolOSSettingsPanel)" in frontend
