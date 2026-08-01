"""Tests for deterministic simulator fault injection and safe recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from poolos.closed_loop_simulator_execution import ClosedLoopExecutionDisposition, ClosedLoopSimulatorExecutionEngine
from poolos.delivery import DeliveryEndpointKind
from poolos.environment import RuntimeMode, build_runtime_environment
from poolos.execution_coordinator import ExecutionCoordinator
from poolos.execution_models import ExecutionPlan, ExecutionStep
from poolos.execution_simulator_delivery import SimulatorStepDeliveryEngine
from poolos.execution_step_state_machine import ExecutionStepStatus
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import OperationTranslationHandler, PoolOperation, StartPump, TranslationContext, TranslationResult, TranslatorRegistry, VendorCommand
from poolos.observations import ObservationStore
from poolos.simulator_execution_gateway import SimulatorExecutionGateway
from poolos.simulator_faults import SimulatorFaultKind, SimulatorFaultPlan, SimulatorFaultRecoveryAction, SimulatorFaultRule

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class Translator:
    vendor: str = "pentair"

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, StartPump)

    def translate(self, operation: PoolOperation, context: TranslationContext) -> TranslationResult:
        del context
        return TranslationResult(commands=(VendorCommand(vendor="pentair", operation="pump.start", target=operation.equipment_id),))


@dataclass(slots=True)
class Endpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SIMULATOR
    endpoint_id: str = "sim-main"
    vendor: str = "pentair"
    calls: list[VendorCommand] = field(default_factory=list)

    def deliver(self, command: VendorCommand, *, correlation_id: str, timeout: float | None = None) -> CommandReceipt:
        del correlation_id, timeout
        self.calls.append(command)
        return CommandReceipt(CommandStatus.ACKNOWLEDGED)


def setup(kind: SimulatorFaultKind, **kwargs: object):
    endpoint = Endpoint()
    registry = TranslatorRegistry()
    registry.register(Translator())
    translator = OperationTranslationHandler(registry, lambda operation: TranslationContext(vendor="pentair", controller_model="sim"))
    environment = build_runtime_environment(mode=RuntimeMode.SIMULATION, installation_id="sim", endpoints=(endpoint,))
    delivery = SimulatorStepDeliveryEngine(translator, SimulatorExecutionGateway.from_environment(environment))
    coordinator = ExecutionCoordinator()
    rule = SimulatorFaultRule(rule_id="fault-1", step_id="plan-1:step:1", kind=kind, **kwargs)
    engine = ClosedLoopSimulatorExecutionEngine(delivery_engine=delivery, coordinator=coordinator, fault_plan=SimulatorFaultPlan((rule,)))
    step = ExecutionStep(step_id="plan-1:step:1", sequence=1, operation=StartPump(equipment_id="filter-pump", operation_id="op-1"), expected_observations={"pump.filter-pump.running": True})
    plan = ExecutionPlan(plan_id="plan-1", proposal_id="proposal-1", authorization_id="authorization-1", decision_id="decision-1", context_id="context-1", created_at=NOW, steps=(step,))
    admitted = coordinator.admit(plan, occurred_at=NOW)
    session = coordinator.start(plan, admitted.session, occurred_at=NOW).session
    return endpoint, engine, plan, session


@pytest.mark.parametrize("kind,expected", [
    (SimulatorFaultKind.DELIVERY_REJECTED, ExecutionStepStatus.FAILED),
    (SimulatorFaultKind.DELIVERY_FAILED, ExecutionStepStatus.FAILED),
    (SimulatorFaultKind.DELIVERY_TIMED_OUT, ExecutionStepStatus.TIMED_OUT),
])
def test_delivery_faults_terminate_without_calling_endpoint(kind: SimulatorFaultKind, expected: ExecutionStepStatus) -> None:
    endpoint, engine, plan, session = setup(kind)
    result = engine.execute(plan, session, ObservationStore(), occurred_at=NOW)
    assert result.disposition is ClosedLoopExecutionDisposition.FAILED
    assert endpoint.calls == []
    assert result.fault_records[0].kind is kind
    assert SimulatorFaultRecoveryAction.AWAIT_OPERATOR in result.fault_records[0].recovery_actions
    assert result.session.completed_step_ids == ()


@pytest.mark.parametrize("kind,kwargs", [
    (SimulatorFaultKind.OBSERVATION_MISSING, {}),
    (SimulatorFaultKind.OBSERVATION_STALE, {}),
    (SimulatorFaultKind.OBSERVATION_MISMATCH, {"replacement_value": False}),
    (SimulatorFaultKind.VERIFICATION_TIMEOUT, {}),
])
def test_observation_faults_prevent_coordinator_advancement(kind: SimulatorFaultKind, kwargs: dict[str, object]) -> None:
    endpoint, engine, plan, session = setup(kind, **kwargs)
    result = engine.execute(plan, session, ObservationStore(), occurred_at=NOW)
    assert result.disposition is ClosedLoopExecutionDisposition.FAILED
    assert len(endpoint.calls) == 1
    assert result.session.completed_step_ids == ()
    assert result.fault_records[0].kind is kind
    assert SimulatorFaultRecoveryAction.REEVALUATE in result.fault_records[0].recovery_actions


def test_fault_plan_rejects_duplicate_rule_identity() -> None:
    rule = SimulatorFaultRule(rule_id="same", step_id="step-1", kind=SimulatorFaultKind.DELIVERY_FAILED)
    with pytest.raises(ValueError, match="rule IDs"):
        SimulatorFaultPlan((rule, rule))


def test_fault_records_are_deterministic() -> None:
    _, first_engine, plan, session = setup(SimulatorFaultKind.OBSERVATION_MISMATCH, replacement_value=False)
    first = first_engine.execute(plan, session, ObservationStore(), occurred_at=NOW)
    _, second_engine, plan2, session2 = setup(SimulatorFaultKind.OBSERVATION_MISMATCH, replacement_value=False)
    second = second_engine.execute(plan2, session2, ObservationStore(), occurred_at=NOW)
    assert first.fault_records == second.fault_records
