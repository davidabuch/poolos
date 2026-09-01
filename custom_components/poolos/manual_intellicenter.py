"""Narrow manual-control gateway for PoolOS-owned IntelliCenter commands.

This module is intentionally separate from PoolOS's independent read-only
IntelliCenter transport.

The read-only transport remains authoritative for observation truth.
This gateway exists only for explicit operator/Home Assistant commands and
exposes a deliberately tiny mutation surface:

* turn Pool/Spa body circulation on or off
* change Pool/Spa heating setpoint
* select one commissioned Pool/Spa heat source
* set one commissioned IntelliChlor Pool/Spa output percentage
* turn explicitly allow-listed Jets, Slide, Spillway, and Pool Light circuits on or off
* change the Pool Light IntelliBrite effect on C0002
* change the explicitly allow-listed Pool PMPCIRC RPM setpoint on p0102

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
    BODY_ATTR,
    CHEM_TYPE,
    ICBaseController,
    ICConnectionHandler,
    ICModelController,
    HEATER_ATTR,
    LIGHT_EFFECTS,
    MAX_ATTR,
    MIN_ATTR,
    PARENT_ATTR,
    PMPCIRC_TYPE,
    PRIM_ATTR,
    PUMP_TYPE,
    SELECT_ATTR,
    SPEED_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    PoolModel,
)

_ALLOWED_BODY_IDS = frozenset({"B1101", "B1202"})
_ALLOWED_CIRCUIT_IDS = frozenset({"C0002", "C0003", "C0004", "FTR01"})
_POOL_LIGHT_OBJNAM = "C0002"
_INTELLICHLOR_OBJNAM = "CHR01"
_POOL_SOLAR_HEATER_OBJNAM = "H0002"
_NO_HEATER_OBJNAM = "00000"
_GAS_HEATER_OBJNAM = "H0001"
_ALLOWED_HEAT_SOURCE_IDS = frozenset(
    {
        _NO_HEATER_OBJNAM,
        _GAS_HEATER_OBJNAM,
        _POOL_SOLAR_HEATER_OBJNAM,
    }
)

# p0102 is the native IntelliCenter PMPCIRC backing the existing
# number.buch_family_rpm_pool entity. This is a circuit speed setpoint,
# not the physical pump RPM telemetry value.
_ALLOWED_PUMP_CIRCUIT_IDS = frozenset({"p0102"})
_PUMP_RPM_MODE = "RPM"

_MIN_TARGET_TEMPERATURE = 40
_MAX_TARGET_TEMPERATURE = 104


def _percentage(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return None
    return numeric if 0 <= numeric <= 100 else None


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
    value: bool | int | str


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


    async def async_set_light_effect(
        self,
        circuit_objnam: str,
        effect: str,
    ) -> ManualCommandReceipt:
        """Set the IntelliBrite effect for the Pool Light circuit."""

        if circuit_objnam != _POOL_LIGHT_OBJNAM:
            raise ValueError(
                f"unsupported manual-control light circuit: {circuit_objnam}"
            )

        if effect not in LIGHT_EFFECTS:
            raise ValueError(
                f"unsupported Pool Light effect: {effect}"
            )

        await self._require_available()

        async with self._command_lock:
            try:
                await self._controller.set_light_effect(
                    circuit_objnam,
                    effect,
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {circuit_objnam} light effect"
                ) from exc

        self._last_error_code = None
        return ManualCommandReceipt(
            body_objnam=circuit_objnam,
            operation="light_effect",
            value=effect,
        )

    async def async_set_body_heat_source(
        self,
        body_objnam: str,
        heater_objnam: str,
    ) -> ManualCommandReceipt:
        """Select one explicitly allow-listed heat source for a Pool/Spa body."""

        self._require_body(body_objnam)

        if heater_objnam not in _ALLOWED_HEAT_SOURCE_IDS:
            raise ValueError(
                f"unsupported manual-control heat source: {heater_objnam}"
            )

        await self._require_available()

        async with self._command_lock:
            try:
                await self._controller.request_changes(
                    body_objnam,
                    {
                        HEATER_ATTR: heater_objnam,
                    },
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {body_objnam} heat source"
                ) from exc

        self._last_error_code = None

        return ManualCommandReceipt(
            body_objnam=body_objnam,
            operation="body_heat_source",
            value=heater_objnam,
        )

    async def async_set_intellichlor_output(
        self,
        body_objnam: str,
        percent: int,
    ) -> ManualCommandReceipt:
        """Set one body output on the commissioned CHR01 IntelliChlor."""

        self._require_body(body_objnam)
        if isinstance(percent, bool) or not isinstance(percent, int):
            raise ValueError("IntelliChlor output must be a whole percentage")
        if not 0 <= percent <= 100:
            raise ValueError("IntelliChlor output must be between 0 and 100")

        candidates = [
            item
            for item in self._model.get_by_type(CHEM_TYPE)
            if str(item.subtype or "").upper() == "ICHLOR"
        ]
        if (
            len(candidates) != 1
            or str(candidates[0].objnam) != _INTELLICHLOR_OBJNAM
        ):
            raise ManualIntelliCenterCommandError(
                "exactly one commissioned IntelliChlor CHR01 is required"
            )

        chlorinator = candidates[0]
        body_ids = tuple(str(chlorinator[BODY_ATTR] or "").split())
        if body_objnam not in body_ids[:2]:
            raise ManualIntelliCenterCommandError(
                f"IntelliChlor CHR01 is not associated with {body_objnam}"
            )
        output_index = body_ids.index(body_objnam)

        await self._require_available()

        async with self._command_lock:
            try:
                if output_index == 0:
                    await self._controller.set_chlorinator_output(
                        _INTELLICHLOR_OBJNAM,
                        percent,
                    )
                else:
                    primary = _percentage(chlorinator[PRIM_ATTR])
                    if primary is None:
                        raise ManualIntelliCenterCommandError(
                            "IntelliChlor Pool output is unavailable; "
                            "Spa output cannot be changed safely"
                        )
                    await self._controller.set_chlorinator_output(
                        _INTELLICHLOR_OBJNAM,
                        primary,
                        percent,
                    )
            except ManualIntelliCenterCommandError:
                raise
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {body_objnam} IntelliChlor output"
                ) from exc

        self._last_error_code = None
        return ManualCommandReceipt(
            body_objnam=body_objnam,
            operation="intellichlor_output",
            value=percent,
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


    async def async_set_pump_circuit_speed(
        self,
        pump_circuit_objnam: str,
        rpm: int | float,
    ) -> ManualCommandReceipt:
        """Set one explicitly allow-listed PMPCIRC RPM setpoint."""

        self._require_pump_circuit_id(pump_circuit_objnam)

        if isinstance(rpm, bool) or not isinstance(rpm, (int, float)):
            raise ValueError("pump RPM must be numeric")

        numeric = float(rpm)
        target = int(round(numeric))

        if numeric != float(target):
            raise ValueError("pump RPM must be a whole number")

        await self._require_available()

        minimum, maximum = self._pump_circuit_rpm_limits(
            pump_circuit_objnam
        )

        if not minimum <= target <= maximum:
            raise ValueError(
                f"pump RPM must be between {minimum} and {maximum}"
            )

        async with self._command_lock:
            try:
                await self._controller.request_changes(
                    pump_circuit_objnam,
                    {
                        SPEED_ATTR: str(target),
                    },
                )
            except Exception as exc:
                self._last_error_code = type(exc).__name__.upper()
                raise ManualIntelliCenterCommandError(
                    f"failed to set {pump_circuit_objnam} pump circuit speed"
                ) from exc

        self._last_error_code = None

        return ManualCommandReceipt(
            body_objnam=pump_circuit_objnam,
            operation="pump_circuit_speed",
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
                    "body_heat_source",
                    "intellichlor_output",
                    "circuit_active",
                    "light_effect",
                    "pump_circuit_speed",
                ],
                "allowed_body_ids": sorted(_ALLOWED_BODY_IDS),
                "allowed_circuit_ids": sorted(_ALLOWED_CIRCUIT_IDS),
                "allowed_pump_circuit_ids": sorted(
                    _ALLOWED_PUMP_CIRCUIT_IDS
                ),
                "pump_rpm_requires_native_limits": True,
                "pump_rpm_requires_explicit_rpm_mode": True,
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


    @staticmethod
    def _require_pump_circuit_id(pump_circuit_objnam: str) -> None:
        if pump_circuit_objnam not in _ALLOWED_PUMP_CIRCUIT_IDS:
            raise ValueError(
                "unsupported manual-control pump circuit: "
                f"{pump_circuit_objnam}"
            )

    @staticmethod
    def _coerce_positive_int(value: object) -> int | None:
        if isinstance(value, bool) or value is None:
            return None

        try:
            numeric = int(str(value))
        except (TypeError, ValueError):
            return None

        return numeric if numeric > 0 else None

    def _pump_circuit_rpm_limits(
        self,
        pump_circuit_objnam: str,
    ) -> tuple[int, int]:
        """Validate PMPCIRC identity/mode and return parent pump limits."""

        item = self._model[pump_circuit_objnam]

        if item is None or str(item.objtype).upper() != str(PMPCIRC_TYPE).upper():
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} is not a live PMPCIRC object"
            )

        mode = item[SELECT_ATTR]

        if mode is None or str(mode).upper() != _PUMP_RPM_MODE:
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} is not configured for RPM control"
            )

        parent_id = item[PARENT_ATTR]

        if parent_id is None or not str(parent_id).strip():
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} has no parent pump"
            )

        parent = self._model[str(parent_id)]

        if parent is None or str(parent.objtype).upper() != str(PUMP_TYPE).upper():
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} parent is not a live pump object"
            )

        minimum = self._coerce_positive_int(parent[MIN_ATTR])
        maximum = self._coerce_positive_int(parent[MAX_ATTR])

        if minimum is None or maximum is None:
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} parent pump native RPM limits "
                "are unavailable"
            )

        if minimum > maximum:
            raise ManualIntelliCenterCommandError(
                f"{pump_circuit_objnam} parent pump RPM limits are invalid"
            )

        return minimum, maximum

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
