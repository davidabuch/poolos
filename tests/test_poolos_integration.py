"""Tests for the transport-independent vendor integration framework."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import ClassVar

import pytest

from poolos.integration import (
    DuplicateTranslatorError,
    PoolOperation,
    SetHeatMode,
    SetPumpSpeed,
    StartPump,
    StopPump,
    TranslationContext,
    TranslationResult,
    TranslatorNotFoundError,
    TranslatorRegistry,
    UnsupportedOperationError,
    VendorCommand,
    VendorMismatchError,
)
from poolos.integration.pentair import PentairTranslator


@dataclass(frozen=True, slots=True)
class RecordingTranslator:
    vendor: str = "example"
    calls: ClassVar[list[tuple[PoolOperation, TranslationContext]]] = []

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, StartPump)

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        self.calls.append((operation, context))
        return TranslationResult(
            commands=(
                VendorCommand(
                    vendor=self.vendor,
                    operation="start",
                    target=operation.equipment_id,
                    metadata={"operation_id": operation.operation_id},
                ),
            ),
            metadata={"firmware": context.firmware_version},
        )


def test_operations_are_typed_validated_and_immutable() -> None:
    operation = SetPumpSpeed(equipment_id="filter_pump", rpm=2400, metadata={"source": "test"})

    assert operation.rpm == 2400
    assert operation.metadata["source"] == "test"
    with pytest.raises(FrozenInstanceError):
        operation.rpm = 1800  # type: ignore[misc]
    with pytest.raises(TypeError):
        operation.metadata["source"] = "changed"  # type: ignore[index]
    with pytest.raises(ValueError, match="rpm must be positive"):
        SetPumpSpeed(equipment_id="filter_pump", rpm=0)
    with pytest.raises(ValueError, match="equipment_id must not be empty"):
        StartPump(equipment_id=" ")
    with pytest.raises(ValueError, match="mode must not be empty"):
        SetHeatMode(equipment_id="spa", mode="")


def test_initial_operation_classes_can_be_constructed() -> None:
    assert StartPump(equipment_id="pump").equipment_id == "pump"
    assert StopPump(equipment_id="pump").equipment_id == "pump"
    assert SetHeatMode(equipment_id="spa", mode="heat").mode == "heat"


def test_vendor_command_is_validated_and_deeply_read_only_at_mapping_boundary() -> None:
    parameters = {"rpm": 2400}
    command = VendorCommand(
        vendor="pentair",
        operation="set_pump_speed",
        target="filter_pump",
        parameters=parameters,
        metadata={"priority": "normal"},
    )
    parameters["rpm"] = 3000

    assert command.parameters["rpm"] == 2400
    with pytest.raises(TypeError):
        command.parameters["rpm"] = 1800  # type: ignore[index]
    with pytest.raises(ValueError, match="operation must not be empty"):
        VendorCommand(vendor="pentair", operation="", target="pump")


def test_translation_context_copies_and_freezes_collections() -> None:
    equipment = {"pump": {"model": "IntelliFlo"}}
    context = TranslationContext(
        vendor="pentair",
        controller_model="IntelliCenter",
        firmware_version="2.0",
        equipment=equipment,
        capabilities={"variable_speed"},
        feature_flags={"strict_validation"},
    )
    equipment["other"] = {}

    assert "other" not in context.equipment
    assert context.capabilities == frozenset({"variable_speed"})
    with pytest.raises(TypeError):
        context.equipment["other"] = {}  # type: ignore[index]


def test_translation_result_normalizes_sequences_and_freezes_metadata() -> None:
    command = VendorCommand(vendor="example", operation="start", target="pump")
    result = TranslationResult(
        commands=[command],  # type: ignore[arg-type]
        warnings=["fallback used"],  # type: ignore[arg-type]
        metadata={"strategy": "direct"},
    )

    assert result.commands == (command,)
    assert result.warnings == ("fallback used",)
    with pytest.raises(TypeError):
        result.metadata["strategy"] = "changed"  # type: ignore[index]


def test_registry_register_lookup_translate_replace_and_unregister() -> None:
    RecordingTranslator.calls.clear()
    registry = TranslatorRegistry()
    translator = RecordingTranslator()
    registry.register(translator)
    operation = StartPump(equipment_id="filter_pump")
    context = TranslationContext(vendor="EXAMPLE", firmware_version="1.2.3")

    assert registry.get(" Example ") is translator
    assert registry.all() == (translator,)
    result = registry.translate("example", operation, context)
    assert result.commands[0].target == "filter_pump"
    assert RecordingTranslator.calls == [(operation, context)]

    replacement = RecordingTranslator()
    registry.replace(replacement)
    assert registry.get("example") is replacement
    assert registry.unregister("example") is replacement
    with pytest.raises(TranslatorNotFoundError):
        registry.get("example")


def test_registry_rejects_duplicates_unknown_vendors_and_context_mismatch() -> None:
    registry = TranslatorRegistry()
    registry.register(RecordingTranslator())

    with pytest.raises(DuplicateTranslatorError):
        registry.register(RecordingTranslator())
    with pytest.raises(TranslatorNotFoundError):
        registry.unregister("missing")
    with pytest.raises(VendorMismatchError):
        registry.translate(
            "example",
            StartPump(equipment_id="pump"),
            TranslationContext(vendor="other"),
        )


def test_pentair_scaffold_recognizes_initial_operations_and_fails_closed() -> None:
    translator = PentairTranslator()
    context = TranslationContext(vendor="pentair")
    operations = (
        SetPumpSpeed(equipment_id="pump", rpm=2400),
        StartPump(equipment_id="pump"),
        StopPump(equipment_id="pump"),
        SetHeatMode(equipment_id="spa", mode="heat"),
    )

    assert all(translator.supports(operation) for operation in operations)
    for operation in operations:
        with pytest.raises(UnsupportedOperationError):
            translator.translate(operation, context)


def test_pentair_scaffold_rejects_wrong_vendor_context() -> None:
    translator = PentairTranslator()

    with pytest.raises(VendorMismatchError):
        translator.translate(
            StartPump(equipment_id="pump"),
            TranslationContext(vendor="hayward"),
        )
