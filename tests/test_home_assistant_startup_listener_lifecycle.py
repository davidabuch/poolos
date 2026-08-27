"""Regression contract for PoolOS one-time HA startup listener lifecycle."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "poolos" / "__init__.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_startup_listener_cleanup_is_idempotent() -> None:
    source = _source()

    assert "startup_unsub = None" in source
    assert "nonlocal startup_unsub" in source
    assert "startup_unsub = hass.bus.async_listen_once(" in source
    assert "def async_remove_startup_listener()" in source
    assert "if startup_unsub is None:" in source
    assert "unsubscribe = startup_unsub" in source
    assert "entry.async_on_unload(async_remove_startup_listener)" in source


def test_listener_marks_itself_consumed_before_activation() -> None:
    source = _source()

    handler = source.split(
        "async def async_handle_homeassistant_started",
        1,
    )[1].split(
        "startup_unsub = hass.bus.async_listen_once(",
        1,
    )[0]

    assert "nonlocal startup_unsub" in handler
    assert "startup_unsub = None" in handler


def test_one_time_listener_is_not_directly_registered_for_unload() -> None:
    source = _source()

    assert "entry.async_on_unload(\n            hass.bus.async_listen_once(" not in source
