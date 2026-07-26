"""Runtime-focused event publication helpers.

PoolOS continues to use the kernel's synchronous :class:`EventBus` as the
single transport. This module standardizes runtime event names and publication
so subsystems do not invent incompatible payload shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .events import EventBus, PoolEvent


class RuntimeEventTopic:
    CYCLE_STARTED = "runtime.cycle.started"
    CYCLE_COMPLETED = "runtime.cycle.completed"
    COMMAND_AUTHORIZED = "runtime.command.authorized"
    COMMAND_BLOCKED = "runtime.command.blocked"
    COMMAND_CONSTRAINED = "runtime.command.constrained"
    COMMAND_SUBMITTED = "runtime.command.submitted"
    EXECUTION_COMPLETED = "runtime.execution.completed"
    RECONCILIATION_COMPLETED = "runtime.reconciliation.completed"


@dataclass(slots=True)
class RuntimeEventPublisher:
    """Publish normalized runtime events onto the existing kernel event bus."""

    bus: EventBus
    source: str = "pool_runtime"

    def publish(
        self,
        topic: str,
        occurred_at: datetime,
        *,
        payload: Any = None,
        source: str | None = None,
    ) -> PoolEvent:
        if occurred_at.tzinfo is None:
            raise ValueError("runtime event timestamp must be timezone-aware")
        event = PoolEvent(
            topic=topic,
            occurred_at=occurred_at,
            source=source or self.source,
            payload=payload,
        )
        self.bus.publish(event)
        return event
