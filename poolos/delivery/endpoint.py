"""Port implemented by writable vendor controller endpoints."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from ..hal import CommandReceipt
from ..integration import VendorCommand


class DeliveryEndpointKind(str, Enum):
    """Safety classification declared by writable command endpoints."""

    SIMULATOR = "simulator"
    SHADOW = "shadow"
    PHYSICAL = "physical"


class VendorCommandEndpoint(Protocol):
    """Deliver transport-neutral vendor commands to one configured endpoint."""

    @property
    def endpoint_id(self) -> str: ...

    @property
    def vendor(self) -> str: ...

    @property
    def delivery_kind(self) -> DeliveryEndpointKind: ...

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt: ...
