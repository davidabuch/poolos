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
