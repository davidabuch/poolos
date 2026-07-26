"""Common HAL value objects and equipment contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import FrozenSet, Mapping, Optional
from uuid import uuid4

from ..capabilities import Capability
from .exceptions import UnsupportedCapabilityError


class CommandStatus(str, Enum):
    ACCEPTED = "accepted"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    status: CommandStatus
    command_id: str = field(default_factory=lambda: str(uuid4()))
    message: str = ""
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: Optional[datetime] = None
    verification_required: bool = True
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status in {
            CommandStatus.ACCEPTED,
            CommandStatus.SENT,
            CommandStatus.ACKNOWLEDGED,
            CommandStatus.VERIFIED,
        }


@dataclass(frozen=True, slots=True)
class EquipmentMetadata:
    equipment_id: str
    name: str
    equipment_type: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    firmware: Optional[str] = None
    adapter_id: Optional[str] = None
    transport: Optional[str] = None
    capabilities: FrozenSet[Capability] = field(default_factory=frozenset)
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EquipmentObservation:
    equipment_id: str
    values: Mapping[str, object]
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    available: bool = True
    stale: bool = False
    source: Optional[str] = None


class HardwareEquipment(ABC):
    """Base contract implemented by vendor-specific equipment objects."""

    @property
    @abstractmethod
    def metadata(self) -> EquipmentMetadata: ...

    @property
    def capabilities(self) -> FrozenSet[Capability]:
        return self.metadata.capabilities

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def require(self, capability: Capability) -> None:
        if not self.supports(capability):
            raise UnsupportedCapabilityError(
                f"{self.metadata.equipment_id} does not support {capability.value}"
            )

    @abstractmethod
    def observe(self) -> EquipmentObservation: ...

    @abstractmethod
    def faults(self) -> tuple[str, ...]: ...
