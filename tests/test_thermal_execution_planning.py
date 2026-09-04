from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from poolos.spa_thermal_policy import (
    SpaHeatingMode,
    SpaPolicyInput,
    SpaThermalPolicyTracker,
    SpaUserSource,
)
from poolos.thermal_execution_planning import (
    ThermalCurrentState,
    ThermalDesiredState,
    ThermalExecutionPlanBuilder,
    ThermalPlanDisposition,
    desired_pool_state,
    desired_spa_state,
)
from poolos.thermal_source_policy import (
    HeatSourcePermissions,
    PoolHeatingMode,
    ThermalSourceInput,
    ThermalSourceSelector,
)


LOCAL = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 8, 27, 14, 0, tzinfo=LOCAL)


def _desired(
    source: PhysicalHeatMode,
    rpm: int | None,
    *,
    body: ThermalBody = ThermalBody.POOL,
    reason: str = "test_policy_selection",
) -> ThermalDesiredState:
    return ThermalDesiredState(
        evaluated_at=NOW,
        body=body,
        requested_mode="solar_preferred",
        selected_source=source,
        required_pump_rpm=rpm,
        reason_code=reason,
        rpm_reason_code=None if rpm is None else f"operating_baseline:{rpm}_rpm",
        rationale=("Existing thermal policy selected the requested physical state.",),
        criteria=("trusted_native_observations",),
        evidence={"temperature_f": 86.0, "target_f": 90.0},
    )


def _current(
    source: PhysicalHeatMode,
    rpm: int | None,
    *,
    body: ThermalBody = ThermalBody.POOL,
    htmode: str = "0",
) -> ThermalCurrentState:
    return ThermalCurrentState(NOW, body, source, rpm, htmode=htmode)


def _operation_kinds(plan: object) -> tuple[type[object], ...]:
    return tuple(type(item) for item in plan.operations)  # type: ignore[attr-defined]


def test_pool_policy_adapts_source_rpm_reason_and_evidence_without_authority() -> None:
    observation = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        86.0,
        90.0,
        100.0,
        PoolHeatingMode.SOLAR_PREFERRED,
    )
    assessment = ThermalSourceSelector().evaluate(observation)

    desired = desired_pool_state(observation, assessment)

    assert desired.body is ThermalBody.POOL
    assert desired.selected_source is PhysicalHeatMode.SOLAR
    assert desired.required_pump_rpm == 2900
    assert desired.reason_code == "solar_preferred_physical_solar"
    assert desired.rpm_reason_code == "operating_baseline:pool_solar:2900_rpm"
    assert desired.evidence["collector_differential_f"] == 14.0
    assert desired.criteria
    assert desired.authority == "none"
    assert desired.command_delivery_enabled is False


def test_pool_solar_preferred_gas_fallback_and_target_satisfied_off() -> None:
    gas_input = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        86.0,
        90.0,
        80.0,
        PoolHeatingMode.SOLAR_PREFERRED,
    )
    off_input = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        90.0,
        90.0,
        100.0,
        PoolHeatingMode.SOLAR_PREFERRED,
    )

    gas = desired_pool_state(gas_input, ThermalSourceSelector().evaluate(gas_input))
    off = desired_pool_state(off_input, ThermalSourceSelector().evaluate(off_input))

    assert gas.selected_source is PhysicalHeatMode.GAS
    assert gas.required_pump_rpm == 3000
    assert gas.fallback_reason == "solar_preferred_gas_fallback"
    assert off.selected_source is PhysicalHeatMode.OFF
    assert off.required_pump_rpm is None


def test_pool_permission_veto_and_missing_evidence_block_actuation_plan() -> None:
    veto_input = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        86.0,
        90.0,
        100.0,
        PoolHeatingMode.SOLAR_ONLY,
        HeatSourcePermissions(solar_allowed=False, solar_veto_reason="operator veto"),
    )
    missing_input = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        None,
        90.0,
        100.0,
    )
    builder = ThermalExecutionPlanBuilder()

    veto = builder.build(
        desired_pool_state(veto_input, ThermalSourceSelector().evaluate(veto_input)),
        _current(PhysicalHeatMode.SOLAR, 2900),
    )
    missing = builder.build(
        desired_pool_state(
            missing_input,
            ThermalSourceSelector().evaluate(missing_input),
        ),
        _current(PhysicalHeatMode.OFF, 0),
    )

    assert veto.disposition is ThermalPlanDisposition.BLOCKED
    assert "heat_source_permission_veto" in veto.blocking_reasons
    assert missing.disposition is ThermalPlanDisposition.BLOCKED
    assert missing.operations == ()


def test_spa_user_session_preserves_solar_qualification_and_gas_fallback() -> None:
    tracker = SpaThermalPolicyTracker()
    first_input = SpaPolicyInput(
        NOW,
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        130.0,
    )
    qualified_input = SpaPolicyInput(
        NOW + timedelta(minutes=2),
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        130.0,
    )
    gas = desired_spa_state(first_input, tracker.evaluate(first_input))
    solar = desired_spa_state(qualified_input, tracker.evaluate(qualified_input))

    assert gas.selected_source is PhysicalHeatMode.GAS
    assert gas.required_pump_rpm == 3000
    assert gas.fallback_reason == "spa_heat_up_gas"
    assert solar.selected_source is PhysicalHeatMode.SOLAR
    assert solar.required_pump_rpm == 2900
    assert "user_session" in solar.criteria


def test_spa_opportunistic_policy_remains_solar_only_and_distinct_from_pool() -> None:
    tracker = SpaThermalPolicyTracker()
    first = SpaPolicyInput(
        NOW,
        False,
        None,
        90.0,
        100.0,
        130.0,
        pool_demand_satisfied=True,
    )
    active = SpaPolicyInput(
        NOW + timedelta(minutes=2),
        False,
        None,
        90.0,
        100.0,
        130.0,
        pool_demand_satisfied=True,
    )
    tracker.evaluate(first)
    solar = desired_spa_state(active, tracker.evaluate(active))
    unavailable_input = SpaPolicyInput(
        NOW + timedelta(minutes=3),
        False,
        None,
        90.0,
        100.0,
        110.0,
        pool_demand_satisfied=True,
    )
    unavailable = desired_spa_state(
        unavailable_input,
        tracker.evaluate(unavailable_input),
    )

    assert solar.selected_source is PhysicalHeatMode.SOLAR
    assert "gas_fallback_forbidden" in solar.criteria
    assert unavailable.selected_source in {PhysicalHeatMode.SOLAR, PhysicalHeatMode.OFF}
    assert unavailable.selected_source is not PhysicalHeatMode.GAS


@pytest.mark.parametrize(
    ("current_source", "current_rpm", "desired_source", "desired_rpm", "types"),
    (
        (
            PhysicalHeatMode.OFF,
            0,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetPumpSpeed, SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.OFF,
            0,
            PhysicalHeatMode.GAS,
            3000,
            (SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.SOLAR,
            2900,
            PhysicalHeatMode.GAS,
            3000,
            (SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.GAS,
            3000,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetHeatMode, SetPumpSpeed),
        ),
        (
            PhysicalHeatMode.SOLAR,
            2900,
            PhysicalHeatMode.OFF,
            None,
            (SetHeatMode,),
        ),
        (
            PhysicalHeatMode.GAS,
            3000,
            PhysicalHeatMode.OFF,
            None,
            (SetHeatMode,),
        ),
        (
            PhysicalHeatMode.SOLAR,
            2600,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetPumpSpeed,),
        ),
        (
            PhysicalHeatMode.GAS,
            2900,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetHeatMode,),
        ),
    ),
)
def test_coupled_transition_order_is_explicit_and_avoids_unnecessary_commands(
    current_source: PhysicalHeatMode,
    current_rpm: int,
    desired_source: PhysicalHeatMode,
    desired_rpm: int | None,
    types: tuple[type[object], ...],
) -> None:
    plan = ThermalExecutionPlanBuilder().build(
        _desired(desired_source, desired_rpm),
        _current(current_source, current_rpm),
    )

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == types
    assert tuple(item.operation_id for item in plan.step_specifications) == tuple(
        item.operation_id for item in plan.operations
    )
    assert plan.command_delivery_enabled is False


def test_already_converged_is_a_command_free_noop() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.SOLAR, 2900),
        _current(PhysicalHeatMode.SOLAR, 2900),
    )

    assert plan.disposition is ThermalPlanDisposition.ALREADY_CONVERGED
    assert plan.operations == ()
    assert plan.step_specifications == ()


@pytest.mark.parametrize(
    ("observed_rpm", "expected_disposition", "expects_rpm_command"),
    (
        (2900, ThermalPlanDisposition.ALREADY_CONVERGED, False),
        (2880, ThermalPlanDisposition.ALREADY_CONVERGED, False),
        (2874, ThermalPlanDisposition.READY, True),
    ),
)
def test_planning_uses_the_same_rpm_tolerance_as_verification(
    observed_rpm: int,
    expected_disposition: ThermalPlanDisposition,
    expects_rpm_command: bool,
) -> None:
    plan = ThermalExecutionPlanBuilder(pump_rpm_tolerance=25).build(
        _desired(PhysicalHeatMode.SOLAR, 2900),
        _current(PhysicalHeatMode.SOLAR, observed_rpm),
    )

    assert plan.disposition is expected_disposition
    assert any(isinstance(item, SetPumpSpeed) for item in plan.operations) is expects_rpm_command


def test_correct_source_and_rpm_within_tolerance_is_already_converged() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.GAS, 3000),
        _current(PhysicalHeatMode.GAS, 2975),
    )

    assert plan.disposition is ThermalPlanDisposition.ALREADY_CONVERGED
    assert plan.operations == ()


@pytest.mark.parametrize("source", (PhysicalHeatMode.SOLAR, PhysicalHeatMode.GAS))
def test_missing_authoritative_rpm_blocks_active_thermal_plan(
    source: PhysicalHeatMode,
) -> None:
    rpm = 2900 if source is PhysicalHeatMode.SOLAR else 3000
    plan = ThermalExecutionPlanBuilder().build(
        _desired(source, rpm),
        _current(PhysicalHeatMode.OFF, None),
    )

    assert plan.disposition is ThermalPlanDisposition.BLOCKED
    assert "pump_observation_missing" in plan.blocking_reasons
    assert plan.operations == ()


def test_off_does_not_require_pump_rpm_and_only_deselects_heat_source() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.OFF, None),
        _current(PhysicalHeatMode.SOLAR, None),
    )

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (SetHeatMode,)
    assert not any(isinstance(item, SetPumpSpeed) for item in plan.operations)


def test_pool_safe_off_is_not_blocked_by_irrelevant_missing_collector() -> None:
    observation = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        90.0,
        90.0,
        None,
        PoolHeatingMode.SOLAR_ONLY,
    )
    desired = desired_pool_state(observation, ThermalSourceSelector().evaluate(observation))
    plan = ThermalExecutionPlanBuilder().build(
        desired,
        _current(PhysicalHeatMode.SOLAR, 2900),
    )

    assert desired.selected_source is PhysicalHeatMode.OFF
    assert desired.evidence_usable
    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (SetHeatMode,)


def test_spa_safe_off_is_not_blocked_by_irrelevant_missing_collector() -> None:
    observation = SpaPolicyInput(
        NOW,
        False,
        None,
        100.0,
        100.0,
        None,
        pool_demand_satisfied=True,
    )
    desired = desired_spa_state(observation, SpaThermalPolicyTracker().evaluate(observation))
    plan = ThermalExecutionPlanBuilder().build(
        desired,
        _current(
            PhysicalHeatMode.SOLAR,
            2900,
            body=ThermalBody.HOT_TUB,
        ),
    )

    assert desired.selected_source is PhysicalHeatMode.OFF
    assert desired.evidence_usable
    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (SetHeatMode,)


def test_missing_collector_blocks_solar_activation_selected_from_prior_evidence() -> None:
    selector = ThermalSourceSelector()
    initial = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        86.0,
        90.0,
        100.0,
        PoolHeatingMode.SOLAR_ONLY,
    )
    selector.evaluate(initial)
    qualified = ThermalSourceInput(
        NOW + timedelta(minutes=10),
        True,
        False,
        False,
        86.0,
        90.0,
        100.0,
        PoolHeatingMode.SOLAR_ONLY,
    )
    assessment = selector.evaluate(qualified)
    missing = ThermalSourceInput(
        qualified.evaluated_at,
        True,
        False,
        False,
        86.0,
        90.0,
        None,
        PoolHeatingMode.SOLAR_ONLY,
    )

    desired = desired_pool_state(missing, assessment)
    plan = ThermalExecutionPlanBuilder().build(
        desired,
        _current(PhysicalHeatMode.OFF, 2600),
    )

    assert assessment.heat_source.value == "solar"
    assert not desired.evidence_usable
    assert plan.disposition is ThermalPlanDisposition.BLOCKED
    assert plan.operations == ()


def test_missing_pool_temperature_blocks_gas_activation() -> None:
    valid = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        86.0,
        90.0,
        None,
        PoolHeatingMode.GAS_ONLY,
    )
    assessment = ThermalSourceSelector().evaluate(valid)
    missing = ThermalSourceInput(
        NOW,
        True,
        False,
        False,
        None,
        90.0,
        None,
        PoolHeatingMode.GAS_ONLY,
    )

    plan = ThermalExecutionPlanBuilder().build(
        desired_pool_state(missing, assessment),
        _current(PhysicalHeatMode.OFF, 2600),
    )

    assert assessment.heat_source.value == "gas"
    assert plan.disposition is ThermalPlanDisposition.BLOCKED
    assert plan.operations == ()


def test_missing_collector_blocks_spa_solar_activation() -> None:
    tracker = SpaThermalPolicyTracker()
    initial = SpaPolicyInput(
        NOW,
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        130.0,
    )
    tracker.evaluate(initial)
    qualified = SpaPolicyInput(
        NOW + timedelta(minutes=2),
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        130.0,
    )
    assessment = tracker.evaluate(qualified)
    missing = SpaPolicyInput(
        qualified.evaluated_at,
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        None,
    )

    plan = ThermalExecutionPlanBuilder().build(
        desired_spa_state(missing, assessment),
        _current(
            PhysicalHeatMode.OFF,
            2600,
            body=ThermalBody.HOT_TUB,
        ),
    )

    assert assessment.heat_source.value == "solar"
    assert plan.disposition is ThermalPlanDisposition.BLOCKED
    assert plan.operations == ()


def test_spa_permission_veto_remains_blocked() -> None:
    observation = SpaPolicyInput(
        NOW,
        True,
        SpaUserSource.HOME_ASSISTANT,
        90.0,
        100.0,
        None,
        heating_mode=SpaHeatingMode.GAS_ONLY,
        permissions=HeatSourcePermissions(gas_allowed=False),
    )
    assessment = SpaThermalPolicyTracker().evaluate(observation)
    plan = ThermalExecutionPlanBuilder().build(
        desired_spa_state(observation, assessment),
        _current(
            PhysicalHeatMode.OFF,
            2600,
            body=ThermalBody.HOT_TUB,
        ),
    )

    assert assessment.reason_code == "gas_permission_veto"
    assert plan.disposition is ThermalPlanDisposition.BLOCKED
    assert "heat_source_permission_veto" in plan.blocking_reasons


def test_native_heater_and_pump_expectations_prove_source_without_htmode() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.GAS, 3000),
        _current(PhysicalHeatMode.OFF, 0, htmode="0"),
    )

    assert plan.expected_final_state == {
        "pool.raw_heater_id": "H0001",
        "pump.rpm": 3000,
    }
    source_spec = plan.step_specifications[1]
    assert source_spec.expected_observations == {"pool.raw_heater_id": "H0001"}
    assert "htmode" not in repr(source_spec.expected_observations).casefold()
    assert source_spec.metadata["htmode_is_context_only"] == "true"


def test_stale_or_degraded_current_truth_cannot_create_plan() -> None:
    source_stale = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.SOLAR, 2900),
        ThermalCurrentState(
            NOW,
            ThermalBody.POOL,
            PhysicalHeatMode.OFF,
            0,
            source_evidence_usable=False,
        ),
    )
    rpm_stale = ThermalExecutionPlanBuilder().build(
        _desired(PhysicalHeatMode.SOLAR, 2900),
        ThermalCurrentState(
            NOW,
            ThermalBody.POOL,
            PhysicalHeatMode.OFF,
            0,
            pump_evidence_usable=False,
        ),
    )

    assert source_stale.disposition is ThermalPlanDisposition.BLOCKED
    assert rpm_stale.disposition is ThermalPlanDisposition.BLOCKED
    assert source_stale.operations == rpm_stale.operations == ()


def test_plan_identity_and_order_are_deterministic() -> None:
    builder = ThermalExecutionPlanBuilder()
    desired = _desired(PhysicalHeatMode.SOLAR, 2900)
    current = _current(PhysicalHeatMode.OFF, 0)

    first = builder.build(desired, current)
    second = builder.build(desired, current)

    assert first.plan_id == second.plan_id
    assert [item.operation_id for item in first.operations] == [
        item.operation_id for item in second.operations
    ]


def test_inactive_pool_cold_start_plans_body_prime_final_rpm_then_solar() -> None:
    desired = _desired(
        PhysicalHeatMode.SOLAR,
        2900,
        body=ThermalBody.POOL,
    )
    current = ThermalCurrentState(
        NOW,
        ThermalBody.POOL,
        PhysicalHeatMode.OFF,
        0,
        body_active=False,
    )

    plan = ThermalExecutionPlanBuilder().build(desired, current)

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (
        SetBodyActive,
        SetPumpSpeed,
        SetPumpSpeed,
        SetHeatMode,
    )

    body = plan.operations[0]
    prime = plan.operations[1]
    final_rpm = plan.operations[2]
    source = plan.operations[3]

    assert isinstance(body, SetBodyActive)
    assert body.equipment_id == ThermalBody.POOL.value
    assert body.active is True
    assert plan.step_specifications[0].expected_observations == {
        "pool.active": True
    }

    assert isinstance(prime, SetPumpSpeed)
    assert prime.rpm == 3000
    assert plan.step_specifications[1].expected_observations == {
        "pump.rpm": 3000
    }
    assert plan.step_specifications[1].metadata["priming_step"] == "true"
    assert (
        plan.step_specifications[1].metadata["minimum_verified_hold_seconds"]
        == "60"
    )

    assert isinstance(final_rpm, SetPumpSpeed)
    assert final_rpm.rpm == 2900

    assert isinstance(source, SetHeatMode)
    assert source.mode is PhysicalHeatMode.SOLAR

    assert "target_body_activation_required" in plan.change_reasons
    assert "cold_start_priming_required" in plan.change_reasons


def test_inactive_hot_tub_gas_start_primes_once_at_3000() -> None:
    desired = _desired(
        PhysicalHeatMode.GAS,
        3000,
        body=ThermalBody.HOT_TUB,
    )
    current = ThermalCurrentState(
        NOW,
        ThermalBody.HOT_TUB,
        PhysicalHeatMode.OFF,
        0,
        body_active=False,
    )

    plan = ThermalExecutionPlanBuilder().build(desired, current)

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (
        SetBodyActive,
        SetPumpSpeed,
        SetHeatMode,
    )

    body = plan.operations[0]
    prime = plan.operations[1]
    source = plan.operations[2]

    assert isinstance(body, SetBodyActive)
    assert body.equipment_id == ThermalBody.HOT_TUB.value
    assert body.active is True
    assert plan.step_specifications[0].expected_observations == {
        "spa.active": True
    }

    assert isinstance(prime, SetPumpSpeed)
    assert prime.rpm == 3000
    assert (
        plan.step_specifications[1].metadata["minimum_verified_hold_seconds"]
        == "60"
    )

    assert isinstance(source, SetHeatMode)
    assert source.mode is PhysicalHeatMode.GAS


def test_active_running_pool_does_not_reprime_for_solar_transition() -> None:
    desired = _desired(
        PhysicalHeatMode.SOLAR,
        2900,
        body=ThermalBody.POOL,
    )
    current = ThermalCurrentState(
        NOW,
        ThermalBody.POOL,
        PhysicalHeatMode.OFF,
        2600,
        body_active=True,
    )

    plan = ThermalExecutionPlanBuilder().build(desired, current)

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (SetPumpSpeed, SetHeatMode)
    assert not any(isinstance(item, SetBodyActive) for item in plan.operations)
    assert all(
        specification.metadata.get("priming_step") != "true"
        for specification in plan.step_specifications
    )
    assert "cold_start_priming_required" not in plan.change_reasons


def test_active_body_with_stopped_pump_still_requires_cold_start_prime() -> None:
    desired = _desired(
        PhysicalHeatMode.SOLAR,
        2900,
        body=ThermalBody.POOL,
    )
    current = ThermalCurrentState(
        NOW,
        ThermalBody.POOL,
        PhysicalHeatMode.OFF,
        0,
        body_active=True,
    )

    plan = ThermalExecutionPlanBuilder().build(desired, current)

    assert plan.disposition is ThermalPlanDisposition.READY
    assert _operation_kinds(plan) == (
        SetPumpSpeed,
        SetPumpSpeed,
        SetHeatMode,
    )

    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert plan.operations[0].rpm == 3000
    assert plan.step_specifications[0].metadata["priming_step"] == "true"

    assert isinstance(plan.operations[1], SetPumpSpeed)
    assert plan.operations[1].rpm == 2900

    assert "cold_start_priming_required" in plan.change_reasons
