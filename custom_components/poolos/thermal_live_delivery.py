"""Home Assistant adapter for the disabled-by-default thermal live port.

The adapter wraps the already commissioned manual IntelliCenter gateway.  It is
not instantiated or scheduled at startup by this module and exposes only the
two canonical operations admitted by the Phase 2 core boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.physical_command_authority import PhysicalRequestSource
from poolos.thermal_live_execution import COMMISSIONED_THERMAL_PUMP_ID

from .manual_intellicenter import (
    ManualIntelliCenterCommandError,
    ManualIntelliCenterControl,
)


_BODY_ID = {ThermalBody.POOL: "B1101", ThermalBody.HOT_TUB: "B1202"}
_HEATER_ID = {
    PhysicalHeatMode.OFF: "00000",
    PhysicalHeatMode.GAS: "H0001",
    PhysicalHeatMode.SOLAR: "H0002",
}


@dataclass(slots=True)
class ManualIntelliCenterThermalLiveDelivery:
    """Deliver only commissioned thermal operations through manual control."""

    manual: ManualIntelliCenterControl
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()

    @property
    def available(self) -> bool:
        return self.manual.available

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        if not correlation_id.strip():
            raise ValueError("correlation_id must not be empty")
        issued_at = datetime.now(timezone.utc)
        try:
            if isinstance(operation, SetPumpSpeed):
                self._validate_pump(operation)
                manual_receipt = await self.manual.async_set_pump_circuit_speed(
                    COMMISSIONED_THERMAL_PUMP_ID,
                    operation.rpm,
                    request_source=PhysicalRequestSource.AUTONOMOUS,
                )
            elif isinstance(operation, SetHeatMode):
                body_id, heater_id = self._validate_heat_mode(operation)
                manual_receipt = await self.manual.async_set_body_heat_source(
                    body_id,
                    heater_id,
                    request_source=PhysicalRequestSource.AUTONOMOUS,
                )
            else:
                return CommandReceipt(
                    status=CommandStatus.REJECTED,
                    command_id=correlation_id,
                    message=f"unsupported thermal operation:{type(operation).__name__}",
                    issued_at=issued_at,
                    verification_required=True,
                )
        except (ManualIntelliCenterCommandError, ValueError) as exc:
            return CommandReceipt(
                status=(
                    CommandStatus.FAILED
                    if isinstance(exc, ManualIntelliCenterCommandError)
                    else CommandStatus.REJECTED
                ),
                command_id=correlation_id,
                message=str(exc),
                issued_at=issued_at,
                verification_required=True,
                details={"error_type": type(exc).__name__},
            )
        return CommandReceipt(
            status=CommandStatus.ACKNOWLEDGED,
            command_id=correlation_id,
            message="Manual IntelliCenter thermal command acknowledged",
            issued_at=issued_at,
            acknowledged_at=datetime.now(timezone.utc),
            verification_required=True,
            details={
                "manual_operation": manual_receipt.operation,
                "manual_target": manual_receipt.body_objnam,
                "manual_value": manual_receipt.value,
            },
        )

    def _validate_pump(self, operation: SetPumpSpeed) -> None:
        if operation.equipment_id != COMMISSIONED_THERMAL_PUMP_ID:
            raise ValueError("unsupported thermal pump circuit")
        if operation.rpm not in {
            self.baselines.solar_heating_rpm,
            self.baselines.gas_heating_rpm,
        }:
            raise ValueError("unsupported thermal pump RPM baseline")

    @staticmethod
    def _validate_heat_mode(operation: SetHeatMode) -> tuple[str, str]:
        try:
            body = ThermalBody(operation.equipment_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported thermal body") from exc
        if not isinstance(operation.mode, PhysicalHeatMode):
            raise ValueError("unsupported physical heat mode")
        if operation.mode not in {
            PhysicalHeatMode.OFF,
            PhysicalHeatMode.GAS,
            PhysicalHeatMode.SOLAR,
        }:
            raise ValueError("unsupported physical heat mode")
        return _BODY_ID[body], _HEATER_ID[operation.mode]


__all__ = ["ManualIntelliCenterThermalLiveDelivery"]
