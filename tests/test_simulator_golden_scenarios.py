"""Permanent end-to-end golden scenarios for simulator execution."""

from __future__ import annotations

import pytest

from poolos.closed_loop_simulator_execution import ClosedLoopExecutionDisposition
from poolos.execution_models import ExecutionLifecycleStatus
from poolos.execution_step_state_machine import ExecutionStepStatus
from poolos.simulator_faults import SimulatorFaultRecoveryAction
from poolos.simulator_golden_scenarios import (
    SIMULATOR_GOLDEN_SCENARIOS,
    SimulatorGoldenScenarioId,
    SimulatorGoldenScenarioRunner,
    validate_simulator_golden_catalog,
)


def test_catalog_is_complete_and_stable() -> None:
    validate_simulator_golden_catalog()
    assert len(SIMULATOR_GOLDEN_SCENARIOS) == 10
    assert {item.scenario_id for item in SIMULATOR_GOLDEN_SCENARIOS} == set(
        SimulatorGoldenScenarioId
    )


@pytest.mark.parametrize(
    "scenario_id",
    [
        SimulatorGoldenScenarioId.SINGLE_STEP_SUCCESS,
        SimulatorGoldenScenarioId.MULTI_STEP_SUCCESS,
    ],
)
def test_success_scenarios_verify_every_step_before_plan_completion(
    scenario_id: SimulatorGoldenScenarioId,
) -> None:
    result = SimulatorGoldenScenarioRunner().run(scenario_id)
    assert result.execution.disposition is ClosedLoopExecutionDisposition.COMPLETED
    assert result.execution.session.lifecycle.status is ExecutionLifecycleStatus.COMPLETED
    assert result.step_statuses
    assert all(status is ExecutionStepStatus.VERIFIED for status in result.step_statuses)
    expected_step_ids = tuple(
        item.step.step_id for item in result.execution.step_results
    )
    assert result.completed_step_ids == expected_step_ids
    assert result.delivered_command_count == len(result.execution.step_results)
    assert result.execution.fault_records == ()


def test_multi_step_scenario_preserves_independent_plan_and_step_lifecycles() -> None:
    result = SimulatorGoldenScenarioRunner().run(
        SimulatorGoldenScenarioId.MULTI_STEP_SUCCESS
    )
    assert len(result.execution.step_results) == 2
    assert result.execution.session.lifecycle.transitions[-1].from_status is (
        ExecutionLifecycleStatus.EXECUTING
    )
    assert result.execution.session.lifecycle.transitions[-1].to_status is (
        ExecutionLifecycleStatus.COMPLETED
    )
    assert result.step_statuses == (
        ExecutionStepStatus.VERIFIED,
        ExecutionStepStatus.VERIFIED,
    )


@pytest.mark.parametrize(
    "scenario_id",
    [
        SimulatorGoldenScenarioId.DELIVERY_REJECTED,
        SimulatorGoldenScenarioId.DELIVERY_FAILED,
        SimulatorGoldenScenarioId.DELIVERY_TIMED_OUT,
    ],
)
def test_delivery_fault_scenarios_terminate_without_endpoint_delivery_or_retry(
    scenario_id: SimulatorGoldenScenarioId,
) -> None:
    result = SimulatorGoldenScenarioRunner().run(scenario_id)
    assert result.execution.disposition is ClosedLoopExecutionDisposition.FAILED
    assert result.execution.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.completed_step_ids == ()
    assert result.delivered_command_count == 0
    assert len(result.execution.fault_records) == 1
    fault = result.execution.fault_records[0]
    assert fault.recovery_actions == (
        SimulatorFaultRecoveryAction.TERMINATE_STEP,
        SimulatorFaultRecoveryAction.TERMINATE_PLAN,
        SimulatorFaultRecoveryAction.AWAIT_OPERATOR,
    )


@pytest.mark.parametrize(
    "scenario_id",
    [
        SimulatorGoldenScenarioId.OBSERVATION_MISSING,
        SimulatorGoldenScenarioId.OBSERVATION_STALE,
        SimulatorGoldenScenarioId.OBSERVATION_MISMATCH,
        SimulatorGoldenScenarioId.VERIFICATION_TIMED_OUT,
    ],
)
def test_verification_fault_scenarios_never_advance_failed_step(
    scenario_id: SimulatorGoldenScenarioId,
) -> None:
    result = SimulatorGoldenScenarioRunner().run(scenario_id)
    assert result.execution.disposition is ClosedLoopExecutionDisposition.FAILED
    assert result.execution.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.completed_step_ids == ()
    assert result.delivered_command_count == 1
    assert len(result.execution.step_results) == 1
    assert result.step_statuses[0] is not ExecutionStepStatus.VERIFIED
    assert len(result.execution.fault_records) == 1
    assert result.execution.fault_records[0].recovery_actions == (
        SimulatorFaultRecoveryAction.TERMINATE_STEP,
        SimulatorFaultRecoveryAction.TERMINATE_PLAN,
        SimulatorFaultRecoveryAction.REEVALUATE,
    )


def test_deterministic_replay_produces_identical_outcome_fingerprint() -> None:
    result = SimulatorGoldenScenarioRunner().run(
        SimulatorGoldenScenarioId.DETERMINISTIC_REPLAY
    )
    assert result.replay_equivalent is True
    assert result.execution.disposition is ClosedLoopExecutionDisposition.COMPLETED
    assert result.outcome_fingerprint


def test_run_all_executes_every_catalog_entry_in_order() -> None:
    results = SimulatorGoldenScenarioRunner().run_all()
    assert tuple(item.scenario_id for item in results) == tuple(
        definition.scenario_id for definition in SIMULATOR_GOLDEN_SCENARIOS
    )
