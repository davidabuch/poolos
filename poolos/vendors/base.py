"""Shared vendor-domain value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True, slots=True)
class VendorIdentity:
    """Stable identity and metadata for a supported equipment vendor."""

    vendor_id: str
    name: str
    family: Optional[str] = None
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vendor_id.strip():
            raise ValueError("vendor_id must not be empty")
        if not self.name.strip():
            raise ValueError("vendor name must not be empty")
        object.__setattr__(self, "attributes", dict(self.attributes))
