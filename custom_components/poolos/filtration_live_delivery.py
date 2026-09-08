"""Exact Pool-only delivery adapter for autonomous filtration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from poolos.filtration_automatic_execution import FiltrationAutomaticDeliveryPort
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import PoolOperation, SetBodyActive, SetPumpSpeed, ThermalBody
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.physical_command_authority import (
    AutomaticFiltrationDispatchContext,
    PhysicalCommandDeniedError,
    PhysicalRequestSource,
)

from .manual_intellicenter import (
    ManualIntelliCenterCommandError,
    ManualIntelliCenterControl,
)


@dataclass(slots=True)
class ManualIntelliCenterFiltrationDelivery(FiltrationAutomaticDeliveryPort):
    manual: ManualIntelliCenterControl
    context: AutomaticFiltrationDispatchContext
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
        issued_at = datetime.now(UTC)
        try:
            if isinstance(operation, SetBodyActive):
                if operation.equipment_id != ThermalBody.POOL.value:
                    raise ValueError("automatic filtration is Pool-only")
                await self.manual.async_set_body_active(
                    "B1101",
                    operation.active,
                    request_source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
                    automatic_filtration_context=self.context,
                )
            elif isinstance(operation, SetPumpSpeed):
                if (
                    operation.equipment_id != self.context.pump_circuit_id
                    or operation.rpm != self.baselines.filtration_rpm
                ):
                    raise ValueError("unsupported automatic filtration pump target")
                await self.manual.async_set_pump_circuit_speed(
                    operation.equipment_id,
                    operation.rpm,
                    request_source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
                    automatic_filtration_context=self.context,
                )
            else:
                raise ValueError("unsupported automatic filtration operation")
        except (ManualIntelliCenterCommandError, ValueError) as exc:
            authority_reason = None
            if isinstance(exc.__cause__, PhysicalCommandDeniedError):
                authority_reason = exc.__cause__.decision.reason.value
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
                details={
                    "error_type": type(exc).__name__,
                    "authority_reason": authority_reason,
                },
            )
        return CommandReceipt(
            status=CommandStatus.ACKNOWLEDGED,
            command_id=correlation_id,
            message="Automatic Pool filtration command acknowledged",
            issued_at=issued_at,
            acknowledged_at=datetime.now(UTC),
            verification_required=True,
        )


__all__ = ["ManualIntelliCenterFiltrationDelivery"]
