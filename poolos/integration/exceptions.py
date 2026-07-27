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


class EquipmentNotFoundError(IntegrationError):
    def __init__(self, equipment_id: str) -> None:
        super().__init__(f"translation equipment not found: {equipment_id}")
        self.equipment_id = equipment_id


class EquipmentTypeError(IntegrationError):
    def __init__(self, equipment_id: str, expected: type[object], actual: type[object]) -> None:
        super().__init__(
            f"translation equipment {equipment_id} must be {expected.__name__}, "
            f"got {actual.__name__}"
        )
        self.equipment_id = equipment_id
        self.expected = expected
        self.actual = actual


class MissingCapabilityError(IntegrationError):
    def __init__(self, equipment_id: str, capability: str) -> None:
        super().__init__(f"equipment {equipment_id} lacks required capability: {capability}")
        self.equipment_id = equipment_id
        self.capability = capability


class TranslationConfigurationError(IntegrationError):
    """Raised when vendor configuration cannot safely satisfy an operation."""


class SetpointOutOfRangeError(IntegrationError):
    def __init__(
        self,
        equipment_id: str,
        parameter: str,
        value: int | float,
        minimum: int | float | None,
        maximum: int | float | None,
    ) -> None:
        bounds = []
        if minimum is not None:
            bounds.append(f"minimum {minimum}")
        if maximum is not None:
            bounds.append(f"maximum {maximum}")
        detail = ", ".join(bounds) or "configured bounds unavailable"
        super().__init__(
            f"{parameter} setpoint {value} is invalid for equipment {equipment_id}: {detail}"
        )
        self.equipment_id = equipment_id
        self.parameter = parameter
        self.value = value
        self.minimum = minimum
        self.maximum = maximum
