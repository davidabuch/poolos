"""Public API for vendor-command routing and endpoint delivery."""

from .endpoint import DeliveryEndpointKind, VendorCommandEndpoint
from .exceptions import (
    DeliveryError,
    DuplicateEndpointError,
    EndpointDeliveryError,
    EndpointNotFoundError,
    EndpointVendorMismatchError,
)
from .gateway import VendorCommandGateway
from .pentair import (
    PentairCommandClient,
    PentairCommandClientError,
    PentairCommandRequest,
    PentairCommandResponse,
    PentairCommandTimeoutError,
    PentairVendorCommandEndpoint,
)
from .receipt import DeliveryReceipt
from .registry import EndpointRegistry
from .simulator import SimulatorVendorCommandEndpoint

__all__ = [
    "DeliveryEndpointKind",
    "DeliveryError",
    "DeliveryReceipt",
    "DuplicateEndpointError",
    "EndpointDeliveryError",
    "EndpointNotFoundError",
    "EndpointRegistry",
    "EndpointVendorMismatchError",
    "PentairCommandClient",
    "PentairCommandClientError",
    "PentairCommandRequest",
    "PentairCommandResponse",
    "PentairCommandTimeoutError",
    "PentairVendorCommandEndpoint",
    "SimulatorVendorCommandEndpoint",
    "VendorCommandEndpoint",
    "VendorCommandGateway",
]
