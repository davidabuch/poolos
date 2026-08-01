"""Tests for Epic 10.14D closed-loop simulator execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from poolos.closed_loop_simulator_execution import (
    ClosedLoopExecutionDisposition,
    ClosedLoopSimulatorExecutionEngine,
)
from poolos.delivery import DeliveryEndpointKind
from poolos.environment import RuntimeMode, build_runtime_environment
from poolos.execution_coordinator import ExecutionCoordinator
from poolos.execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from poolos.execution_simulator_delivery import SimulatorStepDeliveryEngine
from poolos.execution_step_state_machine import ExecutionStepStatus
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import (
    OperationTranslationHandler,
    PoolOperation,
    SetPumpSpeed,
    StartPump,
    TranslationContext,
    TranslationResult,
    TranslatorRegistry,
    VendorCommand,
)
from poolos.observations import ObservationStore
from poolos.simulator_execution_gateway import SimulatorExecutionGateway

NOW = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class ClosedLoopTranslator:
    vendor: str = "pentair"

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, (StartPump, SetPumpSpeed))

    def translate(self, operation: PoolOperation, context: TranslationContext) -> TranslationResult:
        del context
        name = "pump.start" if isinstance(operation, StartPump) else "pump.set_speed"
        parameters = {} if isinstance(operation, StartPump) else {"rpm": operation.rpm}
        return TranslationResult(
            commands=(
                VendorCommand(
                    vendor=self.vendor,
                    operation=name,
                    target=operation.equipment_id,
                    parameters=parameters,
                ),
            )
        )


@dataclass(slots=True)
class AcknowledgingEndpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SIMULATOR
    endpoint_id: str = "sim-main"
    vendor: str = "pentair"
    calls: list[VendorCommand] = field(default_factory=list)

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        del correlation_id, timeout
        self.calls.append(command)
        return CommandReceipt(CommandStatus.ACKNOWLEDGED)


def plan(*, bad_second_expectation: bool = False, no_verification: bool = False) -> ExecutionPlan:
    start = ExecutionStep(
        step_id="plan-1:step:1",
        sequence=1,
        operation=StartPump(equipment_id="filter-pump", operation_id="op-1"),
        expected_observations=(
            {} if no_verification else {"pump.filter-pump.running": True}
        ),
        verification_required=not no_verification,
    )
    speed = ExecutionStep(
        step_id="plan-1:step:2",
        sequence=2,
        operation=SetPumpSpeed(
            equipment_id="filter-pump", operation_id="op-2", rpm=1800
        ),
        expected_observations={
            "pump.filter-pump.speed_rpm": 999 if bad_second_expectation else 1800
        },
    )
    return ExecutionPlan(
        plan_id="plan-1",
        proposal_id="proposal-1",
        authorization_id="authorization-1",
        decision_id="decision-1",
        context_id="context-1",
        created_at=NOW,
        steps=(start, speed),
    )


def components():
    endpoint = AcknowledgingEndpoint()
    registry = TranslatorRegistry()
    registry.register(ClosedLoopTranslator())
    translator = OperationTranslationHandler(
        registry,
        lambda operation: TranslationContext(vendor="pentair", controller_model="sim"),
    )
    environment = build_runtime_environment(
        mode=RuntimeMode.SIMULATION,
        installation_id="sim-installation",
        endpoints=(endpoint,),
    )
    gateway = SimulatorExecutionGateway.from_environment(environment)
    coordinator = ExecutionCoordinator()
    delivery = SimulatorStepDeliveryEngine(translator, gateway)
    return endpoint, coordinator, ClosedLoopSimulatorExecutionEngine(
        delivery_engine=delivery,
        coordinator=coordinator,
    )


def started_session(execution_plan: ExecutionPlan, coordinator: ExecutionCoordinator):
    admitted = coordinator.admit(execution_plan, occurred_at=NOW)
    started = coordinator.start(execution_plan, admitted.session, occurred_at=NOW)
    return started.session


def test_two_step_plan_completes_closed_loop() -> None:
    endpoint, coordinator, engine = components()
    execution_plan = plan()
    store = ObservationStore()

    result = engine.execute(
        execution_plan,
        started_session(execution_plan, coordinator),
        store,
        occurred_at=NOW,
    )

    assert result.disposition is ClosedLoopExecutionDisposition.COMPLETED
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.COMPLETED
    assert result.session.completed_step_ids == (
        "plan-1:step:1",
        "plan-1:step:2",
    )
    assert [item.step_lifecycle.status for item in result.step_results] == [
        ExecutionStepStatus.VERIFIED,
        ExecutionStepStatus.VERIFIED,
    ]
    assert [item.step.operation.operation_id for item in result.step_results] == [
        "op-1",
        "op-2",
    ]
    assert [command.operation for command in endpoint.calls] == [
        "pump.start",
        "pump.set_speed",
    ]
    assert store.get(
        "pump.filter-pump.running", source_id="poolos-closed-loop-simulator"
    ).value is True
    assert store.get(
        "pump.filter-pump.speed_rpm", source_id="poolos-closed-loop-simulator"
    ).value == 1800


def test_plan_lifecycle_stays_executing_until_all_steps_verified() -> None:
    _, coordinator, engine = components()
    execution_plan = plan()
    session = started_session(execution_plan, coordinator)

    result = engine.execute(execution_plan, session, ObservationStore(), occurred_at=NOW)

    assert session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert all(
        item.delivery.lifecycle.plan_id == execution_plan.plan_id
        for item in result.step_results
    )
    assert result.session.lifecycle.transitions[-1].from_status is ExecutionLifecycleStatus.EXECUTING
    assert result.session.lifecycle.transitions[-1].to_status is ExecutionLifecycleStatus.COMPLETED


def test_verification_failure_does_not_advance_failed_step() -> None:
    endpoint, coordinator, engine = components()
    execution_plan = plan(bad_second_expectation=True)

    result = engine.execute(
        execution_plan,
        started_session(execution_plan, coordinator),
        ObservationStore(),
        occurred_at=NOW,
    )

    assert result.disposition is ClosedLoopExecutionDisposition.FAILED
    assert result.session.lifecycle.status is ExecutionLifecycleStatus.EXECUTING
    assert result.session.completed_step_ids == ("plan-1:step:1",)
    assert len(result.step_results) == 2
    assert result.step_results[-1].step_lifecycle.status is ExecutionStepStatus.FAILED
    assert len(endpoint.calls) == 2


def test_verification_not_required_still_advances_after_delivery() -> None:
    _, coordinator, engine = components()
    execution_plan = plan(no_verification=True)

    result = engine.execute(
        execution_plan,
        started_session(execution_plan, coordinator),
        ObservationStore(),
        occurred_at=NOW,
    )

    assert result.disposition is ClosedLoopExecutionDisposition.COMPLETED
    assert result.step_results[0].verification.status.value == "not_required"


def test_closed_loop_rejects_nonexecuting_plan_session() -> None:
    _, coordinator, engine = components()
    execution_plan = plan()
    admitted = coordinator.admit(execution_plan, occurred_at=NOW)

    try:
        engine.execute(execution_plan, admitted.session, ObservationStore(), occurred_at=NOW)
    except ValueError as error:
        assert str(error) == "plan lifecycle must be EXECUTING"
    else:
        raise AssertionError("expected nonexecuting session rejection")
