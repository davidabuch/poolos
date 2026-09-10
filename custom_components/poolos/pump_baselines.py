"""Build one immutable effective pump policy from a config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from poolos.grid_outage_physical_safety import GridOutagePhysicalSafetyEngine
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator

from .const import (
    CONF_PUMP_FILTRATION_RPM,
    CONF_PUMP_GAS_HEATING_RPM,
    CONF_PUMP_GRID_OUTAGE_RPM,
    CONF_PUMP_PRIMING_RPM,
    CONF_PUMP_SOLAR_HEATING_RPM,
    CONF_PUMP_TEMPERATURE_PROBE_RPM,
)


_CONFIG_FIELDS = {
    "filtration_rpm": CONF_PUMP_FILTRATION_RPM,
    "solar_heating_rpm": CONF_PUMP_SOLAR_HEATING_RPM,
    "gas_heating_rpm": CONF_PUMP_GAS_HEATING_RPM,
    "temperature_probe_rpm": CONF_PUMP_TEMPERATURE_PROBE_RPM,
    "priming_rpm": CONF_PUMP_PRIMING_RPM,
    "grid_outage_rpm": CONF_PUMP_GRID_OUTAGE_RPM,
}


def effective_pump_operating_baselines(
    configured: Mapping[str, Any],
) -> PumpOperatingBaselines:
    """Return one strict effective policy, applying defaults only when absent."""

    defaults = PumpOperatingBaselines()
    values = {
        field_name: configured.get(config_key, getattr(defaults, field_name))
        for field_name, config_key in _CONFIG_FIELDS.items()
    }
    return PumpOperatingBaselines(**values)


@dataclass(frozen=True, slots=True)
class PumpBaselineRuntimeComposition:
    """Core dependencies bound to one config entry's effective pump policy."""

    baselines: PumpOperatingBaselines
    thermal_evaluator: ThermalRuntimeEvaluator
    thermal_orchestrator: ThermalRuntimeOrchestrator
    physical_authority: PoolOSPhysicalCommandAuthority
    grid_outage_engine: GridOutagePhysicalSafetyEngine


def compose_pump_baseline_runtime(
    configured: Mapping[str, Any],
) -> PumpBaselineRuntimeComposition:
    """Construct the RPM-sensitive core graph from one effective policy."""

    baselines = effective_pump_operating_baselines(configured)
    return PumpBaselineRuntimeComposition(
        baselines=baselines,
        thermal_evaluator=ThermalRuntimeEvaluator.with_baselines(baselines),
        thermal_orchestrator=ThermalRuntimeOrchestrator(baselines=baselines),
        physical_authority=PoolOSPhysicalCommandAuthority(baselines=baselines),
        grid_outage_engine=GridOutagePhysicalSafetyEngine(baselines=baselines),
    )


__all__ = [
    "PumpBaselineRuntimeComposition",
    "compose_pump_baseline_runtime",
    "effective_pump_operating_baselines",
]
