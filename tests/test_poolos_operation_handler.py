"""Tests for the canonical operation translation boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from poolos.integration import (
    OperationTranslationHandler,
    PoolOperation,
    StartPump,
    TranslationContext,
    TranslationResult,
    TranslatorNotFoundError,
    TranslatorRegistry,
    VendorCommand,
)
from poolos.work_dispatch import build_work_dispatcher
from poolos.execution import ExecutionEngine


@dataclass(frozen=True, slots=True)
class ExampleTranslator:
    vendor: str

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, StartPump)

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        return TranslationResult(
            commands=(
                VendorCommand(
                    vendor=self.vendor,
                    operation="pump.start",
                    target=operation.equipment_id,
                    metadata={"controller": context.controller_model},
                ),
            ),
            metadata={"translated_by": self.vendor},
        )


@dataclass(slots=True)
class RecordingContextProvider:
    contexts: dict[str, TranslationContext]
    calls: list[PoolOperation] = field(default_factory=list)

    def __call__(self, operation: PoolOperation) -> TranslationContext:
        self.calls.append(operation)
        return self.contexts[operation.equipment_id]


def test_handler_resolves_context_and_translates_operation() -> None:
    registry = TranslatorRegistry()
    registry.register(ExampleTranslator("pentair"))
    provider = RecordingContextProvider(
        {
            "filter_pump": TranslationContext(
                vendor="pentair",
                controller_model="IntelliCenter",
            )
        }
    )
    handler = OperationTranslationHandler(registry, provider)
    operation = StartPump(equipment_id="filter_pump")

    result = handler(operation)

    assert provider.calls == [operation]
    assert result.commands[0].vendor == "pentair"
    assert result.commands[0].operation == "pump.start"
    assert result.commands[0].metadata["controller"] == "IntelliCenter"
    assert result.metadata["translated_by"] == "pentair"


def test_context_selects_vendor_without_handler_branching() -> None:
    registry = TranslatorRegistry()
    registry.register(ExampleTranslator("pentair"))
    registry.register(ExampleTranslator("hayward"))
    provider = RecordingContextProvider(
        {
            "pump-a": TranslationContext(vendor="pentair"),
            "pump-b": TranslationContext(vendor="hayward"),
        }
    )
    handler = OperationTranslationHandler(registry, provider)

    first = handler(StartPump(equipment_id="pump-a"))
    second = handler(StartPump(equipment_id="pump-b"))

    assert first.commands[0].vendor == "pentair"
    assert second.commands[0].vendor == "hayward"


def test_handler_integrates_with_pool_operation_dispatch_route() -> None:
    registry = TranslatorRegistry()
    registry.register(ExampleTranslator("pentair"))
    handler = OperationTranslationHandler(
        registry,
        lambda operation: TranslationContext(vendor="pentair"),
    )
    dispatcher = build_work_dispatcher(
        ExecutionEngine(),
        operation_handler=handler,
    )

    result = dispatcher.dispatch(StartPump(equipment_id="filter_pump"))

    assert isinstance(result, TranslationResult)
    assert result.commands[0].target == "filter_pump"


def test_handler_propagates_missing_translator_failure() -> None:
    handler = OperationTranslationHandler(
        TranslatorRegistry(),
        lambda operation: TranslationContext(vendor="unknown"),
    )

    with pytest.raises(TranslatorNotFoundError, match="unknown"):
        handler(StartPump(equipment_id="filter_pump"))


def test_handler_rejects_invalid_context_provider_result() -> None:
    handler = OperationTranslationHandler(
        TranslatorRegistry(),
        lambda operation: object(),  # type: ignore[return-value]
    )

    with pytest.raises(TypeError, match="TranslationContext"):
        handler(StartPump(equipment_id="filter_pump"))
