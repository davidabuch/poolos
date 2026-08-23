"""Narrow manual-control gateway for PoolOS-owned IntelliCenter commands.

This module is intentionally separate from PoolOS's independent read-only
IntelliCenter transport.

The read-only transport remains authoritative for observation truth.
This gateway exists only for explicit operator/Home Assistant commands and
exposes a deliberately tiny mutation surface:

* turn Pool/Spa body circulation on or off
* change Pool/Spa heating setpoint
* turn explicitly allow-listed Jets, Slide, and Spillway circuits on or off

No generic SETPARAMLIST interface is exposed to Home Assistant entities.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from pyintellicenter import (
    ICBaseController,
    ICConnectionHandler,
    ICModelController,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    PoolModel,
)

_ALLOWED_BODY_IDS = frozenset({"B1101", "B1202"})
_ALLOWED_CIRCUIT_IDS = frozenset({"C0002", "C0003", "C0004", "FTR01"})
_MIN_TARGET_TEMPERATURE = 40
_MAX_TARGET_TEMPERATURE = 104


class ManualIntelliCenterState(str, Enum):
    """Lifecycle state for the manual-control connection."""

    INITIALIZING = "INITIALIZING"
    CONNECTING = "CONNECTING"
    AVAILABLE = "AVAILABLE"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    UNAVAILABLE = "UNAVAILABLE"


class ManualIntelliCenterCommandError(RuntimeError):
    """Raised when a manual IntelliCenter command cannot be delivered safely."""


@dataclass(frozen=True, slots=True)
class ManualCommandReceipt:
    """Describe one accepted manual control request."""

    body_objnam: str
    operation: str
    value: bool | int


class _ManualConnectionHandler(ICConnectionHandler):
    """Forward controller lifecycle into the narrow manual gateway."""

    def __init__(
        self,
        owner: ManualIntelliCenterControl,
        controller: ICModelController,
        *,
        reconnect_delay: int,
    ) -> None:
        super().__init__(
            controller,
            time_between_reconnects=reconnect_delay,
        )
        self._owner = owner

    def on_started(self, controller: ICBaseController) -> None:
        del controller
        self._owner._on_connected(reconnected=False)

    def on_reconnected(self, controller: ICBaseController) -> None:
        del controller
        self._owner._on_connected(reconnected=True)

    def on_disconnected(
        self,
        controller: ICBaseController,
        exc: Exception | None,
    ) -> None:
        del controller
        self._owner._on_disconnected(exc)

    def on_retrying(self, delay: int) -> None:
        del delay
        self._owner._state = ManualIntelliCenterState.RECONNECTING


class ManualIntelliCenterControl:
    """Own a separate, narrow IntelliCenter manual-command connection."""

    def __init__(
        self,
        *,
        host: str,
        transport: str = "tcp",
        keepalive_interval: float = 90.0,
        reconnect_delay: int = 30,
    ) -> None:
        normalized_host = host.strip()
        if not normalized_host:
            raise ValueError("manual IntelliCenter host must not be blank")
        if transport not in {"tcp", "websocket"}:
            raise ValueError("manual IntelliCenter transport must be tcp or websocket")
        if keepalive_interval <= 0:
            raise ValueError("manual IntelliCenter keepalive interval must be positive")
        if reconnect_delay <= 0:
            raise ValueError("manual IntelliCenter reconnect delay must be positive")

        self._host = normalized_host
        self._transport_name = transport
        self._model = PoolModel()
        self._controller = ICModelController(
            normalized_host,
            self._model,
            keepalive_interval=keepalive_interval,
            transport=transport,
        )
        self._handler = _ManualConnectionHandler(
            self,
            self._controller,
            reconnect_delay=reconnect_delay,
        )

        self._state = ManualIntelliCenterState.INITIALIZING
        self._running = False
        self._command_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._reconnect_count = 0

    @property
    def state(self) -> ManualIntelliCenterState:
        """Return current manual connection state."""

        return self._state

    @property
    def available(self) -> bool:
        """Return whether manual command delivery is available."""

        return self._state is ManualIntelliCenterState.AVAILABLE

    async def async_start(self) -> None:
        """Start the independent manual command connection."""

        if self._running:
            return

        self._running = True
        self._state = ManualIntelliCenterState.CONNECTING

        try:
            await self._handler.start()
        except Exception as exc:
            self._last_error_code = type(exc).__name__.upper()
            self._state = ManualIntelliCenterState.RECONNECTING

    async def async_stop(self) -> None:
        """Stop reconnect handling and disconnect the manual controller."""

        if not self._running:
            self._state = ManualIntelliCenterState.UNAVAILABLE
            return

        self._running = False
        self._handler.stop()

        with contextlib.suppress(Exception):
            await self._controller.stop()

        self._state = ManualIntelliCenterState.UNAVAILABLE

    async def async_set_body_active(
        self,
        body_objnam: str,
        active: bool,
    ) -> ManualCommandReceipt:
        """Turn Pool/Spa body circulation on or off."""

        self._require_body(body_objnam)
        if not isinstance(active, bool):
            raise ValueError("body active state must be boolean")

        await self._require_available()

        async with self._command_lock:
            try:
                await self._controller.request_changes(
                    body_objnam,
                    {
                        STATUS_ATTR: STATUS_ON if active else STATUS_OFF,
                    },
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {body_objnam} active state"
                ) from exc

        self._last_error_code = None
        return ManualCommandReceipt(
            body_objnam=body_objnam,
            operation="body_active",
            value=active,
        )

    async def async_set_circuit_state(
        self,
        circuit_objnam: str,
        active: bool,
    ) -> ManualCommandReceipt:
        """Turn one explicitly allow-listed IntelliCenter circuit on or off."""

        self._require_circuit(circuit_objnam)

        if not isinstance(active, bool):
            raise ValueError("circuit active state must be boolean")

        await self._require_available()

        async with self._command_lock:
            try:
                await self._controller.set_circuit_state(
                    circuit_objnam,
                    active,
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {circuit_objnam} circuit state"
                ) from exc

        self._last_error_code = None
        return ManualCommandReceipt(
            body_objnam=circuit_objnam,
            operation="circuit_active",
            value=active,
        )

    async def async_set_heating_setpoint(
        self,
        body_objnam: str,
        temperature: int | float,
    ) -> ManualCommandReceipt:
        """Set Pool/Spa heating target through IntelliCenter LOTMP."""

        self._require_body(body_objnam)

        if isinstance(temperature, bool) or not isinstance(
            temperature,
            (int, float),
        ):
            raise ValueError("temperature must be numeric")

        target = int(round(float(temperature)))

        if not _MIN_TARGET_TEMPERATURE <= target <= _MAX_TARGET_TEMPERATURE:
            raise ValueError(
                "temperature must be between "
                f"{_MIN_TARGET_TEMPERATURE} and {_MAX_TARGET_TEMPERATURE}"
            )

        await self._require_available()

        async with self._command_lock:
            try:
                await self._controller.set_heating_setpoint(
                    body_objnam,
                    target,
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {body_objnam} heating setpoint"
                ) from exc

        self._last_error_code = None
        return ManualCommandReceipt(
            body_objnam=body_objnam,
            operation="heating_setpoint",
            value=target,
        )

    def diagnostics(self) -> Mapping[str, Any]:
        """Return bounded diagnostics without exposing a generic command API."""

        return MappingProxyType(
            {
                "state": self._state.value,
                "available": self.available,
                "selected_transport": self._transport_name,
                "allowed_operations": [
                    "body_active",
                    "heating_setpoint",
                    "circuit_active",
                ],
                "allowed_body_ids": sorted(_ALLOWED_BODY_IDS),
                "allowed_circuit_ids": sorted(_ALLOWED_CIRCUIT_IDS),
                "target_temperature_min": _MIN_TARGET_TEMPERATURE,
                "target_temperature_max": _MAX_TARGET_TEMPERATURE,
                "last_error_code": self._last_error_code,
                "reconnect_count": self._reconnect_count,
                "manual_command_delivery_enabled": True,
                "autonomous_command_delivery_enabled": False,
            }
        )

    async def _require_available(self) -> None:
        if not self.available:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is unavailable"
            )

    @staticmethod
    def _require_body(body_objnam: str) -> None:
        if body_objnam not in _ALLOWED_BODY_IDS:
            raise ValueError(
                f"unsupported manual-control body: {body_objnam}"
            )

    @staticmethod
    def _require_circuit(circuit_objnam: str) -> None:
        if circuit_objnam not in _ALLOWED_CIRCUIT_IDS:
            raise ValueError(
                f"unsupported manual-control circuit: {circuit_objnam}"
            )

    def _on_connected(self, *, reconnected: bool) -> None:
        self._state = ManualIntelliCenterState.AVAILABLE
        self._last_error_code = None
        if reconnected:
            self._reconnect_count += 1

    def _on_disconnected(self, exc: Exception | None) -> None:
        self._state = ManualIntelliCenterState.DISCONNECTED
        if exc is not None:
            self._last_error_code = type(exc).__name__.upper()


__all__ = [
    "ManualCommandReceipt",
    "ManualIntelliCenterCommandError",
    "ManualIntelliCenterControl",
    "ManualIntelliCenterState",
]
