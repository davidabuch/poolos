"""Hardware-independent equipment definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Optional

from .capabilities import Capability
from .enums import BodyType, EquipmentType


@dataclass(frozen=True, slots=True)
class Equipment:
    """A physical or logical equipment item known to PoolOS.

    ``capabilities`` accepts both :class:`Capability` members and their stable
    string values for compatibility with early PoolOS milestones. Values are
    normalized to ``Capability`` members at construction time.
    """

    id: str
    name: str
    equipment_type: EquipmentType
    capabilities: FrozenSet[Capability] = field(default_factory=frozenset)
    body: Optional[BodyType] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("equipment id must not be empty")
        if not self.name.strip():
            raise ValueError("equipment name must not be empty")

        normalized = frozenset(
            item if isinstance(item, Capability) else Capability(item)
            for item in self.capabilities
        )
        object.__setattr__(self, "capabilities", normalized)

    def has_capability(self, capability: Capability) -> bool:
        """Return whether this equipment provides ``capability``."""

        return capability in self.capabilities
