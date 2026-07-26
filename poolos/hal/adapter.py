"""Vendor adapter lifecycle and discovery contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .base import HardwareEquipment
from .health import AdapterHealth
from .transport import Transport


@dataclass(frozen=True, slots=True)
class AdapterMetadata:
    adapter_id: str
    name: str
    version: str
    vendor: Optional[str] = None
    supported_equipment: tuple[str, ...] = ()
    attributes: Mapping[str, object] = field(default_factory=dict)


class HardwareAdapter(ABC):
    """Translates vendor semantics into stable PoolOS HAL contracts."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def discover(self) -> Sequence[HardwareEquipment]: ...

    @abstractmethod
    def health(self) -> AdapterHealth: ...

    def shutdown(self) -> None:
        self.disconnect()
