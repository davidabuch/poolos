"""Single routing boundary for transport-neutral vendor commands."""

from __future__ import annotations

from dataclasses import dataclass

from ..hal import CommandReceipt
from ..integration import VendorCommand
from .exceptions import EndpointDeliveryError, EndpointVendorMismatchError
from .receipt import DeliveryReceipt
from .registry import EndpointRegistry


@dataclass(slots=True)
class VendorCommandGateway:
    """Resolve an endpoint, validate admission, and invoke it exactly once."""

    registry: EndpointRegistry

    def deliver(
        self,
        endpoint_id: str,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        endpoint_key = self._require_text(endpoint_id, "endpoint_id")
        correlation_key = self._require_text(correlation_id, "correlation_id")
        endpoint = self.registry.get(endpoint_key)

        endpoint_vendor = self._normalize_vendor(endpoint.vendor)
        command_vendor = self._normalize_vendor(command.vendor)
        if endpoint_vendor != command_vendor:
            raise EndpointVendorMismatchError(
                endpoint_key,
                endpoint_vendor,
                command_vendor,
            )

        try:
            receipt = endpoint.deliver(
                command,
                correlation_id=correlation_key,
                timeout=timeout,
            )
        except Exception as exc:
            raise EndpointDeliveryError(endpoint_key, correlation_key, exc) from exc

        if not isinstance(receipt, CommandReceipt):
            cause = TypeError("endpoint deliver() must return CommandReceipt")
            raise EndpointDeliveryError(endpoint_key, correlation_key, cause)

        return DeliveryReceipt(
            endpoint_id=endpoint_key,
            correlation_id=correlation_key,
            command=command,
            receipt=receipt,
        )

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} must not be empty")
        return normalized

    @staticmethod
    def _normalize_vendor(vendor: str) -> str:
        normalized = vendor.strip().lower()
        if not normalized:
            raise ValueError("vendor must not be empty")
        return normalized
