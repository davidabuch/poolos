"""Port implemented by writable vendor controller endpoints."""

from __future__ import annotations

from typing import Protocol

from ..hal import CommandReceipt
from ..integration import VendorCommand


class VendorCommandEndpoint(Protocol):
    """Deliver transport-neutral vendor commands to one configured endpoint."""

    @property
    def endpoint_id(self) -> str: ...

    @property
    def vendor(self) -> str: ...

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt: ...
