from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.commands import Command, CommandAction
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.scenarios import power_outage_scenario, spa_heat_scenario
from poolos.simulation import BodyThermalModel, Simulation, SimulationScenario
from poolos.validation import (
    DecisionExpectation,
    DecisionValidationCase,
    DecisionValidationRunner,
    ExpectationKind,
    ValidationStatus,
    simulation_fingerprint,
)

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def build_simulation() -> Simulation:
    kernel = PoolKernel()
    kernel.bodies.register(Body("spa", "Spa", BodyType.SPA))
    kernel.equipment.register(
        Equipment(
            "pump",
            "Spa Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            body=BodyType.SPA,
        )
    )
    kernel.equipment.register(
        Equipment(
            "heater",
            "Spa Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            body=BodyType.SPA,
        )
    )
    kernel.update_body_state(
        "spa",
        BodyState(
            BodyType.SPA,
            TemperatureState(90.0, 100.0, False),
            circulation_running=False,
            sanitizer_enabled=False,
        ),
    )
    simulation = Simulation.create(kernel, start_at=START)
    simulation.add_thermal_model(
        BodyThermalModel(
            "spa",
            heater_gain_per_hour=10.0,
            solar_gain_per_hour=0.0,
            ambient_exchange_per_hour=0.0,
        )
    )
    return simulation


def heat_case() -> DecisionValidationCase:
    return DecisionValidationCase(
        "spa reaches target",
        spa_heat_scenario(
            start_at=START,
            pump_id="pump",
            heater_id="heater",
            duration=timedelta(hours=1),
        ),
        (
            DecisionExpectation(
                ExpectationKind.FINAL_BODY_TEMPERATURE,
                100.0,
                subject_id="spa",
                tolerance=0.01,
            ),
            DecisionExpectation(
                ExpectationKind.FINAL_BODY_CIRCULATION, True, subject_id="spa"
            ),
            DecisionExpectation(
                ExpectationKind.FINAL_EQUIPMENT_ACTIVE, True, subject_id="pump"
            ),
            DecisionExpectation(ExpectationKind.APPLIED_EVENT_COUNT, 2),
            DecisionExpectation(ExpectationKind.TIMELINE_MONOTONIC, True),
        ),
        frozenset({"heating", "runtime"}),
    )


def test_validation_case_passes_with_per_expectation_diagnostics():
    report = DecisionValidationRunner(build_simulation).run_case(heat_case())

    assert report.status is ValidationStatus.PASSED
    assert report.passed is True
    assert len(report.checks) == 5
    assert all(check.status is ValidationStatus.PASSED for check in report.checks)
    assert report.fingerprint is not None


def test_failed_expectation_reports_expected_and_actual_values():
    case = DecisionValidationCase(
        "intentional mismatch",
        SimulationScenario("idle", timedelta(minutes=1)),
        (
            DecisionExpectation(
                ExpectationKind.FINAL_EQUIPMENT_ACTIVE, True, subject_id="pump"
            ),
        ),
    )

    report = DecisionValidationRunner(build_simulation).run_case(case)

    assert report.status is ValidationStatus.FAILED
    assert report.checks[0].actual is False
    assert "expected True" in report.checks[0].message


def test_missing_subject_is_a_failed_check_not_a_runner_crash():
    case = DecisionValidationCase(
        "missing equipment",
        SimulationScenario("idle", timedelta(minutes=1)),
        (
            DecisionExpectation(
                ExpectationKind.FINAL_EQUIPMENT_ACTIVE,
                False,
                subject_id="missing",
            ),
        ),
    )

    report = DecisionValidationRunner(build_simulation).run_case(case)

    assert report.status is ValidationStatus.FAILED
    assert "could not evaluate" in report.checks[0].message


def test_power_outage_rule_verifies_safe_final_state():
    simulation = build_simulation()
    simulation.submit(Command("pump", CommandAction.START, issued_at=START))

    def prepared_simulation() -> Simulation:
        return simulation

    case = DecisionValidationCase(
        "outage stops and does not restart circulation",
        power_outage_scenario(
            start_at=START,
            outage_after=timedelta(minutes=15),
            outage_duration=timedelta(minutes=30),
            total_duration=timedelta(hours=1),
        ),
        (
            DecisionExpectation(ExpectationKind.FINAL_GRID_AVAILABLE, True),
            DecisionExpectation(
                ExpectationKind.FINAL_EQUIPMENT_AVAILABLE, True, subject_id="pump"
            ),
            DecisionExpectation(
                ExpectationKind.FINAL_EQUIPMENT_ACTIVE, False, subject_id="pump"
            ),
            DecisionExpectation(ExpectationKind.APPLIED_EVENT_COUNT, 2),
        ),
        frozenset({"safety", "power"}),
    )

    assert DecisionValidationRunner(prepared_simulation).run_case(case).passed


def test_fingerprint_is_deterministic_and_detects_behavior_change():
    scenario = spa_heat_scenario(
        start_at=START,
        pump_id="pump",
        heater_id="heater",
        duration=timedelta(hours=1),
    )
    first = build_simulation().run_scenario(scenario)
    second = build_simulation().run_scenario(scenario)
    changed = build_simulation().run_scenario(
        spa_heat_scenario(
            start_at=START,
            pump_id="pump",
            heater_id="heater",
            target_temperature=99.0,
            duration=timedelta(hours=1),
        )
    )

    assert simulation_fingerprint(first) == simulation_fingerprint(second)
    assert simulation_fingerprint(first) != simulation_fingerprint(changed)


def test_golden_fingerprint_expectation_protects_complete_timeline():
    scenario = spa_heat_scenario(
        start_at=START,
        pump_id="pump",
        heater_id="heater",
        duration=timedelta(minutes=10),
    )
    golden = simulation_fingerprint(build_simulation().run_scenario(scenario))
    case = DecisionValidationCase(
        "golden spa timeline",
        scenario,
        (DecisionExpectation(ExpectationKind.GOLDEN_FINGERPRINT, golden),),
    )

    assert DecisionValidationRunner(build_simulation).run_case(case).passed


def test_suite_aggregates_pass_fail_and_error_precedence():
    failing = DecisionValidationCase(
        "failing",
        SimulationScenario("idle", timedelta(minutes=1)),
        (DecisionExpectation(ExpectationKind.FINAL_GRID_AVAILABLE, False),),
    )
    report = DecisionValidationRunner(build_simulation).run_suite((heat_case(), failing))

    assert report.status is ValidationStatus.FAILED
    assert report.counts[ValidationStatus.PASSED] == 1
    assert report.counts[ValidationStatus.FAILED] == 1


def test_suite_rejects_duplicate_case_names():
    case = heat_case()
    with pytest.raises(ValueError, match="unique"):
        DecisionValidationRunner(build_simulation).run_suite((case, case))


def test_runner_converts_simulation_failure_to_error_report():
    def broken_factory() -> Simulation:
        raise RuntimeError("factory unavailable")

    report = DecisionValidationRunner(broken_factory).run_case(heat_case())

    assert report.status is ValidationStatus.ERROR
    assert report.error == "RuntimeError: factory unavailable"
    assert report.checks == ()


def test_validation_models_reject_ambiguous_definitions():
    with pytest.raises(ValueError, match="subject_id"):
        DecisionExpectation(ExpectationKind.FINAL_BODY_HEATING, False)
    with pytest.raises(ValueError, match="SHA-256"):
        DecisionExpectation(ExpectationKind.GOLDEN_FINGERPRINT, "bad")
    with pytest.raises(ValueError, match="at least one"):
        DecisionValidationCase(
            "empty",
            SimulationScenario("idle", timedelta(minutes=1)),
            (),
        )
