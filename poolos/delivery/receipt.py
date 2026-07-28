"""Structured results returned by the vendor-command gateway."""

from __future__ import annotations

from dataclasses import dataclass

from ..hal import CommandReceipt, CommandStatus
from ..integration import VendorCommand


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """A command receipt enriched with delivery routing and correlation context."""

    endpoint_id: str
    correlation_id: str
    command: VendorCommand
    receipt: CommandReceipt

    @property
    def status(self) -> CommandStatus:
        return self.receipt.status

    @property
    def accepted(self) -> bool:
        return self.receipt.accepted
