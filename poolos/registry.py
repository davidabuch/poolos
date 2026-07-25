"""Canonical equipment registry used by the PoolOS kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .capabilities import Capability
from .equipment import Equipment
from .enums import BodyType, EquipmentType
from .exceptions import DuplicateRegistrationError, UnknownEquipmentError


@dataclass(slots=True)
class EquipmentRegistry:
    """Stores equipment and provides deterministic hardware-neutral queries."""

    _equipment: dict[str, Equipment] = field(default_factory=dict)

    def register(self, equipment: Equipment) -> None:
        if equipment.id in self._equipment:
            raise DuplicateRegistrationError(
                f"equipment already registered: {equipment.id}"
            )
        self._equipment[equipment.id] = equipment

    def get(self, equipment_id: str) -> Equipment:
        try:
            return self._equipment[equipment_id]
        except KeyError as exc:
            raise UnknownEquipmentError(equipment_id) from exc

    def all(self) -> tuple[Equipment, ...]:
        return tuple(self._equipment.values())

    def find_by_type(self, equipment_type: EquipmentType) -> tuple[Equipment, ...]:
        return tuple(
            equipment
            for equipment in self._equipment.values()
            if equipment.equipment_type is equipment_type
        )

    def find_by_capability(self, capability: Capability) -> tuple[Equipment, ...]:
        return tuple(
            equipment
            for equipment in self._equipment.values()
            if equipment.has_capability(capability)
        )

    def find_for_body(self, body: BodyType) -> tuple[Equipment, ...]:
        return tuple(
            equipment
            for equipment in self._equipment.values()
            if equipment.body is body
        )

    def enabled_equipment(self) -> tuple[Equipment, ...]:
        return tuple(
            equipment for equipment in self._equipment.values() if equipment.enabled
        )

    def primary_for(
        self,
        capability: Capability,
        *,
        body: Optional[BodyType] = None,
    ) -> Optional[Equipment]:
        """Return the first enabled match in registration order, if any."""

        for equipment in self._equipment.values():
            if not equipment.enabled or not equipment.has_capability(capability):
                continue
            if body is not None and equipment.body not in (None, body):
                continue
            return equipment
        return None
