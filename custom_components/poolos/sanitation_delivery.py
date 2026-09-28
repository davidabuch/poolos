"""Exact IntelliCenter delivery adapter for sanitation sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from poolos.hal import CommandReceipt, CommandStatus
from poolos.physical_command_authority import (
    PhysicalCommandDeniedError,
    PhysicalRequestSource,
    SanitationDispatchContext,
)
from poolos.sanitation import SanitationAction, SanitationActionKind

from .manual_intellicenter import (
    ManualIntelliCenterCommandError,
    ManualIntelliCenterControl,
)


@dataclass(slots=True)
class ManualIntelliCenterSanitationDelivery:
    """Deliver one exact sanitation action through the central authority."""

    manual: ManualIntelliCenterControl
    context: SanitationDispatchContext

    @property
    def available(self) -> bool:
        return self.manual.available

    async def deliver(
        self,
        action: SanitationAction,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        issued_at = datetime.now(UTC)
        body_id = "B1101" if self.context.body == "pool" else "B1202"
        try:
            if action.kind is SanitationActionKind.HEAT_OFF:
                await self.manual.async_set_body_heat_source(
                    body_id,
                    "00000",
                    request_source=PhysicalRequestSource.SANITATION,
                    sanitation_context=self.context,
                )
            elif action.kind in {
                SanitationActionKind.BODY_ON,
                SanitationActionKind.BODY_OFF,
            }:
                await self.manual.async_set_body_active(
                    body_id,
                    bool(action.requested_value),
                    request_source=PhysicalRequestSource.SANITATION,
                    sanitation_context=self.context,
                )
            elif action.kind is SanitationActionKind.PUMP_SET:
                await self.manual.async_set_pump_circuit_speed(
                    self.context.pump_circuit_id,
                    int(action.requested_value),
                    request_source=PhysicalRequestSource.SANITATION,
                    sanitation_context=self.context,
                )
            else:
                raise ValueError("unsupported sanitation action")
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
            message="Sanitation command acknowledged",
            issued_at=issued_at,
            acknowledged_at=datetime.now(UTC),
            verification_required=True,
        )


__all__ = ["ManualIntelliCenterSanitationDelivery"]
