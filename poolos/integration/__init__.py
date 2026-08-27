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
    PhysicalHeatMode,
    PoolOperation,
    SetHeatMode,
    SetHydraulicRoute,
    SetPumpSpeed,
    StartPump,
    StopPump,
    ThermalBody,
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
    "PhysicalHeatMode",
    "PoolOperation",
    "SetHeatMode",
    "SetHydraulicRoute",
    "SetPumpSpeed",
    "SetpointOutOfRangeError",
    "StartPump",
    "StopPump",
    "ThermalBody",
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
