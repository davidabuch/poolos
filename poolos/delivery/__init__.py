"""Public API for vendor-command routing and endpoint delivery."""

from .endpoint import VendorCommandEndpoint
from .exceptions import (
    DeliveryError,
    DuplicateEndpointError,
    EndpointDeliveryError,
    EndpointNotFoundError,
    EndpointVendorMismatchError,
)
from .gateway import VendorCommandGateway
from .receipt import DeliveryReceipt
from .registry import EndpointRegistry
from .simulator import SimulatorVendorCommandEndpoint

__all__ = [
    "DeliveryError",
    "DeliveryReceipt",
    "DuplicateEndpointError",
    "EndpointDeliveryError",
    "EndpointNotFoundError",
    "EndpointRegistry",
    "EndpointVendorMismatchError",
    "SimulatorVendorCommandEndpoint",
    "VendorCommandEndpoint",
    "VendorCommandGateway",
]
