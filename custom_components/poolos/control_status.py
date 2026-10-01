"""Canonical top-level control status for the PoolOS Home Assistant runtime."""

from __future__ import annotations

from typing import Any


def runtime_control_status(runtime: Any | None) -> dict[str, Any]:
    """Describe actual physical-control capability without erasing scoped gates."""

    if runtime is None:
        return {
            "control_profile": "UNAVAILABLE",
            "command_delivery_enabled": False,
            "manual_command_delivery_available": False,
            "autonomous_command_delivery_enabled": False,
            "autonomous_domains": {
                "filtration": False,
                "thermal": False,
                "grid_outage_safety": False,
            },
            "sanitation_control_available": False,
        }

    manual = getattr(runtime, "manual_intellicenter", None)
    manual_available = bool(manual is not None and manual.available)

    filtration_runtime = getattr(runtime, "filtration_automatic_runtime", None)
    filtration_enabled = bool(
        filtration_runtime is not None and filtration_runtime.enabled
    )

    thermal_runtime = getattr(runtime, "thermal_runtime", None)
    thermal_live_enabled = bool(
        thermal_runtime is not None and thermal_runtime.effective_live_enabled
    )
    thermal_automatic_runtime = getattr(runtime, "thermal_automatic_runtime", None)
    thermal_automatic_enabled = bool(
        thermal_automatic_runtime is not None and thermal_automatic_runtime.enabled
    )
    thermal_enabled = thermal_live_enabled and thermal_automatic_enabled

    outage_runtime = getattr(runtime, "grid_outage_safety_runtime", None)
    grid_outage_enabled = bool(outage_runtime is not None and outage_runtime.enabled)

    autonomous_domains = {
        "filtration": filtration_enabled,
        "thermal": thermal_enabled,
        "grid_outage_safety": grid_outage_enabled,
    }
    autonomous_enabled = manual_available and any(autonomous_domains.values())

    if autonomous_enabled:
        profile = "SCOPED_LIVE"
    elif manual_available:
        profile = "MANUAL_CONTROL"
    else:
        profile = "OBSERVE_ONLY"

    return {
        "control_profile": profile,
        # Compatibility summary: true means at least one physical delivery path
        # is currently available. New consumers should use the explicit fields.
        "command_delivery_enabled": manual_available,
        "manual_command_delivery_available": manual_available,
        "autonomous_command_delivery_enabled": autonomous_enabled,
        "autonomous_domains": autonomous_domains,
        "thermal_live_execution_enabled": thermal_live_enabled,
        "automatic_thermal_execution_enabled": thermal_automatic_enabled,
        "automatic_filtration_execution_enabled": filtration_enabled,
        "grid_outage_physical_safety_enabled": grid_outage_enabled,
        "sanitation_control_available": manual_available,
    }


__all__ = ["runtime_control_status"]
