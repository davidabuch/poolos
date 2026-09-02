"""Native mapping for direct PoolOS BODY heat-mode configuration intent."""

from __future__ import annotations

from poolos.thermal_runtime_assessment import ThermalRequestedMode


_NATIVE_HEATER_BY_DIRECT_MODE = {
    ThermalRequestedMode.OFF: "00000",
    ThermalRequestedMode.GAS: "H0001",
    ThermalRequestedMode.SOLAR: "H0002",
}


def configured_heater_intent_for_direct_requested_mode(
    mode: ThermalRequestedMode,
) -> str | None:
    """Map only direct requested configuration to its native BODY HEATER ID."""

    return _NATIVE_HEATER_BY_DIRECT_MODE.get(ThermalRequestedMode(mode))


__all__ = ["configured_heater_intent_for_direct_requested_mode"]
