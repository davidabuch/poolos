"""Transport-neutral models for Home Assistant service execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class HomeAssistantServiceCall:
    """One Home Assistant service invocation prepared by a command mapper."""

    domain: str
    service: str
    target: Mapping[str, Any] = field(default_factory=dict)
    data: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, label in ((self.domain, "domain"), (self.service, "service")):
            normalized = value.strip().lower()
            if not normalized:
                raise ValueError(f"{label} must not be empty")
            object.__setattr__(self, label, normalized)
        object.__setattr__(self, "target", MappingProxyType(dict(self.target)))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True, slots=True)
class HomeAssistantServiceResult:
    """Outcome returned by a concrete Home Assistant service executor."""

    accepted: bool
    acknowledged: bool = False
    message: str = ""
    call_id: str | None = None
    received_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.acknowledged and not self.accepted:
            raise ValueError("an unaccepted Home Assistant call cannot be acknowledged")
        if self.call_id is not None:
            call_id = self.call_id.strip()
            if not call_id:
                raise ValueError("call_id must not be empty when provided")
            object.__setattr__(self, "call_id", call_id)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
