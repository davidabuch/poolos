"""Build one immutable effective pump policy from a config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from poolos.grid_outage_physical_safety import GridOutagePhysicalSafetyEngine
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_operating_target import (
    PumpOperatingTarget,
    PumpOperatingTargetPolicy,
    PumpTargetUnit,
)
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.pump_speed_session import PumpSpeedSessionRuntime
from poolos.pump_target_session import PumpTargetSessionRuntime
from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator

from .const import (
    CONF_PUMP_FILTRATION_RPM,
    CONF_PUMP_GAS_HEATING_RPM,
    CONF_PUMP_GRID_OUTAGE_RPM,
    CONF_PUMP_PRIMING_RPM,
    CONF_PUMP_SOLAR_HEATING_RPM,
    CONF_PUMP_TEMPERATURE_PROBE_RPM,
    CONF_PUMP_FILTRATION_UNIT,
    CONF_PUMP_FILTRATION_GPM,
    CONF_PUMP_SOLAR_HEATING_UNIT,
    CONF_PUMP_SOLAR_HEATING_GPM,
    CONF_PUMP_GAS_HEATING_UNIT,
    CONF_PUMP_GAS_HEATING_GPM,
    CONF_PUMP_TEMPERATURE_PROBE_UNIT,
    CONF_PUMP_TEMPERATURE_PROBE_GPM,
    CONF_PUMP_PRIMING_UNIT,
    CONF_PUMP_PRIMING_GPM,
    CONF_PUMP_GRID_OUTAGE_UNIT,
    CONF_PUMP_GRID_OUTAGE_GPM,
    CONF_SANITATION_RPM,
    CONF_SANITATION_UNIT,
    CONF_SANITATION_GPM,
    DEFAULT_PUMP_TARGET_UNIT,
    DEFAULT_SANITATION_RPM,
    CONF_SPA_SOLAR_ROOF_F,
    DEFAULT_SPA_SOLAR_ROOF_F,
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
        field_name: _normalize_configured_rpm(
            configured.get(config_key, getattr(defaults, field_name))
        )
        for field_name, config_key in _CONFIG_FIELDS.items()
    }
    return PumpOperatingBaselines(**values)


def _normalize_configured_rpm(value: Any) -> Any:
    """Normalize Home Assistant number-selector output at the adapter boundary."""

    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


_TARGET_CONFIG = {
    "filtration": (
        CONF_PUMP_FILTRATION_UNIT,
        CONF_PUMP_FILTRATION_GPM,
        "filtration_rpm",
    ),
    "solar_heating": (
        CONF_PUMP_SOLAR_HEATING_UNIT,
        CONF_PUMP_SOLAR_HEATING_GPM,
        "solar_heating_rpm",
    ),
    "gas_heating": (
        CONF_PUMP_GAS_HEATING_UNIT,
        CONF_PUMP_GAS_HEATING_GPM,
        "gas_heating_rpm",
    ),
    "temperature_probe": (
        CONF_PUMP_TEMPERATURE_PROBE_UNIT,
        CONF_PUMP_TEMPERATURE_PROBE_GPM,
        "temperature_probe_rpm",
    ),
    "priming": (
        CONF_PUMP_PRIMING_UNIT,
        CONF_PUMP_PRIMING_GPM,
        "priming_rpm",
    ),
    "grid_outage": (
        CONF_PUMP_GRID_OUTAGE_UNIT,
        CONF_PUMP_GRID_OUTAGE_GPM,
        "grid_outage_rpm",
    ),
}


def _configured_target(
    configured: Mapping[str, Any],
    *,
    unit_key: str,
    gpm_key: str,
    rpm_value: int,
) -> PumpOperatingTarget:
    unit_raw = configured.get(unit_key, DEFAULT_PUMP_TARGET_UNIT)
    try:
        unit = PumpTargetUnit(str(unit_raw).lower())
    except ValueError as exc:
        raise ValueError(f"{unit_key} must be rpm or gpm") from exc
    if unit is PumpTargetUnit.RPM:
        return PumpOperatingTarget(unit, rpm_value)

    if gpm_key not in configured:
        raise ValueError(f"{gpm_key} is required when {unit_key}=gpm")
    value = _normalize_configured_rpm(configured[gpm_key])
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{gpm_key} must be a positive whole-number GPM target")
    return PumpOperatingTarget(unit, value)


def effective_pump_operating_targets(
    configured: Mapping[str, Any],
) -> PumpOperatingTargetPolicy:
    """Build unit-aware targets while preserving legacy RPM defaults exactly."""

    baselines = effective_pump_operating_baselines(configured)
    values: dict[str, PumpOperatingTarget] = {}
    for purpose, (unit_key, gpm_key, rpm_field) in _TARGET_CONFIG.items():
        values[purpose] = _configured_target(
            configured,
            unit_key=unit_key,
            gpm_key=gpm_key,
            rpm_value=getattr(baselines, rpm_field),
        )

    sanitation_unit_raw = configured.get(
        CONF_SANITATION_UNIT,
        DEFAULT_PUMP_TARGET_UNIT,
    )
    try:
        sanitation_unit = PumpTargetUnit(str(sanitation_unit_raw).lower())
    except ValueError as exc:
        raise ValueError(f"{CONF_SANITATION_UNIT} must be rpm or gpm") from exc
    sanitation_rpm = _normalize_configured_rpm(
        configured.get(CONF_SANITATION_RPM, DEFAULT_SANITATION_RPM)
    )
    if (
        isinstance(sanitation_rpm, bool)
        or not isinstance(sanitation_rpm, int)
        or sanitation_rpm <= 0
    ):
        raise ValueError(f"{CONF_SANITATION_RPM} must be a positive whole-number RPM target")
    sanitation = (
        PumpOperatingTarget(PumpTargetUnit.RPM, sanitation_rpm)
        if sanitation_unit is PumpTargetUnit.RPM
        else _configured_target(
            configured,
            unit_key=CONF_SANITATION_UNIT,
            gpm_key=CONF_SANITATION_GPM,
            rpm_value=sanitation_rpm,
        )
    )

    return PumpOperatingTargetPolicy(
        filtration=values["filtration"],
        solar_heating=values["solar_heating"],
        gas_heating=values["gas_heating"],
        temperature_probe=values["temperature_probe"],
        priming=values["priming"],
        grid_outage=values["grid_outage"],
        sanitation=sanitation,
        spillway=PumpOperatingTarget(
            PumpTargetUnit.RPM,
            baselines.spillway_rpm,
        ),
    )


@dataclass(frozen=True, slots=True)
class PumpBaselineRuntimeComposition:
    """Core dependencies bound to one config entry's effective pump policy."""

    baselines: PumpOperatingBaselines
    targets: PumpOperatingTargetPolicy
    thermal_evaluator: ThermalRuntimeEvaluator
    thermal_orchestrator: ThermalRuntimeOrchestrator
    physical_authority: PoolOSPhysicalCommandAuthority
    grid_outage_engine: GridOutagePhysicalSafetyEngine
    pump_speed_session: PumpSpeedSessionRuntime
    pump_target_session: PumpTargetSessionRuntime


def compose_pump_baseline_runtime(
    configured: Mapping[str, Any],
) -> PumpBaselineRuntimeComposition:
    """Construct the RPM-sensitive core graph from one effective policy."""

    baselines = effective_pump_operating_baselines(configured)
    targets = effective_pump_operating_targets(configured)
    spa_solar_roof_f = float(
        configured.get(
            CONF_SPA_SOLAR_ROOF_F,
            DEFAULT_SPA_SOLAR_ROOF_F,
        )
    )
    return PumpBaselineRuntimeComposition(
        baselines=baselines,
        targets=targets,
        thermal_evaluator=ThermalRuntimeEvaluator.with_baselines(
            baselines,
            spa_solar_roof_f=spa_solar_roof_f,
        ),
        thermal_orchestrator=ThermalRuntimeOrchestrator(baselines=baselines),
        physical_authority=PoolOSPhysicalCommandAuthority(baselines=baselines),
        grid_outage_engine=GridOutagePhysicalSafetyEngine(baselines=baselines),
        pump_speed_session=PumpSpeedSessionRuntime(baselines=baselines),
        pump_target_session=PumpTargetSessionRuntime(targets=targets),
    )


__all__ = [
    "PumpBaselineRuntimeComposition",
    "compose_pump_baseline_runtime",
    "effective_pump_operating_baselines",
    "effective_pump_operating_targets",
]
