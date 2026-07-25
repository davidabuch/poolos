"""Composition root and runtime owner for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass, field

from .bodies import BodyRegistry
from .clock import Clock, SystemClock
from .config import PoolOSConfig
from .events import EventBus, PoolEvent
from .models import BodyState
from .registry import EquipmentRegistry
from .state import EquipmentState, RuntimeState


@dataclass(slots=True)
class PoolKernel:
    """Owns registries, runtime state, time, configuration, and internal events."""

    config: PoolOSConfig = field(default_factory=PoolOSConfig)
    equipment: EquipmentRegistry = field(default_factory=EquipmentRegistry)
    bodies: BodyRegistry = field(default_factory=BodyRegistry)
    state: RuntimeState = field(default_factory=RuntimeState)
    events: EventBus = field(default_factory=EventBus)
    clock: Clock = field(default_factory=SystemClock)

    def update_body_state(self, body_id: str, state: BodyState) -> bool:
        """Store body state and publish ``state.body.changed`` when appropriate."""

        self.bodies.get(body_id)
        previous = self.state.set_body(body_id, state)
        changed = previous != state
        if changed or self.config.emit_unchanged_state_events:
            self.events.publish(
                PoolEvent(
                    topic="state.body.changed",
                    occurred_at=self.clock.now(),
                    source=body_id,
                    payload={"previous": previous, "current": state},
                )
            )
        return changed

    def update_equipment_state(
        self, equipment_id: str, state: EquipmentState
    ) -> bool:
        """Store equipment state and publish a normalized state event."""

        self.equipment.get(equipment_id)
        previous = self.state.set_equipment(equipment_id, state)
        changed = previous != state
        if changed or self.config.emit_unchanged_state_events:
            self.events.publish(
                PoolEvent(
                    topic="state.equipment.changed",
                    occurred_at=self.clock.now(),
                    source=equipment_id,
                    payload={"previous": previous, "current": state},
                )
            )
        return changed
