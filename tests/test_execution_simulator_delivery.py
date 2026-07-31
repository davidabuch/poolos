"""Tests for execution-step simulator delivery and immutable receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from poolos.delivery import DeliveryEndpointKind
from poolos.environment import RuntimeMode, build_runtime_environment
from poolos.execution_models import (
    ExecutionLifecycleStatus,
    ExecutionPlan,
    ExecutionStep,
)
from poolos.execution_simulator_delivery import (
    SimulatorStepDeliveryDisposition,
    SimulatorStepDeliveryEngine,
    SimulatorStepDeliveryRequest,
)
from poolos.execution_state_machine import ExecutionLifecycle, ExecutionStateMachine
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import (
    OperationTranslationHandler,
    PoolOperation,
    StartPump,
    TranslationContext,
    TranslationResult,
    TranslatorRegistry,
    VendorCommand,
)
from poolos.integration.exceptions import UnsupportedOperationError
from poolos.simulator_execution_gateway import SimulatorExecutionGateway

UTC = timezone.utc
CREATED = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
DELIVERED = datetime(2026, 7, 31, 12, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SequenceTranslator:
    vendor: str = "pentair"
    command_count: int = 2
    fail: bool = False

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, StartPump)

    def translate(self, operation: PoolOperation, context: TranslationContext) -> TranslationResult:
        if self.fail:
            raise UnsupportedOperationError(self.vendor, type(operation))
        return TranslationResult(
            commands=tuple(
                VendorCommand(
                    vendor=self.vendor,
                    operation=f"pump.step_{index}",
                    target=operation.equipment_id,
                )
                for index in range(1, self.command_count + 1)
            )
        )


@dataclass(slots=True)
class SequencedSimulatorEndpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SIMULATOR
    endpoint_id: str = "sim-main"
    vendor: str = "pentair"
    statuses: list[CommandStatus] = field(
        default_factory=lambda: [CommandStatus.ACKNOWLEDGED] * 2
    )
    calls: list[tuple[VendorCommand, str, float | None]] = field(default_factory=list)

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        self.calls.append((command, correlation_id, timeout))
        return CommandReceipt(self.statuses[len(self.calls) - 1])


def plan_and_lifecycle() -> tuple[ExecutionPlan, ExecutionStep, ExecutionLifecycle]:
    operation = StartPump(equipment_id="filter-pump", operation_id="operation-1")
    step = ExecutionStep(
        step_id="plan-1:step:1",
        sequence=1,
        operation=operation,
        verification_required=False,
    )
    plan = ExecutionPlan(
        plan_id="plan-1",
        proposal_id="proposal-1",
        authorization_id="authorization-1",
        decision_id="decision-1",
        context_id="context-1",
        created_at=CREATED,
        steps=(step,),
    )
    machine = ExecutionStateMachine()
    lifecycle = machine.initialize(plan)
    planned = machine.transition(
        lifecycle,
        to_status=ExecutionLifecycleStatus.PLANNED,
        occurred_at=CREATED,
        reason="plan admitted",
    ).lifecycle
    executing = machine.transition(
        planned,
        to_status=ExecutionLifecycleStatus.EXECUTING,
        occurred_at=CREATED,
        reason="execution started",
    ).lifecycle
    return plan, step, executing


def engine(
    endpoint: SequencedSimulatorEndpoint,
    *,
    command_count: int = 2,
    fail_translation: bool = False,
) -> SimulatorStepDeliveryEngine:
    registry = TranslatorRegistry()
    registry.register(
        SequenceTranslator(command_count=command_count, fail=fail_translation)
    )
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
    return SimulatorStepDeliveryEngine(translator, gateway)


def request(
    plan: ExecutionPlan,
    step: ExecutionStep,
    lifecycle: ExecutionLifecycle,
    **kwargs: object,
) -> SimulatorStepDeliveryRequest:
    return SimulatorStepDeliveryRequest(
        plan=plan,
        step=step,
        lifecycle=lifecycle,
        occurred_at=DELIVERED,
        **kwargs,
    )


def test_delivers_translated_commands_in_order_and_preserves_receipts() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint).deliver(request(plan, step, lifecycle, timeout=2.5))

    assert result.disposition is SimulatorStepDeliveryDisposition.DELIVERED
    assert result.lifecycle.status is ExecutionLifecycleStatus.DELIVERED
    assert [item.to_status for item in result.transitions] == [
        ExecutionLifecycleStatus.DELIVERING,
        ExecutionLifecycleStatus.DELIVERED,
    ]
    assert [call[0].operation for call in endpoint.calls] == ["pump.step_1", "pump.step_2"]
    assert all(call[2] == 2.5 for call in endpoint.calls)
    assert [item.sequence for item in result.receipts] == [1, 2]
    assert [item.delivery_receipt.status for item in result.receipts] == [
        CommandStatus.ACKNOWLEDGED,
        CommandStatus.ACKNOWLEDGED,
    ]
    assert result.unattempted_commands == ()
    assert result.failure_reason is None


def test_rejected_receipt_stops_delivery_and_fails_lifecycle() -> None:
    endpoint = SequencedSimulatorEndpoint(
        statuses=[CommandStatus.REJECTED, CommandStatus.ACKNOWLEDGED]
    )
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint).deliver(request(plan, step, lifecycle))

    assert result.disposition is SimulatorStepDeliveryDisposition.REJECTED
    assert result.lifecycle.status is ExecutionLifecycleStatus.FAILED
    assert len(endpoint.calls) == 1
    assert len(result.receipts) == 1
    assert len(result.unattempted_commands) == 1
    assert result.failure_reason == "simulator_command_rejected"


@pytest.mark.parametrize(
    ("status", "disposition", "lifecycle_status"),
    [
        (CommandStatus.FAILED, SimulatorStepDeliveryDisposition.FAILED, ExecutionLifecycleStatus.FAILED),
        (CommandStatus.TIMED_OUT, SimulatorStepDeliveryDisposition.TIMED_OUT, ExecutionLifecycleStatus.TIMED_OUT),
    ],
)
def test_failed_and_timed_out_receipts_map_to_terminal_lifecycle(
    status: CommandStatus,
    disposition: SimulatorStepDeliveryDisposition,
    lifecycle_status: ExecutionLifecycleStatus,
) -> None:
    endpoint = SequencedSimulatorEndpoint(statuses=[status, CommandStatus.ACKNOWLEDGED])
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint).deliver(request(plan, step, lifecycle))

    assert result.disposition is disposition
    assert result.lifecycle.status is lifecycle_status
    assert len(endpoint.calls) == 1
    assert len(result.unattempted_commands) == 1


def test_translation_failure_is_recorded_without_gateway_call() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint, fail_translation=True).deliver(
        request(plan, step, lifecycle)
    )

    assert result.disposition is SimulatorStepDeliveryDisposition.FAILED
    assert result.lifecycle.status is ExecutionLifecycleStatus.FAILED
    assert result.translation is None
    assert result.receipts == ()
    assert endpoint.calls == []
    assert result.failure_reason is not None
    assert result.failure_reason.startswith("translation_failed:")


def test_zero_command_translation_is_a_delivered_no_op() -> None:
    endpoint = SequencedSimulatorEndpoint(statuses=[])
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint, command_count=0).deliver(request(plan, step, lifecycle))

    assert result.delivered
    assert result.receipts == ()
    assert endpoint.calls == []
    assert result.lifecycle.status is ExecutionLifecycleStatus.DELIVERED


def test_request_requires_exact_plan_step() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()
    foreign = ExecutionStep(
        step_id=step.step_id,
        sequence=step.sequence,
        operation=StartPump(equipment_id="other", operation_id="operation-other"),
        verification_required=False,
    )

    with pytest.raises(ValueError, match="exact member"):
        engine(endpoint).deliver(request(plan, foreign, lifecycle))

    assert endpoint.calls == []


def test_request_requires_executing_lifecycle_for_same_plan() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, _ = plan_and_lifecycle()
    lifecycle = ExecutionStateMachine().initialize(plan)

    with pytest.raises(ValueError, match="EXECUTING"):
        engine(endpoint).deliver(request(plan, step, lifecycle))


def test_request_rejects_cross_plan_lifecycle() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()
    other_plan = ExecutionPlan(
        plan_id="plan-2",
        proposal_id=plan.proposal_id,
        authorization_id=plan.authorization_id,
        decision_id=plan.decision_id,
        context_id=plan.context_id,
        created_at=plan.created_at,
        steps=(step,),
    )

    with pytest.raises(ValueError, match="plan_id"):
        engine(endpoint).deliver(request(other_plan, step, lifecycle))


def test_attempt_and_receipt_ids_are_deterministic() -> None:
    first_endpoint = SequencedSimulatorEndpoint()
    second_endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()
    delivery_request = request(plan, step, lifecycle, metadata={"source": "test"})

    first = engine(first_endpoint).deliver(delivery_request)
    second = engine(second_endpoint).deliver(delivery_request)

    assert first.attempt_id == second.attempt_id
    assert [item.receipt_id for item in first.receipts] == [
        item.receipt_id for item in second.receipts
    ]


def test_result_does_not_advance_coordinator_or_verify_step() -> None:
    endpoint = SequencedSimulatorEndpoint()
    plan, step, lifecycle = plan_and_lifecycle()

    result = engine(endpoint).deliver(request(plan, step, lifecycle))

    public_names = set(dir(result))
    assert result.lifecycle.status is ExecutionLifecycleStatus.DELIVERED
    assert "verification_result" not in public_names
    assert "coordination_session" not in public_names
    assert "completed" not in public_names
