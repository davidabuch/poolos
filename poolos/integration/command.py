"""Transport-neutral command objects produced by vendor translators."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class VendorCommand:
    """A logical vendor operation awaiting delivery by a transport."""

    vendor: str
    operation: str
    target: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, label in (
            (self.vendor, "vendor"),
            (self.operation, "operation"),
            (self.target, "target"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
