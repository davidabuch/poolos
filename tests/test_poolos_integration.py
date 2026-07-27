"""Tests for the transport-independent vendor integration framework."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import ClassVar

import pytest

from poolos.integration import (
    DuplicateTranslatorError,
    EquipmentNotFoundError,
    EquipmentTypeError,
    MissingCapabilityError,
    PoolOperation,
    SetHeatMode,
    SetPumpSpeed,
    SetpointOutOfRangeError,
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
from poolos.integration.pentair import (
    PentairCommandOperation,
    PentairCommandParameter,
    PentairTranslator,
)
from poolos.vendors.pentair import (
    PentairObjectAddress,
    PentairObjectKind,
    PentairPump,
    PentairPumpControlMode,
)


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


def _pentair_pump(
    *,
    control_mode: PentairPumpControlMode = PentairPumpControlMode.VARIABLE_SPEED,
    minimum_rpm: int | None = 450,
    maximum_rpm: int | None = 3450,
) -> PentairPump:
    return PentairPump(
        address=PentairObjectAddress(
            object_id="pump-1",
            kind=PentairObjectKind.PUMP,
            numeric_id=7,
            panel_name="Filter Pump",
        ),
        name="Filter Pump",
        control_mode=control_mode,
        minimum_rpm=minimum_rpm,
        maximum_rpm=maximum_rpm,
    )


def test_pentair_pump_start_stop_and_speed_translate_to_logical_commands() -> None:
    translator = PentairTranslator()
    context = TranslationContext(vendor="pentair", equipment={"filter_pump": _pentair_pump()})

    start = translator.translate(
        StartPump(equipment_id="filter_pump", correlation_id="session-1"),
        context,
    )
    stop = translator.translate(StopPump(equipment_id="filter_pump"), context)
    speed = translator.translate(SetPumpSpeed(equipment_id="filter_pump", rpm=2400), context)

    assert start.commands[0].operation == PentairCommandOperation.START_PUMP
    assert start.commands[0].target == "pump-1"
    assert start.commands[0].metadata["numeric_id"] == 7
    assert start.commands[0].metadata["correlation_id"] == "session-1"
    assert stop.commands[0].operation == PentairCommandOperation.STOP_PUMP
    assert speed.commands[0].operation == PentairCommandOperation.SET_PUMP_SPEED
    assert speed.commands[0].parameters[PentairCommandParameter.RPM] == 2400
    assert speed.metadata["source_operation"] == "SetPumpSpeed"


def test_pentair_supports_only_implemented_pump_operations() -> None:
    translator = PentairTranslator()

    assert translator.supports(StartPump(equipment_id="pump"))
    assert translator.supports(StopPump(equipment_id="pump"))
    assert translator.supports(SetPumpSpeed(equipment_id="pump", rpm=2400))
    assert not translator.supports(SetHeatMode(equipment_id="spa", mode="heat"))

    with pytest.raises(UnsupportedOperationError):
        translator.translate(
            SetHeatMode(equipment_id="spa", mode="heat"),
            TranslationContext(vendor="pentair"),
        )


def test_pentair_translation_validates_equipment_and_capabilities() -> None:
    translator = PentairTranslator()

    with pytest.raises(EquipmentNotFoundError):
        translator.translate(
            StartPump(equipment_id="missing"),
            TranslationContext(vendor="pentair"),
        )
    with pytest.raises(EquipmentTypeError):
        translator.translate(
            StartPump(equipment_id="pump"),
            TranslationContext(vendor="pentair", equipment={"pump": object()}),
        )

    single_speed = _pentair_pump(
        control_mode=PentairPumpControlMode.SINGLE_SPEED,
        minimum_rpm=None,
        maximum_rpm=None,
    )
    with pytest.raises(MissingCapabilityError, match="pentair.variable_speed"):
        translator.translate(
            SetPumpSpeed(equipment_id="pump", rpm=2400),
            TranslationContext(vendor="pentair", equipment={"pump": single_speed}),
        )


def test_pentair_speed_translation_requires_bounds_and_enforces_them() -> None:
    translator = PentairTranslator()
    operation = SetPumpSpeed(equipment_id="pump", rpm=3500)

    with pytest.raises(MissingCapabilityError, match="pentair.rpm_bounds"):
        translator.translate(
            operation,
            TranslationContext(
                vendor="pentair",
                equipment={"pump": _pentair_pump(minimum_rpm=None, maximum_rpm=None)},
            ),
        )
    with pytest.raises(SetpointOutOfRangeError) as exc_info:
        translator.translate(
            operation,
            TranslationContext(vendor="pentair", equipment={"pump": _pentair_pump()}),
        )

    assert exc_info.value.minimum == 450
    assert exc_info.value.maximum == 3450


def test_pentair_scaffold_rejects_wrong_vendor_context() -> None:
    translator = PentairTranslator()

    with pytest.raises(VendorMismatchError):
        translator.translate(
            StartPump(equipment_id="pump"),
            TranslationContext(vendor="hayward"),
        )
