from __future__ import annotations

import pytest

from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_operating_target import (
    PumpOperatingTarget,
    PumpOperatingTargetPolicy,
    PumpTargetUnit,
)


def test_default_target_policy_is_exact_legacy_rpm_policy() -> None:
    baselines = PumpOperatingBaselines()
    policy = PumpOperatingTargetPolicy.from_rpm_baselines(baselines)

    assert policy.filtration == PumpOperatingTarget(PumpTargetUnit.RPM, 2600)
    assert policy.solar_heating == PumpOperatingTarget(PumpTargetUnit.RPM, 2900)
    assert policy.gas_heating == PumpOperatingTarget(PumpTargetUnit.RPM, 3000)
    assert policy.temperature_probe == PumpOperatingTarget(PumpTargetUnit.RPM, 1500)
    assert policy.priming == PumpOperatingTarget(PumpTargetUnit.RPM, 3000)
    assert policy.grid_outage == PumpOperatingTarget(PumpTargetUnit.RPM, 1500)
    assert policy.sanitation == PumpOperatingTarget(PumpTargetUnit.RPM, 3200)
    assert policy.spillway == PumpOperatingTarget(PumpTargetUnit.RPM, 2900)


def test_gpm_target_is_first_class_without_rpm_conversion() -> None:
    target = PumpOperatingTarget(PumpTargetUnit.GPM, 42)

    assert target.unit is PumpTargetUnit.GPM
    assert target.value == 42
    assert target.observed_concept == "pump.gpm"
    assert target.configured_concept == "pump.configured_flow_gpm"
    assert target.verification_tolerance == 2.0


def test_rpm_target_preserves_existing_bounds() -> None:
    with pytest.raises(ValueError, match="RPM target"):
        PumpOperatingTarget(PumpTargetUnit.RPM, 449)

    with pytest.raises(ValueError, match="RPM target"):
        PumpOperatingTarget(PumpTargetUnit.RPM, 3451)


def test_policy_fingerprint_changes_with_unit_even_when_numeric_value_matches() -> None:
    baselines = PumpOperatingBaselines()
    legacy = PumpOperatingTargetPolicy.from_rpm_baselines(baselines)
    mixed = PumpOperatingTargetPolicy(
        filtration=PumpOperatingTarget(PumpTargetUnit.GPM, 40),
        solar_heating=legacy.solar_heating,
        gas_heating=legacy.gas_heating,
        temperature_probe=legacy.temperature_probe,
        priming=legacy.priming,
        grid_outage=legacy.grid_outage,
        sanitation=legacy.sanitation,
        spillway=legacy.spillway,
    )

    assert mixed.fingerprint != legacy.fingerprint
