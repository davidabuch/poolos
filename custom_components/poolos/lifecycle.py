"""One command-free stop boundary shared by HA shutdown and config-entry unload."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import PoolOSRuntimeData


LOGGER = logging.getLogger(__name__)


class PoolOSIntegrationLifecycle:
    """Fence every producer before yielding, drain it, then disconnect transports."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._complete = False

    async def async_stop(
        self, data: PoolOSRuntimeData, *, homeassistant_stop: bool = False
    ) -> None:
        async with self._lock:
            if self._complete:
                return
            # Final-write persistence keeps only an already-exportable checkpoint,
            # with its original receipts and age. Reload does not arm restoration.
            if homeassistant_stop:
                data.thermal_automatic_runtime.preserve_shutdown_checkpoint()
            data.coordinator.prepare_unload()
            data.thermal_runtime.set_orchestration_observer(None)
            data.thermal_runtime.set_orchestration_failure_observer(None)
            if data.manual_intellicenter is not None:
                data.manual_intellicenter.prepare_stop()
            runtimes = (
                data.grid_outage_safety_runtime,
                data.sanitation_runtime,
                data.thermal_automatic_runtime,
                data.filtration_automatic_runtime,
            )
            for runtime in runtimes:
                runtime.prepare_unload()
            # No await precedes these fences. An already dispatched command may
            # settle its truthful receipt; no successor operation may be issued.
            results = await asyncio.gather(
                *(runtime.async_unload() for runtime in runtimes), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    LOGGER.error(
                        "PoolOS runtime drain failed during command-free stop",
                        exc_info=(type(result), result, result.__traceback__),
                    )
            data.thermal_runtime_orchestrator.unload(unloaded_at=datetime.now(UTC))
            try:
                await data.coordinator.async_prepare_unload()
            except Exception:
                LOGGER.exception("PoolOS coordinator drain failed during command-free stop")
            finally:
                # Even a persistence/analysis failure must not leave either
                # transport's reconnect/background tasks alive during final writes.
                stops = [data.coordinator.async_stop_independent_intellicenter()]
                if data.manual_intellicenter is not None:
                    stops.append(data.manual_intellicenter.async_stop())
                results = await asyncio.gather(*stops, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        LOGGER.error(
                            "PoolOS transport drain failed during command-free stop",
                            exc_info=(type(result), result, result.__traceback__),
                        )
            self._complete = True
