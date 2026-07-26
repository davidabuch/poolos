"""Health and diagnostics models for PoolOS hardware adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional


class AdapterHealthState(str, Enum):
    UNKNOWN = "unknown"
    INITIALIZING = "initializing"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    READ_ONLY = "read_only"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    state: AdapterHealthState = AdapterHealthState.UNKNOWN
    message: str = ""
    last_contact: Optional[datetime] = None
    since: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_count: int = 0
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def writable(self) -> bool:
        return self.state in {AdapterHealthState.CONNECTED, AdapterHealthState.DEGRADED}

    @property
    def readable(self) -> bool:
        return self.state in {
            AdapterHealthState.CONNECTED,
            AdapterHealthState.DEGRADED,
            AdapterHealthState.READ_ONLY,
        }
