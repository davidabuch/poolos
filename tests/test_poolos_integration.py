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
    PhysicalHeatMode,
    PoolOperation,
    SetHeatMode,
    SetHydraulicRoute,
    SetPumpSpeed,
    SetpointOutOfRangeError,
    StartPump,
    StopPump,
    ThermalBody,
    TranslationContext,
    TranslationResult,
    TranslatorNotFoundError,
    TranslatorRegistry,
    VendorCommand,
    TranslationConfigurationError,
    VendorMismatchError,
)
from poolos.integration.pentair import (
    PentairCommandOperation,
    PentairCommandParameter,
    PentairTranslator,
)
from poolos.vendors.pentair import (
    PentairBody,
    PentairBodyKind,
    PentairObjectAddress,
    PentairObjectKind,
    PentairPump,
    PentairPumpControlMode,
    PentairSharedEquipment,
    PentairTemperatureUnit,
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
    with pytest.raises(ValueError, match="unsupported physical heat mode"):
        SetHeatMode(equipment_id=ThermalBody.HOT_TUB, mode="")


def test_initial_operation_classes_can_be_constructed() -> None:
    assert StartPump(equipment_id="pump").equipment_id == "pump"
    assert StopPump(equipment_id="pump").equipment_id == "pump"
    heat = SetHeatMode(
        equipment_id=ThermalBody.HOT_TUB,
        mode=PhysicalHeatMode.GAS,
    )
    assert heat.equipment_id == "hot_tub"
    assert heat.mode is PhysicalHeatMode.GAS
    route = SetHydraulicRoute(
        equipment_id="shared-1",
        suction_body_id="pool",
        return_body_id="spa",
    )
    assert route.suction_body_id == "pool"
    assert route.return_body_id == "spa"


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


@pytest.mark.parametrize(
    ("body", "mode", "native_body", "heater_id"),
    (
        (ThermalBody.POOL, PhysicalHeatMode.OFF, "B1101", "00000"),
        (ThermalBody.POOL, PhysicalHeatMode.GAS, "B1101", "H0001"),
        (ThermalBody.POOL, PhysicalHeatMode.SOLAR, "B1101", "H0002"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.OFF, "B1202", "00000"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.GAS, "B1202", "H0001"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.SOLAR, "B1202", "H0002"),
    ),
)
def test_pentair_translates_only_commissioned_heat_source_matrix(
    body: ThermalBody,
    mode: PhysicalHeatMode,
    native_body: str,
    heater_id: str,
) -> None:
    translator = PentairTranslator()
    operation = SetHeatMode(equipment_id=body, mode=mode)

    result = translator.translate(
        operation,
        TranslationContext(vendor="pentair", capabilities={"pentair.heat_mode"}),
    )

    assert translator.supports(operation)
    assert result.commands[0].operation is PentairCommandOperation.SET_BODY_HEATER
    assert result.commands[0].target == native_body
    assert result.commands[0].parameters[PentairCommandParameter.HEATER_ID] == heater_id
    assert "HTMODE" not in result.commands[0].parameters
    assert "HXSLR" not in repr(result.commands[0])


def test_pentair_heat_source_translation_fails_closed() -> None:
    translator = PentairTranslator()

    with pytest.raises(ValueError, match="unsupported thermal body"):
        SetHeatMode(equipment_id="spa", mode=PhysicalHeatMode.GAS)
    with pytest.raises(ValueError, match="unsupported physical heat mode"):
        SetHeatMode(equipment_id=ThermalBody.POOL, mode="solar_preferred")
    with pytest.raises(MissingCapabilityError, match="pentair.heat_mode"):
        translator.translate(
            SetHeatMode(
                equipment_id=ThermalBody.POOL,
                mode=PhysicalHeatMode.SOLAR,
            ),
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


def _pentair_body(
    *,
    object_id: str,
    body_kind: PentairBodyKind,
    circuit_id: str,
    shared_equipment_group: str | None = "shared-1",
) -> PentairBody:
    return PentairBody(
        address=PentairObjectAddress(
            object_id=object_id,
            kind=PentairObjectKind.BODY,
            panel_name=body_kind.value.title(),
        ),
        name=body_kind.value.title(),
        body_kind=body_kind,
        circuit_id=circuit_id,
        temperature_unit=PentairTemperatureUnit.FAHRENHEIT,
        minimum_temperature=40,
        maximum_temperature=104,
        shared_equipment_group=shared_equipment_group,
    )


def _shared_route_context() -> TranslationContext:
    pool = _pentair_body(
        object_id="body-pool",
        body_kind=PentairBodyKind.POOL,
        circuit_id="circuit-pool",
    )
    spa = _pentair_body(
        object_id="body-spa",
        body_kind=PentairBodyKind.SPA,
        circuit_id="circuit-spa",
    )
    group = PentairSharedEquipment(
        group_id="shared-1",
        body_ids=frozenset({"body-pool", "body-spa"}),
        pump_ids=frozenset({"pump-1"}),
        intake_valve_id="valve-intake",
        return_valve_id="valve-return",
    )
    return TranslationContext(
        vendor="pentair",
        equipment={"pool": pool, "spa": spa, "shared": group},
    )


@pytest.mark.parametrize(
    ("suction", "return_body", "expected_suction", "expected_return"),
    [
        ("pool", "pool", "body-pool", "body-pool"),
        ("spa", "spa", "body-spa", "body-spa"),
        ("pool", "spa", "body-pool", "body-spa"),
        ("spa", "pool", "body-spa", "body-pool"),
    ],
)
def test_pentair_translates_all_four_shared_hydraulic_routes(
    suction: str,
    return_body: str,
    expected_suction: str,
    expected_return: str,
) -> None:
    result = PentairTranslator().translate(
        SetHydraulicRoute(
            equipment_id="shared-1",
            suction_body_id=suction,
            return_body_id=return_body,
            correlation_id="route-session",
        ),
        _shared_route_context(),
    )

    command = result.commands[0]
    assert command.operation == PentairCommandOperation.SET_HYDRAULIC_ROUTE
    assert command.target == "shared-1"
    assert command.parameters[PentairCommandParameter.SUCTION_BODY_ID] == expected_suction
    assert command.parameters[PentairCommandParameter.RETURN_BODY_ID] == expected_return
    assert command.parameters[PentairCommandParameter.INTAKE_VALVE_ID] == "valve-intake"
    assert command.parameters[PentairCommandParameter.RETURN_VALVE_ID] == "valve-return"
    assert command.metadata["correlation_id"] == "route-session"
    assert result.metadata["hydraulic_route"] == {
        "suction": expected_suction,
        "return": expected_return,
    }


def test_cross_body_route_requires_common_shared_equipment() -> None:
    pool = _pentair_body(
        object_id="body-pool",
        body_kind=PentairBodyKind.POOL,
        circuit_id="circuit-pool",
        shared_equipment_group=None,
    )
    spa = _pentair_body(
        object_id="body-spa",
        body_kind=PentairBodyKind.SPA,
        circuit_id="circuit-spa",
        shared_equipment_group=None,
    )
    context = TranslationContext(vendor="pentair", equipment={"pool": pool, "spa": spa})

    with pytest.raises(TranslationConfigurationError, match="shared equipment group"):
        PentairTranslator().translate(
            SetHydraulicRoute(
                equipment_id="hydraulics",
                suction_body_id="pool",
                return_body_id="spa",
            ),
            context,
        )


def test_hydraulic_route_validates_body_inventory_and_group_membership() -> None:
    translator = PentairTranslator()
    context = _shared_route_context()

    with pytest.raises(EquipmentNotFoundError):
        translator.translate(
            SetHydraulicRoute(
                equipment_id="shared-1",
                suction_body_id="missing",
                return_body_id="spa",
            ),
            context,
        )

    pool = context.equipment["pool"]
    spa = context.equipment["spa"]
    invalid_group = PentairSharedEquipment(
        group_id="shared-1",
        body_ids=frozenset({"body-pool", "body-other"}),
        pump_ids=frozenset({"pump-1"}),
    )
    bad_context = TranslationContext(
        vendor="pentair",
        equipment={"pool": pool, "spa": spa, "shared": invalid_group},
    )
    with pytest.raises(TranslationConfigurationError, match="not members"):
        translator.translate(
            SetHydraulicRoute(
                equipment_id="shared-1",
                suction_body_id="pool",
                return_body_id="spa",
            ),
            bad_context,
        )
