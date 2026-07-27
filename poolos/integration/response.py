"""Structured results returned by vendor translators."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .command import VendorCommand


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """One deterministic translation, including diagnostics and annotations."""

    commands: tuple[VendorCommand, ...]
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
