"""Canonical operator-intent path for manual native thermal source requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from poolos.integration import ThermalBody
from poolos.thermal_runtime_assessment import ThermalRequestedMode

from .manual_intellicenter import ManualIntelliCenterCommandError

if TYPE_CHECKING:
    from . import PoolOSRuntimeData


HEAT_MODE_OFF = "Off"
HEAT_MODE_SOLAR = "Solar"
HEAT_MODE_GAS = "Gas"
HEAT_MODE_SOLAR_PREFERRED = "Solar Preferred"

HEAT_MODE_OPTIONS = (
    HEAT_MODE_OFF,
    HEAT_MODE_SOLAR,
    HEAT_MODE_GAS,
    HEAT_MODE_SOLAR_PREFERRED,
)

_BODY_OBJNAM = {
    ThermalBody.POOL: "B1101",
    ThermalBody.HOT_TUB: "B1202",
}

_NATIVE_HEATER_BY_DIRECT_MODE = {
    HEAT_MODE_OFF: "00000",
    HEAT_MODE_GAS: "H0001",
    HEAT_MODE_SOLAR: "H0002",
}


def requested_heat_mode(
    runtime: PoolOSRuntimeData,
    body: ThermalBody,
) -> ThermalRequestedMode:
    """Return the single runtime-owned requested mode for one body."""

    if body is ThermalBody.POOL:
        return runtime.thermal_runtime.pool_requested_mode
    return runtime.thermal_runtime.hot_tub_requested_mode


async def async_request_heat_mode(
    runtime: PoolOSRuntimeData,
    body: ThermalBody,
    option: str,
) -> None:
    """Apply one requested mode without conflating it with observed truth."""

    if option not in HEAT_MODE_OPTIONS:
        raise ValueError(f"unsupported heat mode: {option}")

    mode = ThermalRequestedMode(option)
    if mode is ThermalRequestedMode.SOLAR_PREFERRED:
        runtime.thermal_runtime.set_requested_mode(body, mode)
        return

    manual = runtime.manual_intellicenter
    if manual is None or not manual.available:
        raise ManualIntelliCenterCommandError(
            "manual IntelliCenter command connection is unavailable"
        )

    await manual.async_set_body_heat_source(
        _BODY_OBJNAM[body],
        _NATIVE_HEATER_BY_DIRECT_MODE[option],
    )

    # Requested mode changes only after accepted delivery. Native HEATER and
    # active-source state remain read-back truth from the independent transport.
    runtime.thermal_runtime.set_requested_mode(body, mode)
