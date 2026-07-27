"""Execution context made available to vendor translators."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TranslationContext:
    """Immutable installation and capability facts used during translation."""

    vendor: str
    controller_model: str | None = None
    firmware_version: str | None = None
    equipment: Mapping[str, Any] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    feature_flags: frozenset[str] = field(default_factory=frozenset)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vendor.strip():
            raise ValueError("vendor must not be empty")
        object.__setattr__(self, "equipment", MappingProxyType(dict(self.equipment)))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "feature_flags", frozenset(self.feature_flags))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
