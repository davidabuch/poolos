"""Exceptions raised by the vendor-command delivery boundary."""

from __future__ import annotations


class DeliveryError(Exception):
    """Base class for vendor-command delivery failures."""


class DuplicateEndpointError(DeliveryError):
    def __init__(self, endpoint_id: str) -> None:
        super().__init__(f"delivery endpoint already registered: {endpoint_id}")
        self.endpoint_id = endpoint_id


class EndpointNotFoundError(DeliveryError):
    def __init__(self, endpoint_id: str) -> None:
        super().__init__(f"delivery endpoint not registered: {endpoint_id}")
        self.endpoint_id = endpoint_id


class EndpointVendorMismatchError(DeliveryError):
    def __init__(self, endpoint_id: str, expected: str, actual: str) -> None:
        super().__init__(
            f"delivery endpoint {endpoint_id} vendor mismatch: "
            f"expected {expected}, got {actual}"
        )
        self.endpoint_id = endpoint_id
        self.expected = expected
        self.actual = actual


class EndpointDeliveryError(DeliveryError):
    def __init__(self, endpoint_id: str, correlation_id: str, cause: Exception) -> None:
        super().__init__(
            f"delivery endpoint {endpoint_id} failed for correlation "
            f"{correlation_id}: {cause}"
        )
        self.endpoint_id = endpoint_id
        self.correlation_id = correlation_id
        self.cause = cause
