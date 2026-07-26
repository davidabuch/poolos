"""Public PoolOS hardware abstraction layer API."""
from .adapter import AdapterMetadata, HardwareAdapter
from .base import CommandReceipt, CommandStatus, EquipmentMetadata, EquipmentObservation, HardwareEquipment
from .equipment import Chlorinator, Cover, Filter, Heater, Light, Pump, Sensor, Valve
from .exceptions import (
    AdapterNotFoundError,
    AdapterStateError,
    CommandTimeoutError,
    DuplicateAdapterError,
    HALError,
    TransportError,
    TransportUnavailableError,
    UnsupportedCapabilityError,
)
from .health import AdapterHealth, AdapterHealthState
from .registry import AdapterRegistry
from .transport import Transport, TransportMetadata, TransportResponse, TransportState
from .transports import HomeAssistantTransport, RS485Transport, SimulatorTransport

__all__ = [
    "AdapterHealth", "AdapterHealthState", "AdapterMetadata", "AdapterRegistry",
    "CommandReceipt", "CommandStatus", "EquipmentMetadata", "EquipmentObservation",
    "HardwareAdapter", "HardwareEquipment", "Transport", "TransportMetadata",
    "TransportResponse", "TransportState", "SimulatorTransport",
    "HomeAssistantTransport", "RS485Transport", "Pump", "Heater", "Valve",
    "Filter", "Light", "Chlorinator", "Sensor", "Cover",
]
