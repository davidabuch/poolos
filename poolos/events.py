"""Synchronous internal event model and event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass(frozen=True, slots=True)
class PoolEvent:
    """An immutable fact published by the PoolOS kernel."""

    topic: str
    occurred_at: datetime
    source: str
    payload: Any = None


EventHandler = Callable[[PoolEvent], None]


@dataclass(slots=True)
class EventBus:
    """Small synchronous event bus with topic and wildcard subscriptions."""

    _subscribers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def subscribe(self, topic: str, handler: EventHandler) -> Callable[[], None]:
        handlers = self._subscribers.setdefault(topic, [])
        handlers.append(handler)

        def unsubscribe() -> None:
            current = self._subscribers.get(topic)
            if current is None:
                return
            try:
                current.remove(handler)
            except ValueError:
                return
            if not current:
                self._subscribers.pop(topic, None)

        return unsubscribe

    def publish(self, event: PoolEvent) -> None:
        handlers = tuple(self._subscribers.get(event.topic, ()))
        wildcard_handlers = tuple(self._subscribers.get("*", ()))
        for handler in handlers + wildcard_handlers:
            handler(event)
