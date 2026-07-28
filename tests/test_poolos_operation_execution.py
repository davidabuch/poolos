"""Tests for canonical operation translation and delivery composition."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from poolos.delivery import EndpointRegistry, VendorCommandGateway
from poolos.execution import ExecutionEngine
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
from poolos.operation_execution import (
    OperationDeliveryContext,
    OperationExecutionHandler,
)
from poolos.work_dispatch import build_work_dispatcher


@dataclass(frozen=True, slots=True)
class SequenceTranslator:
    vendor: str = "pentair"
    command_count: int = 3

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, StartPump)

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        return TranslationResult(
            commands=tuple(
                VendorCommand(
                    vendor=self.vendor,
                    operation=f"pump.step_{index}",
                    target=operation.equipment_id,
                )
                for index in range(1, self.command_count + 1)
            ),
            warnings=("example warning",),
            metadata={"controller": context.controller_model},
        )


@dataclass(slots=True)
class SequencedEndpoint:
    endpoint_id: str = "main-controller"
    vendor: str = "pentair"
    statuses: list[CommandStatus] = field(
        default_factory=lambda: [CommandStatus.ACKNOWLEDGED] * 3
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
        status = self.statuses[len(self.calls) - 1]
        return CommandReceipt(status)


@dataclass(slots=True)
class FailingSecondEndpoint(SequencedEndpoint):
    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        self.calls.append((command, correlation_id, timeout))
        if len(self.calls) == 2:
            raise TimeoutError("controller unavailable")
        return CommandReceipt(CommandStatus.ACKNOWLEDGED)


def build_handler(
    endpoint: SequencedEndpoint,
    *,
    command_count: int = 3,
) -> OperationExecutionHandler:
    translators = TranslatorRegistry()
    translators.register(SequenceTranslator(command_count=command_count))
    translation_handler = OperationTranslationHandler(
        translators,
        lambda operation: TranslationContext(
            vendor="pentair",
            controller_model="IntelliCenter",
        ),
    )
    endpoints = EndpointRegistry()
    endpoints.register(endpoint)
    return OperationExecutionHandler(
        translation_handler=translation_handler,
        gateway=VendorCommandGateway(endpoints),
        delivery_context_provider=lambda operation: OperationDeliveryContext(
            endpoint_id="main-controller",
            correlation_id=f"operation:{operation.equipment_id}",
            timeout=2.5,
        ),
    )


def test_handler_translates_and_delivers_commands_in_order() -> None:
    endpoint = SequencedEndpoint()
    handler = build_handler(endpoint)
    operation = StartPump(equipment_id="filter_pump")

    result = handler(operation)

    assert [call[0].operation for call in endpoint.calls] == [
        "pump.step_1",
        "pump.step_2",
        "pump.step_3",
    ]
    assert all(call[1] == "operation:filter_pump" for call in endpoint.calls)
    assert all(call[2] == 2.5 for call in endpoint.calls)
    assert result.operation is operation
    assert result.translation.warnings == ("example warning",)
    assert len(result.receipts) == 3
    assert result.attempted_count == 3
    assert result.completed
    assert result.successful
    assert result.failed_command is None
    assert result.delivery_error is None
    assert result.unattempted_commands == ()


def test_handler_stops_after_rejected_receipt_and_retains_partial_result() -> None:
    endpoint = SequencedEndpoint(
        statuses=[
            CommandStatus.ACKNOWLEDGED,
            CommandStatus.REJECTED,
            CommandStatus.ACKNOWLEDGED,
        ]
    )
    handler = build_handler(endpoint)

    result = handler(StartPump(equipment_id="filter_pump"))

    assert len(endpoint.calls) == 2
    assert [receipt.status for receipt in result.receipts] == [
        CommandStatus.ACKNOWLEDGED,
        CommandStatus.REJECTED,
    ]
    assert result.rejected_receipt is result.receipts[1]
    assert [command.operation for command in result.unattempted_commands] == [
        "pump.step_3"
    ]
    assert result.attempted_count == 2
    assert not result.completed
    assert not result.successful
    assert result.failed_command is None
    assert result.delivery_error is None


def test_handler_stops_after_delivery_error_and_identifies_failed_command() -> None:
    endpoint = FailingSecondEndpoint()
    handler = build_handler(endpoint)

    result = handler(StartPump(equipment_id="filter_pump"))

    assert len(endpoint.calls) == 2
    assert len(result.receipts) == 1
    assert result.failed_command is not None
    assert result.failed_command.operation == "pump.step_2"
    assert result.delivery_error is not None
    assert isinstance(result.delivery_error.__cause__, TimeoutError)
    assert [command.operation for command in result.unattempted_commands] == [
        "pump.step_3"
    ]
    assert result.attempted_count == 2
    assert not result.completed
    assert not result.successful


def test_zero_command_translation_is_a_successful_no_op() -> None:
    endpoint = SequencedEndpoint(statuses=[])
    handler = build_handler(endpoint, command_count=0)

    result = handler(StartPump(equipment_id="filter_pump"))

    assert endpoint.calls == []
    assert result.receipts == ()
    assert result.attempted_count == 0
    assert result.completed
    assert result.successful


def test_handler_rejects_invalid_delivery_context_provider_result() -> None:
    endpoint = SequencedEndpoint()
    handler = build_handler(endpoint)
    handler.delivery_context_provider = (
        lambda operation: object()  # type: ignore[assignment,return-value]
    )

    with pytest.raises(TypeError, match="OperationDeliveryContext"):
        handler(StartPump(equipment_id="filter_pump"))

    assert endpoint.calls == []


def test_delivery_context_normalizes_and_validates_values() -> None:
    context = OperationDeliveryContext(
        endpoint_id=" main-controller ",
        correlation_id=" operation-123 ",
        timeout=1.0,
    )

    assert context.endpoint_id == "main-controller"
    assert context.correlation_id == "operation-123"

    with pytest.raises(ValueError, match="endpoint_id"):
        OperationDeliveryContext(" ", "operation-123")
    with pytest.raises(ValueError, match="correlation_id"):
        OperationDeliveryContext("main-controller", " ")
    with pytest.raises(ValueError, match="timeout"):
        OperationDeliveryContext("main-controller", "operation-123", timeout=0)


def test_operation_execution_handler_integrates_with_work_dispatcher() -> None:
    endpoint = SequencedEndpoint()
    handler = build_handler(endpoint)
    dispatcher = build_work_dispatcher(
        ExecutionEngine(),
        operation_handler=handler,
    )

    result = dispatcher.dispatch(StartPump(equipment_id="filter_pump"))

    assert result.successful
    assert len(endpoint.calls) == 3
