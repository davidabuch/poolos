from __future__ import annotations

import pytest

from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.thermal_operating_purpose import (
    ThermalOperatingPurpose,
    ThermalOperatingPurposeEvidence,
    assess_thermal_operating_purpose,
)


@pytest.mark.parametrize(
    ("selected", "solar", "heater", "demand", "purpose", "rpm"),
    (
        (PhysicalHeatMode.OFF, False, False, False, ThermalOperatingPurpose.ORDINARY_CIRCULATION, 2600),
        (PhysicalHeatMode.SOLAR, False, False, True, ThermalOperatingPurpose.ORDINARY_CIRCULATION, 2600),
        (PhysicalHeatMode.SOLAR, True, False, True, ThermalOperatingPurpose.SOLAR_HEATING, 2900),
        (PhysicalHeatMode.GAS, False, False, True, ThermalOperatingPurpose.ORDINARY_CIRCULATION, 2600),
        (PhysicalHeatMode.GAS, False, True, True, ThermalOperatingPurpose.GAS_HEATING, 3000),
    ),
)
def test_selected_source_does_not_replace_active_operating_purpose(
    selected: PhysicalHeatMode,
    solar: bool,
    heater: bool,
    demand: bool,
    purpose: ThermalOperatingPurpose,
    rpm: int,
) -> None:
    result = assess_thermal_operating_purpose(
        ThermalOperatingPurposeEvidence(
            body=ThermalBody.HOT_TUB,
            body_active=True,
            other_body_active=False,
            selected_source=selected,
            solar_active=solar,
            heater_active=heater,
            body_heating_demand_active=demand,
            evidence_usable=True,
        )
    )

    assert result.purpose is purpose
    assert result.required_pump_rpm == rpm


def test_temperature_acquisition_requires_positive_poolos_provenance() -> None:
    unowned = assess_thermal_operating_purpose(
        ThermalOperatingPurposeEvidence(
            body=ThermalBody.HOT_TUB,
            body_active=True,
            other_body_active=False,
            selected_source=PhysicalHeatMode.OFF,
            solar_active=False,
            heater_active=False,
            body_heating_demand_active=False,
            evidence_usable=True,
        )
    )
    owned = assess_thermal_operating_purpose(
        ThermalOperatingPurposeEvidence(
            body=ThermalBody.HOT_TUB,
            body_active=True,
            other_body_active=False,
            selected_source=PhysicalHeatMode.OFF,
            solar_active=False,
            heater_active=False,
            body_heating_demand_active=False,
            evidence_usable=True,
            temperature_acquisition_owned=True,
        )
    )

    assert unowned.purpose is ThermalOperatingPurpose.ORDINARY_CIRCULATION
    assert owned.purpose is ThermalOperatingPurpose.TEMPERATURE_ACQUISITION
    assert owned.required_pump_rpm == 1500


@pytest.mark.parametrize(
    "evidence",
    (
        ThermalOperatingPurposeEvidence(
            body=ThermalBody.HOT_TUB,
            body_active=True,
            other_body_active=True,
            selected_source=PhysicalHeatMode.GAS,
            solar_active=False,
            heater_active=True,
            body_heating_demand_active=True,
            evidence_usable=True,
        ),
        ThermalOperatingPurposeEvidence(
            body=ThermalBody.HOT_TUB,
            body_active=True,
            other_body_active=False,
            selected_source=PhysicalHeatMode.GAS,
            solar_active=False,
            heater_active=True,
            body_heating_demand_active=True,
            evidence_usable=False,
        ),
    ),
)
def test_ambiguous_or_unusable_topology_fails_closed(
    evidence: ThermalOperatingPurposeEvidence,
) -> None:
    result = assess_thermal_operating_purpose(evidence)

    assert result.purpose is ThermalOperatingPurpose.UNRESOLVED
    assert result.required_pump_rpm is None
