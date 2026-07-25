"""Immutable commands shared by all PoolOS subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from .enums import CommandPriority


class CommandAction(str, Enum):
    """Hardware-independent actions understood by the execution layer."""

    SET = "set"
    START = "start"
    STOP = "stop"
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(frozen=True, slots=True)
class Command:
    """One immutable request to change a body or equipment item.

    Commands describe intent only. They do not contain adapter-specific entity
    identifiers, service calls, or transport details.
    """

    target: str
    action: CommandAction
    value: Any = None
    priority: CommandPriority = CommandPriority.NORMAL
    requested_by: str = "poolos"
    correlation_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("command target must not be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by must not be empty")
        if not self.command_id.strip():
            raise ValueError("command_id must not be empty")
        if self.issued_at.tzinfo is None:
            raise ValueError("issued_at must be timezone-aware")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def deduplication_key(self) -> tuple[str, CommandAction]:
        """Return the queue key used for latest-command-wins deduplication."""

        return (self.target, self.action)
