"""Pentair command-client port and vendor-command endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from ..hal import CommandReceipt, CommandStatus
from ..integration import VendorCommand
from ..integration.pentair import PentairCommandOperation


class PentairCommandClientError(Exception):
    """Base class for known failures reported by a Pentair command client."""


class PentairCommandTimeoutError(PentairCommandClientError):
    """Raised when a Pentair command client exceeds its delivery timeout."""


@dataclass(frozen=True, slots=True)
class PentairCommandRequest:
    """Controller-facing request produced from one logical Pentair command."""

    operation: str
    target: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        for value, label in (
            (self.operation, "operation"),
            (self.target, "target"),
            (self.correlation_id, "correlation_id"),
        ):
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{label} must not be empty")
            object.__setattr__(self, label, normalized)
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True)
class PentairCommandResponse:
    """Acknowledgement returned by a concrete Pentair command client."""

    accepted: bool
    acknowledged: bool = False
    message: str = ""
    command_id: str | None = None
    received_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.acknowledged and not self.accepted:
            raise ValueError("an unaccepted Pentair command cannot be acknowledged")
        if self.command_id is not None:
            command_id = self.command_id.strip()
            if not command_id:
                raise ValueError("command_id must not be empty when provided")
            object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class PentairCommandClient(Protocol):
    """Port implemented by a concrete Pentair controller adapter.

    The anticipated first production implementation is a Home Assistant adapter.
    A future direct IntelliCenter or RS-485 adapter may implement the same port
    without changing PoolOS translation, routing, or execution code.
    """

    def execute(
        self,
        request: PentairCommandRequest,
        *,
        timeout: float | None = None,
    ) -> PentairCommandResponse: ...


@dataclass(slots=True)
class PentairVendorCommandEndpoint:
    """Adapt logical Pentair vendor commands to a Pentair command client."""

    endpoint_id: str
    client: PentairCommandClient
    vendor: str = "pentair"

    def __init__(
        self,
        endpoint_id: str,
        client: PentairCommandClient,
    ) -> None:
        self.endpoint_id = self._require_text(endpoint_id, "endpoint_id")
        self.client = client
        self.vendor = "pentair"

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        correlation_key = self._require_text(correlation_id, "correlation_id")
        self._validate_vendor(command.vendor)
        operation = self._validate_operation(command.operation)
        request = PentairCommandRequest(
            operation=operation,
            target=command.target,
            parameters=command.parameters,
            metadata=command.metadata,
            correlation_id=correlation_key,
        )

        try:
            response = self.client.execute(request, timeout=timeout)
        except PentairCommandTimeoutError as exc:
            return self._failure_receipt(
                CommandStatus.TIMED_OUT,
                correlation_key,
                request,
                exc,
            )
        except PentairCommandClientError as exc:
            return self._failure_receipt(
                CommandStatus.FAILED,
                correlation_key,
                request,
                exc,
            )

        return self._receipt_from_response(
            response,
            correlation_id=correlation_key,
            request=request,
        )

    def _validate_vendor(self, command_vendor: str) -> None:
        actual = command_vendor.strip().lower()
        if actual != self.vendor:
            raise ValueError(
                f"endpoint vendor {self.vendor!r} does not match command vendor "
                f"{actual!r}"
            )

    @staticmethod
    def _validate_operation(operation: str) -> str:
        normalized = operation.strip()
        supported = {item.value for item in PentairCommandOperation}
        if normalized not in supported:
            raise ValueError(f"unsupported Pentair command operation: {normalized}")
        return normalized

    def _receipt_from_response(
        self,
        response: PentairCommandResponse,
        *,
        correlation_id: str,
        request: PentairCommandRequest,
    ) -> CommandReceipt:
        if not response.accepted:
            status = CommandStatus.REJECTED
            default_message = "Pentair command client rejected command"
        elif response.acknowledged:
            status = CommandStatus.ACKNOWLEDGED
            default_message = "Pentair command client acknowledged command"
        else:
            status = CommandStatus.SENT
            default_message = "Pentair command client accepted command"

        return CommandReceipt(
            status=status,
            command_id=correlation_id,
            message=response.message or default_message,
            acknowledged_at=(
                response.received_at if response.acknowledged else None
            ),
            verification_required=True,
            details={
                "endpoint_id": self.endpoint_id,
                "operation": request.operation,
                "target": request.target,
                "client_command_id": response.command_id,
                "client_details": response.details,
            },
        )

    def _failure_receipt(
        self,
        status: CommandStatus,
        correlation_id: str,
        request: PentairCommandRequest,
        error: Exception,
    ) -> CommandReceipt:
        return CommandReceipt(
            status=status,
            command_id=correlation_id,
            message=str(error),
            verification_required=True,
            details={
                "endpoint_id": self.endpoint_id,
                "operation": request.operation,
                "target": request.target,
                "error_type": type(error).__name__,
            },
        )

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} must not be empty")
        return normalized
