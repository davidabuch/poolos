"""PoolOS-owned independent read-only IntelliCenter transport.

Only audited discovery, read, subscription, and keepalive protocol operations
cross this boundary. The general-purpose pyintellicenter controller remains a
private implementation detail and every equipment mutation is blocked centrally.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import asyncio
import contextlib
from datetime import UTC, datetime
from enum import Enum
import json
import math
from types import MappingProxyType
from typing import Any

from pyintellicenter import (
    BODY_TYPE,
    CIRCUIT_TYPE,
    GPM_ATTR,
    HEATER_ATTR,
    HTMODE_ATTR,
    ICBaseController,
    ICConnectionHandler,
    ICModelController,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    OBJTYP_ATTR,
    PARENT_ATTR,
    PUMP_STATUS_ON,
    PUMP_TYPE,
    PWR_ATTR,
    RPM_ATTR,
    SENSE_TYPE,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    SUBTYP_ATTR,
    PoolModel,
    PoolObject,
)
from pyintellicenter.attributes import ALL_ATTRIBUTES_BY_TYPE
from pyintellicenter.exceptions import ICConnectionError, ICTimeoutError

from poolos.intellicenter_readonly import (
    NativeBodyKind,
    NativeBodyState,
    NativeCircuitState,
    NativeIntelliCenterReadError,
    NativeIntelliCenterTransportSnapshot,
    NativePumpState,
    NativeRawAttribute,
    NativeRawObject,
    NativeRawScalar,
    NativeTemperatureKind,
    NativeTemperatureState,
)

ALLOWED_READ_ONLY_PROTOCOL_OPERATIONS = frozenset(
    {"GetParamList", "RequestParamList"}
)
DISCOVERED_OBJECT_TYPES = frozenset(
    {
        "BODY",
        "CHEM",
        "CIRCGROUP",
        "CIRCGRP",
        "CIRCUIT",
        "EXTINSTR",
        "FDR",
        "FEATR",
        "HEATER",
        "MODULE",
        "PANEL",
        "PERMIT",
        "PMPCIRC",
        "PRESS",
        "PUMP",
        "REMBTN",
        "REMOTE",
        "SCHED",
        "SENSE",
        "STATUS",
        "SYSTEM",
        "SYSTIM",
        "VALVE",
    }
)
_UNKNOWN_TYPE_DISCOVERY_ATTRIBUTES = frozenset(
    {SNAME_ATTR, PARENT_ATTR, STATUS_ATTR, SUBTYP_ATTR}
)
_RAW_TEXT_LIMIT = 256


class IndependentIntelliCenterTransportState(str, Enum):
    """Detailed lifecycle state for the independent shadow connection."""

    INITIALIZING = "INITIALIZING"
    CONNECTING = "CONNECTING"
    DISCOVERING = "DISCOVERING"
    AVAILABLE = "AVAILABLE"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    UNAVAILABLE = "UNAVAILABLE"


class ReadOnlyProtocolViolation(RuntimeError):
    """Raised before a disallowed protocol operation reaches the connection."""


class ReadOnlyProtocolGuard:
    """Central allowlist for all controller commands exposed to PoolOS."""

    def __init__(self) -> None:
        self._blocked_count = 0

    @property
    def blocked_count(self) -> int:
        return self._blocked_count

    def require_allowed(self, operation: str) -> None:
        if operation in ALLOWED_READ_ONLY_PROTOCOL_OPERATIONS:
            return
        self._blocked_count += 1
        raise ReadOnlyProtocolViolation(
            f"IntelliCenter protocol operation is not read-only: {operation}"
        )


class _DiscoveryPoolModel(PoolModel):
    """PoolModel variant that retains unknown identities instead of dropping them."""

    def __init__(self) -> None:
        self._discovery_attribute_map = {
            name: set(attributes)
            for name, attributes in ALL_ATTRIBUTES_BY_TYPE.items()
        }
        super().__init__(self._discovery_attribute_map)

    def add_object(self, objnam: str, params: dict[str, Any]) -> PoolObject | None:
        object_type = params.get(OBJTYP_ATTR)
        if isinstance(object_type, str) and object_type:
            self._discovery_attribute_map.setdefault(
                object_type,
                set(_UNKNOWN_TYPE_DISCOVERY_ATTRIBUTES),
            )
        return super().add_object(objnam, params)


class _ReadOnlyModelController(ICModelController):
    """Guarded controller whose mutating command channel is structurally closed."""

    def __init__(
        self,
        host: str,
        model: PoolModel,
        *,
        keepalive_interval: float,
        transport: str,
        guard: ReadOnlyProtocolGuard,
    ) -> None:
        super().__init__(
            host,
            model,
            keepalive_interval=keepalive_interval,
            transport=transport,
        )
        self._read_only_guard = guard

    async def send_cmd(
        self, cmd: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._read_only_guard.require_allowed(cmd)
        return await super().send_cmd(cmd, extra)

    async def request_changes(
        self, objnam: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        del objnam, changes
        self._read_only_guard.require_allowed("SETPARAMLIST")
        raise AssertionError("unreachable")

    async def _queue_property_change(
        self, objnam: str, changes: dict[str, str]
    ) -> dict[str, Any]:
        del objnam, changes
        self._read_only_guard.require_allowed("SETPARAMLIST")
        raise AssertionError("unreachable")

    async def refresh_body_metadata(
        self,
        objnam: str,
        *,
        applying_body_ids: set[str],
        generation_is_current: Callable[[], bool],
    ) -> None:
        """Refresh BODY state and heater metadata for one connection generation."""

        if not generation_is_current():
            return

        # First refresh the BODY itself. HEATER must come from this fresh
        # response rather than from the cached model because gas/solar source
        # selection can change while the body remains active.
        response = await self.send_cmd(
            "RequestParamList",
            {
                "objectList": [
                    {
                        "objnam": objnam,
                        "keys": [
                            LOTMP_ATTR,
                            HEATER_ATTR,
                            HTMODE_ATTR,
                            STATUS_ATTR,
                            LSTTMP_ATTR,
                        ],
                    }
                ]
            },
        )

        # The connection may have changed while the request was in flight.
        # Never apply an old-generation response to the current model.
        if not generation_is_current():
            return

        object_list = response.get("objectList")
        if not isinstance(object_list, list):
            return

        # Mark only the synchronous application of our own BODY response.
        # There is no await inside this section, so an unrelated live update
        # cannot be accidentally suppressed while network I/O is in flight.
        applying_body_ids.add(objnam)
        try:
            self._apply_updates(object_list)
        finally:
            applying_body_ids.discard(objnam)

        if not generation_is_current():
            return

        body = self._model[objnam]
        if body is None:
            return

        selected_heater = body[HEATER_ATTR]
        if selected_heater in (None, ""):
            return

        if not generation_is_current():
            return

        # Refresh metadata for the heater identified by the freshly read BODY.
        response = await self.send_cmd(
            "RequestParamList",
            {
                "objectList": [
                    {
                        "objnam": str(selected_heater),
                        "keys": [
                            OBJTYP_ATTR,
                            SUBTYP_ATTR,
                            SNAME_ATTR,
                        ],
                    }
                ]
            },
        )

        # A reconnect can also occur during the second request. The heater
        # metadata response belongs to the same generation as its BODY request.
        if not generation_is_current():
            return

        object_list = response.get("objectList")
        if isinstance(object_list, list):
            self._apply_updates(object_list)


class _ReadOnlyConnectionHandler(ICConnectionHandler):
    """Forward pyintellicenter lifecycle callbacks without exposing its controller."""

    def __init__(
        self,
        owner: IndependentIntelliCenterReadOnlyTransport,
        controller: _ReadOnlyModelController,
        *,
        reconnect_delay: int,
    ) -> None:
        super().__init__(controller, time_between_reconnects=reconnect_delay)
        self._owner = owner

    def on_started(self, controller: ICBaseController) -> None:
        del controller
        self._owner._on_connected(reconnected=False)

    def on_reconnected(self, controller: ICBaseController) -> None:
        del controller
        self._owner._on_connected(reconnected=True)

    def on_disconnected(
        self, controller: ICBaseController, exc: Exception | None
    ) -> None:
        del controller
        self._owner._on_disconnected(exc)

    def on_retrying(self, delay: int) -> None:
        self._owner._on_retrying(delay)

    def on_updated(
        self,
        controller: ICModelController,
        updates: dict[str, dict[str, Any]],
    ) -> None:
        del controller
        self._owner._on_updated(updates)


class IndependentIntelliCenterReadOnlyTransport:
    """Own one independent, narrow, shadow-only IntelliCenter connection."""

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
            raise ValueError("independent IntelliCenter host must not be blank")
        if transport not in {"tcp", "websocket"}:
            raise ValueError("independent IntelliCenter transport must be tcp or websocket")
        if keepalive_interval <= 0 or reconnect_delay <= 0:
            raise ValueError("independent IntelliCenter retry intervals must be positive")

        self._host = normalized_host
        self._transport_name = transport
        self._guard = ReadOnlyProtocolGuard()
        self._model = _DiscoveryPoolModel()
        self._controller = _ReadOnlyModelController(
            normalized_host,
            self._model,
            keepalive_interval=keepalive_interval,
            transport=transport,
            guard=self._guard,
        )
        self._handler = _ReadOnlyConnectionHandler(
            self,
            self._controller,
            reconnect_delay=reconnect_delay,
        )
        self._state = IndependentIntelliCenterTransportState.INITIALIZING
        self._latest_snapshot: NativeIntelliCenterTransportSnapshot | None = None
        self._last_successful_connection: datetime | None = None
        self._last_successful_discovery: datetime | None = None
        self._last_native_update: datetime | None = None
        self._last_error_code: str | None = None
        self._reconnect_count = 0
        self._discovery_generation = 0
        self._running = False
        self._body_metadata_refresh_pending: set[str] = set()
        self._body_metadata_refresh_dirty: set[str] = set()
        self._body_metadata_refresh_applying: set[str] = set()
        self._body_metadata_refresh_tasks: set[asyncio.Task[None]] = set()
        self._connection_reconciliation_tasks: set[asyncio.Task[None]] = set()

    @property
    def state(self) -> IndependentIntelliCenterTransportState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state is IndependentIntelliCenterTransportState.AVAILABLE

    @property
    def latest_snapshot(self) -> NativeIntelliCenterTransportSnapshot | None:
        return self._latest_snapshot

    async def async_start(self) -> None:
        """Start independent discovery without propagating failure to HA observations."""

        if self._running:
            return
        self._running = True
        self._state = IndependentIntelliCenterTransportState.CONNECTING
        try:
            await self._handler.start()
        except Exception as exc:
            self._last_error_code = type(exc).__name__.upper()
            self._state = IndependentIntelliCenterTransportState.RECONNECTING

    async def async_stop(self) -> None:
        """Stop reconnect tasks and close the private connection."""

        if not self._running:
            self._state = IndependentIntelliCenterTransportState.UNAVAILABLE
            return
        self._running = False
        self._handler.stop()

        reconciliation_tasks = tuple(self._connection_reconciliation_tasks)
        for task in reconciliation_tasks:
            task.cancel()
        if reconciliation_tasks:
            await asyncio.gather(*reconciliation_tasks, return_exceptions=True)

        refresh_tasks = tuple(self._body_metadata_refresh_tasks)
        for task in refresh_tasks:
            task.cancel()
        if refresh_tasks:
            await asyncio.gather(*refresh_tasks, return_exceptions=True)

        self._connection_reconciliation_tasks.clear()
        self._body_metadata_refresh_tasks.clear()
        self._body_metadata_refresh_pending.clear()
        self._body_metadata_refresh_dirty.clear()
        self._body_metadata_refresh_applying.clear()

        with contextlib.suppress(Exception):
            await self._controller.stop()
        self._state = IndependentIntelliCenterTransportState.UNAVAILABLE

    def read_snapshot(self) -> NativeIntelliCenterTransportSnapshot:
        """Return the latest immutable snapshot through the existing read contract."""

        if not self.connected or self._latest_snapshot is None:
            raise NativeIntelliCenterReadError("INDEPENDENT_TRANSPORT_UNAVAILABLE")
        return self._latest_snapshot

    def diagnostics(self, *, generated_at: datetime) -> Mapping[str, Any]:
        """Return bounded commissioning diagnostics with explicit time input."""

        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("diagnostic generated_at must be timezone-aware")
        snapshot = self._latest_snapshot
        snapshot_age_seconds = (
            None
            if snapshot is None
            else max(0.0, (generated_at - snapshot.observed_at).total_seconds())
        )
        raw = (
            {
                "total_native_object_count": 0,
                "count_by_native_object_type": {},
                "raw_inventory": [],
                "inventory_truncated": False,
            }
            if snapshot is None
            else dict(snapshot.raw_inventory_diagnostics())
        )
        unknown_count = 0
        if snapshot is not None:
            unknown_count = sum(
                item.object_type not in DISCOVERED_OBJECT_TYPES
                for item in snapshot.raw_inventory
            )
        system_info = self._controller.system_info
        return MappingProxyType(
            {
                "state": self._state.value,
                "selected_transport": self._transport_name,
                "connected": self.connected,
                "controller_name": getattr(system_info, "prop_name", None),
                "software_version": getattr(system_info, "sw_version", None),
                "last_successful_connection": _iso(self._last_successful_connection),
                "last_successful_discovery": _iso(self._last_successful_discovery),
                "last_native_message_or_update": _iso(self._last_native_update),
                "snapshot_timestamp": (
                    None if snapshot is None else snapshot.observed_at.isoformat()
                ),
                "snapshot_age_seconds": snapshot_age_seconds,
                "reconnect_count": self._reconnect_count,
                "discovery_generation": self._discovery_generation,
                "unknown_object_type_count": unknown_count,
                "last_error_code": self._last_error_code,
                "allowed_protocol_operations": sorted(
                    ALLOWED_READ_ONLY_PROTOCOL_OPERATIONS
                ),
                "blocked_disallowed_command_count": self._guard.blocked_count,
                "authority": "none",
                "command_delivery_enabled": False,
                "physical_delivery_enabled": False,
                "read_only_safety_mode": True,
                **raw,
            }
        )

    def _on_connected(self, *, reconnected: bool) -> None:
        observed_at = datetime.now(UTC)
        self._state = IndependentIntelliCenterTransportState.DISCOVERING
        self._last_successful_connection = observed_at
        self._last_successful_discovery = observed_at
        self._last_native_update = observed_at
        self._last_error_code = None
        self._discovery_generation += 1
        if reconnected:
            self._reconnect_count += 1
        self._latest_snapshot = self._copy_snapshot(
            observed_at=observed_at,
            connected=True,
        )
        self._state = IndependentIntelliCenterTransportState.AVAILABLE
        self._schedule_connection_reconciliation(
            discovery_generation=self._discovery_generation,
        )

    def _on_disconnected(self, exc: Exception | None) -> None:
        observed_at = datetime.now(UTC)
        self._last_error_code = None if exc is None else type(exc).__name__.upper()
        self._latest_snapshot = self._copy_snapshot(
            observed_at=observed_at,
            connected=False,
        )
        self._state = IndependentIntelliCenterTransportState.DISCONNECTED

    def _on_retrying(self, delay: int) -> None:
        del delay
        self._state = IndependentIntelliCenterTransportState.RECONNECTING

    def _on_updated(self, updates: dict[str, dict[str, Any]]) -> None:
        # Connection lifecycle callbacks exclusively own transport availability.
        # A model callback can arrive while start/reconnect is still in progress,
        # or late while an old connection is being torn down. Such callbacks may
        # have updated the controller model, but they must not publish that model
        # as authoritative or resurrect a non-AVAILABLE transport.
        if (
            not self._running
            or self._state is not IndependentIntelliCenterTransportState.AVAILABLE
        ):
            return

        self._schedule_body_metadata_refreshes(updates)

        observed_at = datetime.now(UTC)
        self._last_native_update = observed_at
        self._latest_snapshot = self._copy_snapshot(
            observed_at=observed_at,
            connected=True,
        )

    def _refresh_generation_is_current(
        self,
        discovery_generation: int,
    ) -> bool:
        """Return whether read work still belongs to the authoritative connection."""

        return (
            self._running
            and discovery_generation == self._discovery_generation
            and self._state is IndependentIntelliCenterTransportState.AVAILABLE
        )

    def _schedule_connection_reconciliation(
        self,
        *,
        discovery_generation: int,
    ) -> None:
        """Reconcile all BODY metadata after a successful connection."""

        if not self._refresh_generation_is_current(discovery_generation):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        task = loop.create_task(
            self._async_reconcile_bodies_after_connection(discovery_generation)
        )
        self._connection_reconciliation_tasks.add(task)
        task.add_done_callback(self._on_connection_reconciliation_done)

    async def _async_reconcile_bodies_after_connection(
        self,
        discovery_generation: int,
    ) -> None:
        # A previous-generation BODY worker can still be unwinding from failed
        # network I/O. Let its cleanup finish before creating new work that uses
        # the same per-BODY pending/dirty bookkeeping.
        previous_refresh_tasks = tuple(self._body_metadata_refresh_tasks)
        if previous_refresh_tasks:
            await asyncio.gather(
                *previous_refresh_tasks,
                return_exceptions=True,
            )

        if not self._refresh_generation_is_current(discovery_generation):
            return

        updates = {
            str(body.objnam): {STATUS_ATTR: body[STATUS_ATTR]}
            for body in self._model.get_by_type(BODY_TYPE)
        }
        self._schedule_body_metadata_refreshes(
            updates,
            discovery_generation=discovery_generation,
        )

    def _on_connection_reconciliation_done(
        self,
        task: asyncio.Task[None],
    ) -> None:
        self._connection_reconciliation_tasks.discard(task)
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            task.result()

    def _schedule_body_metadata_refreshes(
        self,
        updates: dict[str, dict[str, Any]],
        *,
        discovery_generation: int | None = None,
    ) -> None:
        if not self._running:
            return

        generation = (
            self._discovery_generation
            if discovery_generation is None
            else discovery_generation
        )
        if not self._refresh_generation_is_current(generation):
            return

        trigger_attributes = {
            STATUS_ATTR,
            HTMODE_ATTR,
            HEATER_ATTR,
            LSTTMP_ATTR,
        }

        for objnam, changed in updates.items():
            item = self._model[objnam]
            if item is None or str(item.objtype) != BODY_TYPE:
                continue

            # Ignore the BODY callback produced while PoolOS is applying its
            # own RequestParamList response.  An unsolicited IntelliCenter
            # update may legitimately contain LOTMP plus HEATER/HTMODE, and
            # must still participate in refresh/rerun handling.
            if objnam in self._body_metadata_refresh_applying:
                continue

            if not trigger_attributes.intersection(changed):
                continue

            # If another real BODY update arrives while the request is in flight,
            # remember it.  The worker will perform exactly one additional pass
            # using the newest state rather than silently losing the transition.
            if objnam in self._body_metadata_refresh_pending:
                self._body_metadata_refresh_dirty.add(objnam)
                continue

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                continue

            self._body_metadata_refresh_pending.add(objnam)
            task = loop.create_task(
                self._async_refresh_body_metadata(
                    objnam,
                    discovery_generation=generation,
                )
            )
            self._body_metadata_refresh_tasks.add(task)
            task.add_done_callback(self._on_body_metadata_refresh_done)

    async def _async_refresh_body_metadata(
        self,
        objnam: str,
        *,
        discovery_generation: int,
    ) -> None:
        try:
            while self._refresh_generation_is_current(discovery_generation):
                self._body_metadata_refresh_dirty.discard(objnam)

                refresh_succeeded = False
                for attempt in range(2):
                    try:
                        await self._controller.refresh_body_metadata(
                            objnam,
                            applying_body_ids=self._body_metadata_refresh_applying,
                            generation_is_current=lambda: self._refresh_generation_is_current(
                                discovery_generation
                            ),
                        )
                    except Exception as exc:
                        self._last_error_code = type(exc).__name__.upper()

                        is_transient = isinstance(
                            exc,
                            (ICConnectionError, ICTimeoutError),
                        )
                        if (
                            not is_transient
                            or attempt == 1
                            or not self._refresh_generation_is_current(
                                discovery_generation
                            )
                        ):
                            return

                        # Retry exactly once only for a recognized transient
                        # pyintellicenter connection/request timeout while this
                        # connection generation remains authoritative.
                        await asyncio.sleep(0)
                        continue

                    refresh_succeeded = True
                    break

                if not refresh_succeeded:
                    break

                if not self._refresh_generation_is_current(discovery_generation):
                    break

                if objnam not in self._body_metadata_refresh_dirty:
                    break
        finally:
            self._body_metadata_refresh_pending.discard(objnam)
            self._body_metadata_refresh_dirty.discard(objnam)

    def _on_body_metadata_refresh_done(
        self,
        task: asyncio.Task[None],
    ) -> None:
        self._body_metadata_refresh_tasks.discard(task)
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            task.result()

    def _copy_snapshot(
        self, *, observed_at: datetime, connected: bool
    ) -> NativeIntelliCenterTransportSnapshot:
        raw = tuple(_copy_raw_object(item, observed_at) for item in self._model)
        return NativeIntelliCenterTransportSnapshot(
            source_id="poolos.independent_intellicenter",
            observed_at=observed_at,
            connected=connected,
            temperature_unit=(
                "°C"
                if bool(getattr(self._controller.system_info, "uses_metric", False))
                else "°F"
            ),
            bodies=tuple(
                item
                for obj in self._model.get_by_type(BODY_TYPE)
                if (item := _copy_body(obj, self._controller)) is not None
            ),
            pumps=tuple(
                item
                for obj in self._model.get_by_type(PUMP_TYPE)
                if (item := _copy_pump(obj)) is not None
            ),
            temperatures=tuple(
                _copy_temperature(obj)
                for obj in self._model.get_by_type(SENSE_TYPE)
            ),
            circuits=tuple(
                item
                for obj in self._model.get_by_type(CIRCUIT_TYPE)
                if (item := _copy_circuit(obj)) is not None
            ),
            raw_inventory=raw,
        )


def _copy_raw_object(item: PoolObject, observed_at: datetime) -> NativeRawObject:
    properties = dict(item.properties)
    return NativeRawObject(
        native_id=str(item.objnam),
        object_type=str(item.objtype),
        subtype=None if item.subtype is None else str(item.subtype),
        name=None if item.sname is None else str(item.sname),
        parent_id=_optional_text(properties.get(PARENT_ATTR)),
        observed_at=observed_at,
        attributes=tuple(
            NativeRawAttribute(str(name), _raw_scalar(value))
            for name, value in sorted(properties.items(), key=lambda pair: str(pair[0]))
        ),
    )


def _copy_body(
    item: PoolObject, controller: _ReadOnlyModelController
) -> NativeBodyState | None:
    status = item[STATUS_ATTR]
    heat_mode = item[HTMODE_ATTR]
    if status is None or heat_mode is None:
        return None
    selected_heater_id = _optional_text(item[HEATER_ATTR])
    selected_heater = (
        None if selected_heater_id is None else controller.model[selected_heater_id]
    )
    return NativeBodyState(
        native_id=str(item.objnam),
        name=str(item.sname or item.objnam),
        kind=_body_kind(item),
        active=str(status).upper() != STATUS_OFF,
        heating_active=controller.is_body_heating(item.objnam),
        current_temperature=_number(item[LSTTMP_ATTR]),
        target_temperature=_number(item[LOTMP_ATTR]),
        active_heat_source=_heater_source(selected_heater),
        selected_heat_mode=_heater_mode(selected_heater),
        raw_heater_id=selected_heater_id,
        raw_htmode=_optional_text(heat_mode),
    )


def _copy_pump(item: PoolObject) -> NativePumpState | None:
    status = item[STATUS_ATTR]
    if status is None:
        return None
    return NativePumpState(
        native_id=str(item.objnam),
        name=str(item.sname or item.objnam),
        running=str(status).upper() == str(PUMP_STATUS_ON).upper(),
        rpm=_number(item[RPM_ATTR]),
        gpm=_number(item[GPM_ATTR]),
        power_watts=_number(item[PWR_ATTR]),
    )


def _copy_temperature(item: PoolObject) -> NativeTemperatureState:
    # pyintellicenter documents SOURCE as the calibrated reading and SUBTYP as
    # exactly AIR, SOLAR, or POOL (water).  Names and parents are retained in raw
    # inventory but never used to guess probe semantics.
    kind = {
        "AIR": NativeTemperatureKind.AIR,
        "SOLAR": NativeTemperatureKind.SOLAR,
        "POOL": NativeTemperatureKind.WATER,
    }.get(str(item.subtype or "").strip().upper(), NativeTemperatureKind.UNKNOWN)
    return NativeTemperatureState(
        native_id=str(item.objnam),
        name=str(item.sname or item.objnam),
        kind=kind,
        temperature=_number(item[SOURCE_ATTR]),
    )


def _copy_circuit(item: PoolObject) -> NativeCircuitState | None:
    status = item[STATUS_ATTR]
    if status is None:
        return None
    return NativeCircuitState(
        native_id=str(item.objnam),
        name=str(item.sname or item.objnam),
        active=str(status).upper() != STATUS_OFF,
        use=_optional_text(item["USE"]),
        subtype=_optional_text(item.subtype),
    )


def _body_kind(item: PoolObject) -> NativeBodyKind:
    text = " ".join(
        str(value).casefold()
        for value in (item.objnam, item.sname, item.subtype)
        if value is not None
    )
    if "spa" in text:
        return NativeBodyKind.SPA
    if "pool" in text:
        return NativeBodyKind.POOL
    return NativeBodyKind.UNKNOWN


def _heater_source(item: PoolObject | None) -> str | None:
    if item is None:
        return None

    subtype = (
        None
        if item.subtype is None
        else str(item.subtype).strip().upper()
    )
    direct = {
        "HEATER": "gas",
        "GAS": "gas",
        "SOLAR": "solar",
        "ULTRA": "heat_pump",
        "HCOMBO": "hybrid",
    }.get(subtype)
    if direct is not None:
        return direct

    # Fall back only to explicit descriptive metadata. Never infer a source
    # from BODY HTMODE or from an opaque heater object ID.
    text = " ".join(
        str(value)
        for value in (item.subtype, item.sname)
        if value not in (None, "")
    ).casefold().replace("_", " ").replace("-", " ")

    if "solar preferred" in text:
        return None
    if "solar" in text:
        return "solar"
    if "gas" in text or "mastertemp" in text:
        return "gas"
    if "heat pump" in text or "ultratemp" in text:
        return "heat_pump"
    if "hybrid" in text:
        return "hybrid"
    return None


def _heater_mode(item: PoolObject | None) -> str | None:
    if item is None or item.subtype is None:
        return None
    subtype = str(item.subtype).strip().upper()
    return {
        "HEATER": "gas",
        "GAS": "gas",
        "SOLAR": "solar",
        "SOLARPREF": "solar_preferred",
        "ULTRA": "heat_pump",
        "HCOMBO": "hybrid",
    }.get(subtype)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)[:_RAW_TEXT_LIMIT]


def _raw_scalar(value: Any) -> NativeRawScalar:
    if value is None or isinstance(value, (str, bool, int)):
        return value if not isinstance(value, str) else value[:_RAW_TEXT_LIMIT]
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))[
            :_RAW_TEXT_LIMIT
        ]
    except (TypeError, ValueError):
        return str(value)[:_RAW_TEXT_LIMIT]


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


__all__ = [
    "ALLOWED_READ_ONLY_PROTOCOL_OPERATIONS",
    "DISCOVERED_OBJECT_TYPES",
    "IndependentIntelliCenterReadOnlyTransport",
    "IndependentIntelliCenterTransportState",
    "ReadOnlyProtocolGuard",
    "ReadOnlyProtocolViolation",
]
