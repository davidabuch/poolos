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
    system_id: Optional[str] = None
    shared_body_ids: FrozenSet[str] = field(default_factory=frozenset)

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


@dataclass(frozen=True, slots=True)
class FilterEquipment:
    """First-class filter model with optional instrumentation.

    An analog gauge does not create a digital pressure reading.  Pressure and
    flow observations remain optional, while maintenance history and learned
    health estimates can still be represented.
    """

    equipment: Equipment
    media_type: Optional[str] = None
    filter_area_sq_ft: Optional[float] = None
    pressure_psi: Optional[float] = None
    flow_gpm: Optional[float] = None
    estimated_health: Optional[float] = None

    def __post_init__(self) -> None:
        if self.pressure_psi is not None and self.pressure_psi < 0:
            raise ValueError("pressure must not be negative")
        if self.flow_gpm is not None and self.flow_gpm < 0:
            raise ValueError("flow must not be negative")
        if self.estimated_health is not None and not 0.0 <= self.estimated_health <= 1.0:
            raise ValueError("estimated health must be between 0 and 1")

    @property
    def has_digital_pressure(self) -> bool:
        return self.pressure_psi is not None
