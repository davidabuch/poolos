"""Public API for transport-independent vendor integration."""

from .command import VendorCommand
from .context import TranslationContext
from .exceptions import (
    DuplicateTranslatorError,
    EquipmentNotFoundError,
    EquipmentTypeError,
    IntegrationError,
    MissingCapabilityError,
    SetpointOutOfRangeError,
    TranslatorNotFoundError,
    UnsupportedOperationError,
    VendorMismatchError,
)
from .operations import PoolOperation, SetHeatMode, SetPumpSpeed, StartPump, StopPump
from .registry import TranslatorRegistry
from .response import TranslationResult
from .translator import Translator

__all__ = [
    "DuplicateTranslatorError",
    "EquipmentNotFoundError",
    "EquipmentTypeError",
    "IntegrationError",
    "MissingCapabilityError",
    "PoolOperation",
    "SetHeatMode",
    "SetPumpSpeed",
    "SetpointOutOfRangeError",
    "StartPump",
    "StopPump",
    "TranslationContext",
    "TranslationResult",
    "Translator",
    "TranslatorNotFoundError",
    "TranslatorRegistry",
    "UnsupportedOperationError",
    "VendorCommand",
    "VendorMismatchError",
]
