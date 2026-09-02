"""Canonical operator-intent path for manual native thermal source requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from poolos.integration import ThermalBody
from poolos.thermal_runtime_assessment import ThermalRequestedMode

from .configured_thermal import configured_heater_intent_for_direct_requested_mode
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

    heater_id = configured_heater_intent_for_direct_requested_mode(mode)
    if heater_id is None:
        raise ValueError(f"unsupported direct heat mode: {option}")

    await manual.async_set_body_heat_source(_BODY_OBJNAM[body], heater_id)

    # Requested mode changes only after accepted delivery. Native HEATER and
    # active-source state remain read-back truth from the independent transport.
    runtime.thermal_runtime.set_requested_mode(body, mode)
