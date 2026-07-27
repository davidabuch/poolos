"""Pentair translation of canonical PoolOS operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from poolos.capabilities import Capability
from poolos.vendors.pentair import PentairPump

from ..command import VendorCommand
from ..context import TranslationContext
from ..exceptions import (
    EquipmentNotFoundError,
    EquipmentTypeError,
    MissingCapabilityError,
    SetpointOutOfRangeError,
    UnsupportedOperationError,
    VendorMismatchError,
)
from ..operations import PoolOperation, SetPumpSpeed, StartPump, StopPump
from ..response import TranslationResult
from .capabilities import PENTAIR_START_STOP, PENTAIR_VARIABLE_SPEED
from .commands import PentairCommandOperation, PentairCommandParameter


@dataclass(frozen=True, slots=True)
class PentairTranslator:
    """Translate supported PoolOS operations into logical Pentair commands."""

    vendor: str = "pentair"

    _supported_types = (SetPumpSpeed, StartPump, StopPump)

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

        pump = self._resolve_pump(operation.equipment_id, context)
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
    def _resolve_pump(equipment_id: str, context: TranslationContext) -> PentairPump:
        try:
            equipment = context.equipment[equipment_id]
        except KeyError as exc:
            raise EquipmentNotFoundError(equipment_id) from exc
        if not isinstance(equipment, PentairPump):
            raise EquipmentTypeError(equipment_id, PentairPump, type(equipment))
        return equipment

    def _translate_start(
        self,
        operation: StartPump,
        pump: PentairPump,
    ) -> TranslationResult:
        self._require_capability(pump, Capability.START_STOP, PENTAIR_START_STOP)
        return self._single_command(
            operation,
            pump,
            PentairCommandOperation.START_PUMP,
        )

    def _translate_stop(
        self,
        operation: StopPump,
        pump: PentairPump,
    ) -> TranslationResult:
        self._require_capability(pump, Capability.START_STOP, PENTAIR_START_STOP)
        return self._single_command(
            operation,
            pump,
            PentairCommandOperation.STOP_PUMP,
        )

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
        pump: PentairPump,
        command_operation: PentairCommandOperation,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> TranslationResult:
        command_metadata: dict[str, Any] = {
            "operation_id": operation.operation_id,
            "equipment_id": operation.equipment_id,
            "object_kind": pump.address.kind.value,
        }
        if operation.correlation_id is not None:
            command_metadata["correlation_id"] = operation.correlation_id
        if pump.address.numeric_id is not None:
            command_metadata["numeric_id"] = pump.address.numeric_id

        command = VendorCommand(
            vendor=self.vendor,
            operation=command_operation,
            target=pump.address.object_id,
            parameters=parameters or {},
            metadata=command_metadata,
        )
        return TranslationResult(
            commands=(command,),
            metadata={
                "translator": type(self).__name__,
                "source_operation": type(operation).__name__,
            },
        )
