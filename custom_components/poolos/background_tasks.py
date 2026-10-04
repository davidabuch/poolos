"""Ownership of noncritical work across purpose changes and integration stop."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PoolOSBackgroundTasks:
    """Fence scheduling synchronously, then cancel and await owned auxiliary work."""

    _stopping: bool = False
    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _settling_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def create(
        self,
        hass: Any,
        coroutine: Coroutine[Any, Any, Any],
        name: str,
        *,
        cancel_on_stop: bool = True,
    ) -> asyncio.Task[Any] | None:
        if self._stopping:
            coroutine.close()
            return
        task = hass.async_create_task(coroutine, name)
        self._tasks.add(task)
        if not cancel_on_stop:
            self._settling_tasks.add(task)
        task.add_done_callback(self._settling_tasks.discard)
        task.add_done_callback(self._tasks.discard)
        return task

    def prepare_stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        for task in self._tasks:
            if task not in self._settling_tasks and not task.cancelling():
                task.cancel()

    async def async_stop(self) -> None:
        self.prepare_stop()
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._settling_tasks.clear()
