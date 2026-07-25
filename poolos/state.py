"""Runtime state owned by the PoolOS kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .models import BodyState


@dataclass(frozen=True, slots=True)
class EquipmentState:
    """Latest normalized state for one equipment item."""

    available: bool = True
    active: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    observed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(slots=True)
class RuntimeState:
    """In-memory source of truth for the latest normalized installation state."""

    _bodies: dict[str, BodyState] = field(default_factory=dict)
    _equipment: dict[str, EquipmentState] = field(default_factory=dict)

    def set_body(self, body_id: str, state: BodyState) -> Optional[BodyState]:
        previous = self._bodies.get(body_id)
        self._bodies[body_id] = state
        return previous

    def get_body(self, body_id: str) -> Optional[BodyState]:
        return self._bodies.get(body_id)

    def body_snapshot(self) -> Mapping[str, BodyState]:
        return MappingProxyType(dict(self._bodies))

    def set_equipment(
        self, equipment_id: str, state: EquipmentState
    ) -> Optional[EquipmentState]:
        previous = self._equipment.get(equipment_id)
        self._equipment[equipment_id] = state
        return previous

    def get_equipment(self, equipment_id: str) -> Optional[EquipmentState]:
        return self._equipment.get(equipment_id)

    def equipment_snapshot(self) -> Mapping[str, EquipmentState]:
        return MappingProxyType(dict(self._equipment))
