"""Awaitable shutdown of the pinned pyintellicenter connection-handler tasks."""

from __future__ import annotations

import asyncio
from typing import Any


async def async_quiesce_connection_handler(handler: Any) -> None:
    """Fence and await reconnect/debounce without upstream's fire-and-forget stop.

    pyintellicenter 0.1.20 ICConnectionHandler.stop() cancels these two tasks but
    drops their handles, then creates an unowned controller-stop task. PoolOS
    owns the controller and awaits its stop separately after this fence.
    """

    handler._stopped = True
    tasks = []
    for name in ("_starter_task", "_disconnect_debounce_task"):
        task = getattr(handler, name, None)
        setattr(handler, name, None)
        if task is not None:
            task.cancel()
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
