"""Pentair translation of canonical PoolOS operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from poolos.capabilities import Capability
from poolos.vendors.pentair import PentairBody, PentairPump, PentairSharedEquipment

from ..command import VendorCommand
from ..context import TranslationContext
from ..exceptions import (
    EquipmentNotFoundError,
    EquipmentTypeError,
    MissingCapabilityError,
    SetpointOutOfRangeError,
    TranslationConfigurationError,
    UnsupportedOperationError,
    VendorMismatchError,
)
from ..operations import PoolOperation, SetHydraulicRoute, SetPumpSpeed, StartPump, StopPump
from ..response import TranslationResult
from .capabilities import (
    PENTAIR_HYDRAULIC_ROUTING,
    PENTAIR_SHARED_EQUIPMENT_ROUTING,
    PENTAIR_START_STOP,
    PENTAIR_VARIABLE_SPEED,
)
from .commands import PentairCommandOperation, PentairCommandParameter


@dataclass(frozen=True, slots=True)
class PentairTranslator:
    """Translate supported PoolOS operations into logical Pentair commands."""

    vendor: str = "pentair"

    _supported_types = (SetHydraulicRoute, SetPumpSpeed, StartPump, StopPump)

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, self._supported_types)

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        self._validate_vendor(context)
        if not self.supports(operation):
            raise UnsupportedOperationError(self.vendor, type(operation))

        if isinstance(operation, SetHydraulicRoute):
            return self._translate_hydraulic_route(operation, context)

        pump = self._resolve_equipment(operation.equipment_id, context, PentairPump)
        if isinstance(operation, SetPumpSpeed):
            return self._translate_set_speed(operation, pump)
        if isinstance(operation, StartPump):
            return self._translate_start(operation, pump)
        if isinstance(operation, StopPump):
            return self._translate_stop(operation, pump)
        raise UnsupportedOperationError(self.vendor, type(operation))

    def _validate_vendor(self, context: TranslationContext) -> None:
        actual = context.vendor.strip().lower()
        if actual != self.vendor:
            raise VendorMismatchError(self.vendor, actual)

    @staticmethod
    def _resolve_equipment(
        equipment_id: str,
        context: TranslationContext,
        expected_type: type[Any],
    ) -> Any:
        try:
            equipment = context.equipment[equipment_id]
        except KeyError as exc:
            raise EquipmentNotFoundError(equipment_id) from exc
        if not isinstance(equipment, expected_type):
            raise EquipmentTypeError(equipment_id, expected_type, type(equipment))
        return equipment

    def _translate_hydraulic_route(
        self,
        operation: SetHydraulicRoute,
        context: TranslationContext,
    ) -> TranslationResult:
        suction = self._resolve_equipment(operation.suction_body_id, context, PentairBody)
        return_body = self._resolve_equipment(operation.return_body_id, context, PentairBody)
        group = self._resolve_route_group(suction, return_body, context)

        parameters: dict[str, Any] = {
            PentairCommandParameter.SUCTION_BODY_ID: suction.address.object_id,
            PentairCommandParameter.SUCTION_BODY_KIND: suction.body_kind.value,
            PentairCommandParameter.SUCTION_CIRCUIT_ID: suction.circuit_id,
            PentairCommandParameter.RETURN_BODY_ID: return_body.address.object_id,
            PentairCommandParameter.RETURN_BODY_KIND: return_body.body_kind.value,
            PentairCommandParameter.RETURN_CIRCUIT_ID: return_body.circuit_id,
        }
        capability = PENTAIR_HYDRAULIC_ROUTING
        target = operation.equipment_id
        target_kind = "hydraulic_system"

        if group is not None:
            parameters[PentairCommandParameter.SHARED_EQUIPMENT_GROUP] = group.group_id
            if group.intake_valve_id is not None:
                parameters[PentairCommandParameter.INTAKE_VALVE_ID] = group.intake_valve_id
            if group.return_valve_id is not None:
                parameters[PentairCommandParameter.RETURN_VALVE_ID] = group.return_valve_id
            capability = PENTAIR_SHARED_EQUIPMENT_ROUTING
            target = group.group_id
            target_kind = "shared_equipment"

        command = VendorCommand(
            vendor=self.vendor,
            operation=PentairCommandOperation.SET_HYDRAULIC_ROUTE,
            target=target,
            parameters=parameters,
            metadata=self._operation_metadata(operation, object_kind=target_kind),
        )
        return TranslationResult(
            commands=(command,),
            metadata={
                "source_operation": type(operation).__name__,
                "translation_capability": capability,
                "hydraulic_route": {
                    "suction": suction.address.object_id,
                    "return": return_body.address.object_id,
                },
            },
        )

    @staticmethod
    def _resolve_route_group(
        suction: PentairBody,
        return_body: PentairBody,
        context: TranslationContext,
    ) -> PentairSharedEquipment | None:
        suction_group = suction.shared_equipment_group
        return_group = return_body.shared_equipment_group

        if suction.address.object_id != return_body.address.object_id:
            if suction_group is None or return_group is None:
                raise TranslationConfigurationError(
                    "cross-body hydraulic routes require a shared equipment group"
                )
            if suction_group != return_group:
                raise TranslationConfigurationError(
                    "suction and return bodies must belong to the same shared equipment group"
                )

        group_id = suction_group or return_group
        if group_id is None:
            return None

        groups = [
            item
            for item in context.equipment.values()
            if isinstance(item, PentairSharedEquipment) and item.group_id == group_id
        ]
        if not groups:
            raise TranslationConfigurationError(
                f"hydraulic route references missing shared equipment group {group_id}"
            )
        if len(groups) > 1:
            raise TranslationConfigurationError(
                f"shared equipment group {group_id} is configured more than once"
            )

        group = groups[0]
        requested = {suction.address.object_id, return_body.address.object_id}
        if not requested <= group.body_ids:
            raise TranslationConfigurationError(
                f"hydraulic route bodies are not members of shared equipment group {group_id}"
            )
        return group

    def _translate_start(
        self,
        operation: StartPump,
        pump: PentairPump,
    ) -> TranslationResult:
        self._require_capability(pump, Capability.START_STOP, PENTAIR_START_STOP)
        return self._single_command(operation, pump, PentairCommandOperation.START_PUMP)

    def _translate_stop(
        self,
        operation: StopPump,
        pump: PentairPump,
    ) -> TranslationResult:
        self._require_capability(pump, Capability.START_STOP, PENTAIR_START_STOP)
        return self._single_command(operation, pump, PentairCommandOperation.STOP_PUMP)

    def _translate_set_speed(
        self,
        operation: SetPumpSpeed,
        pump: PentairPump,
    ) -> TranslationResult:
        self._require_capability(pump, Capability.RPM_CONTROL, PENTAIR_VARIABLE_SPEED)
        if pump.minimum_rpm is None or pump.maximum_rpm is None:
            raise MissingCapabilityError(operation.equipment_id, "pentair.rpm_bounds")
        if not pump.minimum_rpm <= operation.rpm <= pump.maximum_rpm:
            raise SetpointOutOfRangeError(
                operation.equipment_id,
                PentairCommandParameter.RPM,
                operation.rpm,
                pump.minimum_rpm,
                pump.maximum_rpm,
            )
        return self._single_command(
            operation,
            pump,
            PentairCommandOperation.SET_PUMP_SPEED,
            parameters={PentairCommandParameter.RPM: operation.rpm},
        )

    @staticmethod
    def _require_capability(
        pump: PentairPump,
        capability: Capability,
        external_name: str,
    ) -> None:
        if capability not in pump.capabilities:
            raise MissingCapabilityError(pump.address.object_id, external_name)

    def _single_command(
        self,
        operation: PoolOperation,
        equipment: PentairPump,
        command_operation: PentairCommandOperation,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> TranslationResult:
        command_metadata = self._operation_metadata(
            operation,
            object_kind=equipment.address.kind.value,
        )
        if equipment.address.numeric_id is not None:
            command_metadata["numeric_id"] = equipment.address.numeric_id
        command = VendorCommand(
            vendor=self.vendor,
            operation=command_operation,
            target=equipment.address.object_id,
            parameters=parameters or {},
            metadata=command_metadata,
        )
        return TranslationResult(
            commands=(command,),
            metadata={"source_operation": type(operation).__name__},
        )

    @staticmethod
    def _operation_metadata(
        operation: PoolOperation,
        *,
        object_kind: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "operation_id": operation.operation_id,
            "equipment_id": operation.equipment_id,
            "object_kind": object_kind,
        }
        if operation.correlation_id is not None:
            metadata["correlation_id"] = operation.correlation_id
        return metadata
