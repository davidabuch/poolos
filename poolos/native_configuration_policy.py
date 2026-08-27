"""Read-only compatibility guard for native IntelliCenter configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NativeCompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    WARNING = "warning"
    CONFLICT = "conflict"


class AutonomousCapability(str, Enum):
    SOLAR_SOURCE_SELECTION = "solar_source_selection"
    SOLAR_PUMP_BASELINE = "solar_pump_baseline"
    GAS_PUMP_BASELINE = "gas_pump_baseline"
    FILTRATION_SCHEDULING = "filtration_scheduling"
    TEMPERATURE_PROBE_PUMP_BASELINE = "temperature_probe_pump_baseline"
    GRID_OUTAGE_PUMP_BASELINE = "grid_outage_pump_baseline"
    SPILLWAY_PUMP_BASELINE = "spillway_pump_baseline"
    GENERAL_PUMP_RPM_OWNERSHIP = "general_pump_rpm_ownership"


@dataclass(frozen=True, slots=True)
class NativeRpmAssignment:
    purpose: str
    rpm: int


@dataclass(frozen=True, slots=True)
class NativeConfigurationInput:
    native_solar_preferred: bool = False
    rpm_assignments: tuple[NativeRpmAssignment, ...] = ()
    conflicting_schedule_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NativeConfigurationConflict:
    code: str
    description: str
    affected_capabilities: tuple[AutonomousCapability, ...]


@dataclass(frozen=True, slots=True)
class NativeConfigurationAssessment:
    state: NativeCompatibilityState
    conflicts: tuple[NativeConfigurationConflict, ...]
    disabled_capabilities: tuple[AutonomousCapability, ...]
    authority: str = "none"
    command_delivery_enabled: bool = False


class NativeConfigurationGuard:
    """Surface conflicts without attempting to rewrite native configuration."""

    def evaluate(self, configuration: NativeConfigurationInput) -> NativeConfigurationAssessment:
        conflicts: list[NativeConfigurationConflict] = []
        if configuration.native_solar_preferred:
            conflicts.append(
                NativeConfigurationConflict(
                    "native_solar_preferred_conflict",
                    "Native Solar Preferred competes with PoolOS solar-source selection.",
                    (AutonomousCapability.SOLAR_SOURCE_SELECTION,),
                )
            )
        for assignment in configuration.rpm_assignments:
            purpose = assignment.purpose.strip().casefold()
            if "solar" in purpose:
                affected = (AutonomousCapability.SOLAR_PUMP_BASELINE,)
            elif "gas" in purpose or "heater" in purpose or "spa" in purpose:
                affected = (AutonomousCapability.GAS_PUMP_BASELINE,)
            elif "filtration" in purpose or "filter" in purpose:
                affected = (AutonomousCapability.FILTRATION_SCHEDULING,)
            elif "probe" in purpose or "temperature" in purpose:
                affected = (AutonomousCapability.TEMPERATURE_PROBE_PUMP_BASELINE,)
            elif "outage" in purpose or "grid" in purpose:
                affected = (AutonomousCapability.GRID_OUTAGE_PUMP_BASELINE,)
            elif "spillway" in purpose:
                affected = (AutonomousCapability.SPILLWAY_PUMP_BASELINE,)
            else:
                affected = (AutonomousCapability.GENERAL_PUMP_RPM_OWNERSHIP,)
            conflicts.append(
                NativeConfigurationConflict(
                    "native_rpm_assignment_conflict",
                    f"Native RPM assignment for {assignment.purpose} competes with PoolOS.",
                    affected,
                )
            )
        if configuration.conflicting_schedule_names:
            conflicts.append(
                NativeConfigurationConflict(
                    "native_filtration_schedule_conflict",
                    "Native schedules compete with flexible filtration scheduling.",
                    (AutonomousCapability.FILTRATION_SCHEDULING,),
                )
            )
        disabled = tuple(sorted({capability for item in conflicts for capability in item.affected_capabilities}, key=lambda item: item.value))
        state = NativeCompatibilityState.COMPATIBLE if not conflicts else NativeCompatibilityState.CONFLICT
        return NativeConfigurationAssessment(state, tuple(conflicts), disabled)
