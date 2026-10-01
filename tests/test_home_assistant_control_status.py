"""Runtime truth tests for PoolOS top-level control status."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "poolos" / "control_status.py"

spec = importlib.util.spec_from_file_location("poolos_control_status_test", MODULE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
runtime_control_status = module.runtime_control_status


def _runtime(
    *,
    manual_available: bool,
    filtration: bool = False,
    thermal_live: bool = False,
    thermal_automatic: bool = False,
    outage: bool = False,
):
    return SimpleNamespace(
        manual_intellicenter=SimpleNamespace(available=manual_available),
        filtration_automatic_runtime=SimpleNamespace(enabled=filtration),
        thermal_runtime=SimpleNamespace(effective_live_enabled=thermal_live),
        thermal_automatic_runtime=SimpleNamespace(enabled=thermal_automatic),
        grid_outage_safety_runtime=SimpleNamespace(enabled=outage),
    )


def test_unloaded_runtime_is_unavailable_and_non_actuating() -> None:
    status = runtime_control_status(None)

    assert status["control_profile"] == "UNAVAILABLE"
    assert status["command_delivery_enabled"] is False
    assert status["manual_command_delivery_available"] is False
    assert status["autonomous_command_delivery_enabled"] is False


def test_manual_transport_without_autonomy_is_manual_control() -> None:
    status = runtime_control_status(_runtime(manual_available=True))

    assert status["control_profile"] == "MANUAL_CONTROL"
    assert status["command_delivery_enabled"] is True
    assert status["manual_command_delivery_available"] is True
    assert status["autonomous_command_delivery_enabled"] is False


def test_scoped_live_requires_transport_and_enabled_autonomous_domain() -> None:
    status = runtime_control_status(
        _runtime(
            manual_available=True,
            filtration=True,
            thermal_live=True,
            thermal_automatic=True,
            outage=True,
        )
    )

    assert status["control_profile"] == "SCOPED_LIVE"
    assert status["command_delivery_enabled"] is True
    assert status["autonomous_command_delivery_enabled"] is True
    assert status["autonomous_domains"] == {
        "filtration": True,
        "thermal": True,
        "grid_outage_safety": True,
    }


def test_thermal_autonomy_requires_both_automatic_and_live_gates() -> None:
    automatic_only = runtime_control_status(
        _runtime(
            manual_available=True,
            thermal_automatic=True,
            thermal_live=False,
        )
    )
    live_only = runtime_control_status(
        _runtime(
            manual_available=True,
            thermal_automatic=False,
            thermal_live=True,
        )
    )

    assert automatic_only["autonomous_domains"]["thermal"] is False
    assert live_only["autonomous_domains"]["thermal"] is False


def test_enabled_gates_without_transport_fail_to_observe_only() -> None:
    status = runtime_control_status(
        _runtime(
            manual_available=False,
            filtration=True,
            thermal_live=True,
            thermal_automatic=True,
            outage=True,
        )
    )

    assert status["control_profile"] == "OBSERVE_ONLY"
    assert status["command_delivery_enabled"] is False
    assert status["autonomous_command_delivery_enabled"] is False
