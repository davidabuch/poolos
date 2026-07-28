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
    TranslationConfigurationError,
    TranslatorNotFoundError,
    UnsupportedOperationError,
    VendorMismatchError,
)
from .handler import OperationTranslationHandler, TranslationContextProvider
from .operations import (
    PoolOperation,
    SetHeatMode,
    SetHydraulicRoute,
    SetPumpSpeed,
    StartPump,
    StopPump,
)
from .registry import TranslatorRegistry
from .response import TranslationResult
from .translator import Translator

__all__ = [
    "DuplicateTranslatorError",
    "EquipmentNotFoundError",
    "EquipmentTypeError",
    "IntegrationError",
    "MissingCapabilityError",
    "OperationTranslationHandler",
    "PoolOperation",
    "SetHeatMode",
    "SetHydraulicRoute",
    "SetPumpSpeed",
    "SetpointOutOfRangeError",
    "StartPump",
    "StopPump",
    "TranslationConfigurationError",
    "TranslationContext",
    "TranslationContextProvider",
    "TranslationResult",
    "Translator",
    "TranslatorNotFoundError",
    "TranslatorRegistry",
    "UnsupportedOperationError",
    "VendorCommand",
    "VendorMismatchError",
]
