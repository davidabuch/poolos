"""Exceptions raised by the PoolOS vendor integration framework."""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for vendor integration failures."""


class DuplicateTranslatorError(IntegrationError):
    def __init__(self, vendor: str) -> None:
        super().__init__(f"translator already registered for vendor: {vendor}")
        self.vendor = vendor


class TranslatorNotFoundError(IntegrationError):
    def __init__(self, vendor: str) -> None:
        super().__init__(f"translator not registered for vendor: {vendor}")
        self.vendor = vendor


class VendorMismatchError(IntegrationError):
    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(f"translation context vendor mismatch: expected {expected}, got {actual}")
        self.expected = expected
        self.actual = actual


class UnsupportedOperationError(IntegrationError):
    def __init__(self, vendor: str, operation_type: type[object]) -> None:
        name = operation_type.__name__
        super().__init__(f"vendor {vendor} does not support operation: {name}")
        self.vendor = vendor
        self.operation_type = operation_type
