"""Transport contracts separating vendor semantics from message delivery."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional


class TransportState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TransportMetadata:
    name: str
    version: str = "unknown"
    state: TransportState = TransportState.DISCONNECTED
    last_contact: Optional[datetime] = None
    latency_ms: Optional[float] = None
    retry_count: int = 0
    error_count: int = 0
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    accepted: bool
    payload: object = None
    acknowledged: bool = False
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None


class Transport(ABC):
    """Moves commands and observations without understanding pool semantics."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def send(self, destination: str, payload: object, *, timeout: Optional[float] = None) -> TransportResponse: ...

    @abstractmethod
    def read(self, source: str, *, timeout: Optional[float] = None) -> TransportResponse: ...

    @abstractmethod
    def metadata(self) -> TransportMetadata: ...
