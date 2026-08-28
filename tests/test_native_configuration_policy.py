from poolos.native_configuration_policy import AutonomousCapability, NativeCompatibilityState, NativeConfigurationGuard, NativeConfigurationInput, NativeRpmAssignment


def test_compatible_native_configuration_is_non_authoritative() -> None:
    result = NativeConfigurationGuard().evaluate(NativeConfigurationInput())
    assert result.state is NativeCompatibilityState.COMPATIBLE
    assert result.disabled_capabilities == ()
    assert result.authority == "none"
    assert result.command_delivery_enabled is False


def test_native_solar_preferred_conflict_only_degrades_source_selection() -> None:
    result = NativeConfigurationGuard().evaluate(NativeConfigurationInput(native_solar_preferred=True))
    assert result.state is NativeCompatibilityState.CONFLICT
    assert result.disabled_capabilities == (AutonomousCapability.SOLAR_SOURCE_SELECTION,)
    assert AutonomousCapability.FILTRATION_SCHEDULING not in result.disabled_capabilities


def test_native_rpm_and_schedule_conflicts_are_explicit_and_scoped() -> None:
    result = NativeConfigurationGuard().evaluate(
        NativeConfigurationInput(
            rpm_assignments=(NativeRpmAssignment("Solar", 2800), NativeRpmAssignment("Spa Heater", 3000)),
            conflicting_schedule_names=("Pool schedule",),
        )
    )
    assert set(result.disabled_capabilities) == {
        AutonomousCapability.SOLAR_PUMP_BASELINE,
        AutonomousCapability.GAS_PUMP_BASELINE,
        AutonomousCapability.FILTRATION_SCHEDULING,
    }
    assert len(result.conflicts) == 3


def test_all_native_rpm_assignments_are_classified_for_single_owner_migration() -> None:
    result = NativeConfigurationGuard().evaluate(
        NativeConfigurationInput(
            rpm_assignments=(
                NativeRpmAssignment("Filtration", 2600),
                NativeRpmAssignment("Temperature probe", 1500),
                NativeRpmAssignment("Grid outage", 1500),
                NativeRpmAssignment("Spillway", 2800),
                NativeRpmAssignment("Feature circuit", 2400),
            )
        )
    )

    assert set(result.disabled_capabilities) == {
        AutonomousCapability.FILTRATION_SCHEDULING,
        AutonomousCapability.TEMPERATURE_PROBE_PUMP_BASELINE,
        AutonomousCapability.GRID_OUTAGE_PUMP_BASELINE,
        AutonomousCapability.SPILLWAY_PUMP_BASELINE,
        AutonomousCapability.GENERAL_PUMP_RPM_OWNERSHIP,
    }
