"""Body-neutral classification of the pump's current thermal purpose.

Selected heater configuration is intentionally separate from observed active
energy delivery.  This module is command-free and cannot establish ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .integration import PhysicalHeatMode, ThermalBody
from .operating_baselines import PumpOperatingBaselines


class ThermalOperatingPurpose(StrEnum):
    INACTIVE = "inactive"
    TEMPERATURE_ACQUISITION = "temperature_acquisition"
    ORDINARY_CIRCULATION = "ordinary_circulation"
    SOLAR_HEATING = "solar_heating"
    GAS_HEATING = "gas_heating"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ThermalOperatingPurposeEvidence:
    """Current authoritative facts; none of them imply PoolOS provenance."""

    body: ThermalBody
    body_active: bool | None
    other_body_active: bool | None
    selected_source: PhysicalHeatMode | None
    solar_active: bool | None
    heater_active: bool | None
    body_heating_demand_active: bool | None
    evidence_usable: bool
    temperature_acquisition_owned: bool = False


@dataclass(frozen=True, slots=True)
class ThermalOperatingPurposeAssessment:
    purpose: ThermalOperatingPurpose
    active_source: PhysicalHeatMode | None
    required_pump_rpm: int | None
    reason_code: str
    evidence_usable: bool


def assess_thermal_operating_purpose(
    evidence: ThermalOperatingPurposeEvidence,
    *,
    baselines: PumpOperatingBaselines = PumpOperatingBaselines(),
) -> ThermalOperatingPurposeAssessment:
    """Classify active purpose without equating HEATER selection with heat."""

    if not evidence.evidence_usable:
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.UNRESOLVED,
            None,
            None,
            "thermal_operating_evidence_unusable",
            False,
        )
    if evidence.body_active is True and evidence.other_body_active is True:
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.UNRESOLVED,
            None,
            None,
            "body_topology_contradictory",
            False,
        )
    if evidence.body_active is not True or evidence.other_body_active is not False:
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.INACTIVE,
            None,
            None,
            "target_body_not_exclusively_active",
            True,
        )
    if evidence.temperature_acquisition_owned:
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.TEMPERATURE_ACQUISITION,
            PhysicalHeatMode.OFF,
            baselines.temperature_probe_rpm,
            "temperature_acquisition_owned",
            True,
        )
    if (
        evidence.selected_source is PhysicalHeatMode.SOLAR
        and evidence.solar_active is True
    ):
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.SOLAR_HEATING,
            PhysicalHeatMode.SOLAR,
            baselines.solar_heating_rpm,
            "solar_actively_engaged",
            True,
        )
    if (
        evidence.selected_source is PhysicalHeatMode.GAS
        and evidence.heater_active is True
        and evidence.body_heating_demand_active is True
    ):
        return ThermalOperatingPurposeAssessment(
            ThermalOperatingPurpose.GAS_HEATING,
            PhysicalHeatMode.GAS,
            baselines.gas_heating_rpm,
            "gas_actively_heating_target_body",
            True,
        )
    return ThermalOperatingPurposeAssessment(
        ThermalOperatingPurpose.ORDINARY_CIRCULATION,
        PhysicalHeatMode.OFF,
        baselines.filtration_rpm,
        "body_active_without_active_heat_delivery",
        True,
    )


__all__ = [
    "ThermalOperatingPurpose",
    "ThermalOperatingPurposeAssessment",
    "ThermalOperatingPurposeEvidence",
    "assess_thermal_operating_purpose",
]
