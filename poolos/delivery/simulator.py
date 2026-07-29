"""In-memory vendor-command endpoint backed by the HAL simulator transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Mapping

from ..hal import (
    CommandReceipt,
    CommandStatus,
    CommandTimeoutError,
    SimulatorTransport,
    Transport,
    TransportError,
    TransportResponse,
)
from ..integration import VendorCommand
from .endpoint import DeliveryEndpointKind


@dataclass(slots=True)
class SimulatorVendorCommandEndpoint:
    """Deliver vendor commands through an in-memory simulator transport.

    The endpoint deliberately preserves the command's vendor dialect. It does
    not interpret pool semantics; it only adapts the transport-neutral command
    into a deterministic simulator payload and maps the transport response into
    a HAL ``CommandReceipt``.
    """

    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SIMULATOR

    endpoint_id: str
    vendor: str
    transport: Transport
    destination_prefix: str = "vendor-commands"

    def __init__(
        self,
        endpoint_id: str,
        vendor: str,
        transport: Transport | None = None,
        *,
        destination_prefix: str = "vendor-commands",
    ) -> None:
        self.endpoint_id = self._require_text(endpoint_id, "endpoint_id")
        self.vendor = self._require_text(vendor, "vendor")
        self.transport = (
            transport
            if transport is not None
            else SimulatorTransport(name=f"{self.endpoint_id}-simulator")
        )
        normalized_prefix = self._require_text(
            destination_prefix,
            "destination_prefix",
        ).strip("/")
        if not normalized_prefix:
            raise ValueError("destination_prefix must not be empty")
        self.destination_prefix = normalized_prefix

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        correlation_key = self._require_text(correlation_id, "correlation_id")
        self._validate_vendor(command.vendor)
        destination = self._destination(command)
        payload = self._payload(command, correlation_key)

        try:
            response = self.transport.send(
                destination,
                payload,
                timeout=timeout,
            )
        except CommandTimeoutError as exc:
            return self._failure_receipt(
                CommandStatus.TIMED_OUT,
                correlation_key,
                destination,
                exc,
            )
        except TransportError as exc:
            return self._failure_receipt(
                CommandStatus.FAILED,
                correlation_key,
                destination,
                exc,
            )

        return self._receipt_from_response(
            response,
            correlation_id=correlation_key,
            destination=destination,
        )

    def _validate_vendor(self, command_vendor: str) -> None:
        expected = self.vendor.strip().lower()
        actual = command_vendor.strip().lower()
        if expected != actual:
            raise ValueError(
                f"endpoint vendor {expected!r} does not match command vendor {actual!r}"
            )

    def _destination(self, command: VendorCommand) -> str:
        vendor = command.vendor.strip().lower()
        target = command.target.strip().strip("/")
        return f"{self.destination_prefix}/{vendor}/{target}"

    def _payload(
        self,
        command: VendorCommand,
        correlation_id: str,
    ) -> Mapping[str, Any]:
        return {
            "vendor": command.vendor,
            "operation": command.operation,
            "target": command.target,
            "parameters": dict(command.parameters),
            "metadata": dict(command.metadata),
            "correlation_id": correlation_id,
            "endpoint_id": self.endpoint_id,
        }

    def _receipt_from_response(
        self,
        response: TransportResponse,
        *,
        correlation_id: str,
        destination: str,
    ) -> CommandReceipt:
        if not response.accepted:
            status = CommandStatus.REJECTED
            message = "simulator transport rejected command"
        elif response.acknowledged:
            status = CommandStatus.ACKNOWLEDGED
            message = "simulator transport acknowledged command"
        else:
            status = CommandStatus.SENT
            message = "simulator transport accepted command"

        acknowledged_at: datetime | None = (
            response.received_at if response.acknowledged else None
        )
        return CommandReceipt(
            status=status,
            command_id=correlation_id,
            message=message,
            acknowledged_at=acknowledged_at,
            verification_required=True,
            details={
                "endpoint_id": self.endpoint_id,
                "destination": destination,
                "transport_correlation_id": response.correlation_id,
                "transport_payload": response.payload,
            },
        )

    def _failure_receipt(
        self,
        status: CommandStatus,
        correlation_id: str,
        destination: str,
        error: Exception,
    ) -> CommandReceipt:
        return CommandReceipt(
            status=status,
            command_id=correlation_id,
            message=str(error),
            verification_required=True,
            details={
                "endpoint_id": self.endpoint_id,
                "destination": destination,
                "error_type": type(error).__name__,
            },
        )

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} must not be empty")
        return normalized
