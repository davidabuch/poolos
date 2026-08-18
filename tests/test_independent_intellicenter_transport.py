"""Independent IntelliCenter transport and raw discovery contracts for 12.0C1."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from poolos.intellicenter_readonly import (
    NativeIntelliCenterReadAdapter,
    NativeIntelliCenterReadError,
)
from poolos.observation_parity import ObservationParityEngine

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "independent_intellicenter.py"
NOW = datetime(2026, 8, 11, 18, 0, tzinfo=UTC)


class FakePoolObject:
    def __init__(self, objnam: str, params: dict[str, Any]) -> None:
        self.objnam = objnam
        self.objtype = str(params["OBJTYP"])
        self.subtype = params.get("SUBTYP")
        self.properties = {
            key: value
            for key, value in params.items()
            if key not in {"OBJTYP", "SUBTYP"}
        }

    @property
    def sname(self) -> str | None:
        value = self.properties.get("SNAME")
        return None if value is None else str(value)

    def __getitem__(self, key: str) -> Any:
        return self.properties.get(key)


class FakePoolModel:
    def __init__(self, attribute_map: dict[str, set[str]]) -> None:
        self.attribute_map = attribute_map
        self.objects: dict[str, FakePoolObject] = {}

    def __iter__(self):
        return iter(self.objects.values())

    def __getitem__(self, key: str) -> FakePoolObject | None:
        return self.objects.get(key)

    def add_object(self, objnam: str, params: dict[str, Any]) -> FakePoolObject | None:
        if params.get("OBJTYP") not in self.attribute_map:
            return None
        item = FakePoolObject(objnam, dict(params))
        self.objects[objnam] = item
        return item

    def get_by_type(self, object_type: str) -> list[FakePoolObject]:
        return [item for item in self if item.objtype == object_type]


class FakeModelController:
    initial_objects: tuple[tuple[str, dict[str, Any]], ...] = ()
    start_error: Exception | None = None

    def __init__(
        self,
        host: str,
        model: FakePoolModel,
        *,
        keepalive_interval: float,
        transport: str,
    ) -> None:
        self.host = host
        self.model = model
        self.keepalive_interval = keepalive_interval
        self.transport = transport
        self.system_info = SimpleNamespace(
            prop_name="Test IntelliCenter",
            sw_version="3.042",
            uses_metric=False,
        )
        self.sent_operations: list[str] = []
        self.sent_requests: list[tuple[str, dict[str, Any] | None]] = []
        self.command_responses: dict[str, dict[str, Any]] = {}
        self.command_response_queues: dict[str, list[dict[str, Any]]] = {}
        self._updated_callback = None
        self._model = model
        self.stopped = False

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        for objnam, params in self.initial_objects:
            self.model.add_object(objnam, dict(params))

    async def stop(self) -> None:
        self.stopped = True

    async def send_cmd(
        self, cmd: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.sent_operations.append(cmd)
        self.sent_requests.append((cmd, extra))

        queue = self.command_response_queues.get(cmd)
        if queue:
            return queue.pop(0)

        return self.command_responses.get(cmd, {"objectList": []})

    def set_updated_callback(self, callback) -> None:
        self._updated_callback = callback

    def _apply_updates(
        self,
        changes_as_list: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        updates: dict[str, dict[str, Any]] = {}

        for entry in changes_as_list:
            objnam = str(entry["objnam"])
            params = dict(entry.get("params") or {})
            item = self.model[objnam]
            if item is None:
                continue
            item.properties.update(params)
            updates[objnam] = params

        if updates and self._updated_callback is not None:
            self._updated_callback(self, updates)

        return updates

    async def request_changes(
        self, objnam: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        del objnam, changes
        self.sent_operations.append("SETPARAMLIST")
        return {}

    async def _queue_property_change(
        self, objnam: str, changes: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request_changes(objnam, changes)

    def is_body_heating(self, objnam: str) -> bool:
        item = self.model[objnam]
        return item is not None and item["HTMODE"] not in (None, "0", 0)


class FakeConnectionHandler:
    def __init__(
        self, controller: FakeModelController, *, time_between_reconnects: int
    ) -> None:
        self._controller = controller
        self.time_between_reconnects = time_between_reconnects
        self.stopped = False
        controller.set_updated_callback(self.on_updated)

    async def start(self) -> None:
        await self._controller.start()
        self.on_started(self._controller)

    def stop(self) -> None:
        self.stopped = True


def _objects() -> tuple[tuple[str, dict[str, Any]], ...]:
    identities = (
        ("B1101", "BODY"),
        ("C0001", "CIRCUIT"),
        ("G0001", "CIRCGRP"),
        ("H0001", "HEATER"),
        ("P0001", "PUMP"),
        ("PC001", "PMPCIRC"),
        ("S0001", "SENSE"),
        ("CH001", "CHEM"),
        ("SC001", "SCHED"),
        ("EX001", "EXTINSTR"),
        ("SYS01", "SYSTEM"),
        ("X0001", "FUTURE_TYPE"),
    )
    result: list[tuple[str, dict[str, Any]]] = []
    for objnam, object_type in identities:
        params: dict[str, Any] = {
            "OBJTYP": object_type,
            "SUBTYP": "UNKNOWN",
            "SNAME": objnam,
            "PARENT": "SYS01",
        }
        if object_type == "BODY":
            params.update(
                {
                    "SNAME": "Pool",
                    "STATUS": "ON",
                    "HTMODE": "1",
                    "LSTTMP": "82",
                    "LOTMP": "86",
                    "HEATER": "H0001",
                }
            )
        elif object_type == "HEATER":
            params.update({"SUBTYP": "HEATER", "SNAME": "Gas Heater"})
        elif object_type == "PUMP":
            params.update(
                {"SNAME": "Filter Pump", "STATUS": "10", "RPM": 2200, "GPM": 42, "PWR": 1200}
            )
        elif object_type == "SENSE":
            params.update({"SUBTYP": "AIR", "SNAME": "Air", "SOURCE": 78})
        elif object_type == "CIRCUIT":
            params.update({"SNAME": "Pool", "STATUS": "ON", "USE": "POOL"})
        result.append((objnam, params))
    return tuple(result)


def _load_module(monkeypatch: pytest.MonkeyPatch):
    pyic = ModuleType("pyintellicenter")
    constants = {
        "BODY_TYPE": "BODY",
        "CIRCUIT_TYPE": "CIRCUIT",
        "GPM_ATTR": "GPM",
        "HEATER_ATTR": "HEATER",
        "HEATER_TYPE": "HEATER",
        "HTMODE_ATTR": "HTMODE",
        "LOTMP_ATTR": "LOTMP",
        "LSTTMP_ATTR": "LSTTMP",
        "OBJTYP_ATTR": "OBJTYP",
        "PARENT_ATTR": "PARENT",
        "PMPCIRC_TYPE": "PMPCIRC",
        "PUMP_STATUS_ON": "10",
        "PUMP_TYPE": "PUMP",
        "PWR_ATTR": "PWR",
        "RPM_ATTR": "RPM",
        "SENSE_TYPE": "SENSE",
        "SNAME_ATTR": "SNAME",
        "SOURCE_ATTR": "SOURCE",
        "STATUS_ATTR": "STATUS",
        "STATUS_OFF": "OFF",
        "SUBTYP_ATTR": "SUBTYP",
    }
    for name, value in constants.items():
        setattr(pyic, name, value)
    pyic.ICBaseController = FakeModelController
    pyic.ICConnectionHandler = FakeConnectionHandler
    pyic.ICModelController = FakeModelController
    pyic.PoolModel = FakePoolModel
    pyic.PoolObject = FakePoolObject
    attributes = ModuleType("pyintellicenter.attributes")
    attributes.ALL_ATTRIBUTES_BY_TYPE = {
        str(params["OBJTYP"]): {"SNAME", "PARENT", "SUBTYP", "STATUS"}
        for _, params in _objects()
        if params["OBJTYP"] != "FUTURE_TYPE"
    }
    monkeypatch.setitem(sys.modules, "pyintellicenter", pyic)
    monkeypatch.setitem(sys.modules, "pyintellicenter.attributes", attributes)
    FakeModelController.initial_objects = _objects()
    FakeModelController.start_error = None

    spec = importlib.util.spec_from_file_location(
        "poolos_test_independent_intellicenter", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_independent_construction_discovery_and_unknown_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")

    asyncio.run(transport.async_start())
    snapshot = transport.read_snapshot()
    object_types = {item.object_type for item in snapshot.raw_inventory}

    assert transport.connected is True
    assert len(snapshot.raw_inventory) == 12
    assert {
        "BODY",
        "CIRCUIT",
        "CIRCGRP",
        "HEATER",
        "PUMP",
        "PMPCIRC",
        "SENSE",
        "CHEM",
        "SCHED",
        "EXTINSTR",
        "SYSTEM",
        "FUTURE_TYPE",
    } == object_types
    assert "runtime_data" not in MODULE_PATH.read_text(encoding="utf-8")


def test_snapshot_is_defensive_and_feeds_existing_normalization_and_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())
    snapshot = transport.read_snapshot()
    canonical = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot, generated_at=snapshot.observed_at
    )
    report = ObservationParityEngine().compare(
        canonical.observations,
        canonical.observations,
        generated_at=snapshot.observed_at,
        ha_source_available=True,
        native_source_available=True,
    )

    transport._controller.model["B1101"].properties["LSTTMP"] = "99"

    assert snapshot.bodies[0].current_temperature == 82.0
    assert {item.observation_id for item in canonical.observations} >= {
        "pool.active",
        "pool.temperature",
        "pump.rpm",
        "air.temperature",
        "pool.command_active",
    }
    assert report.parity_ratio == 1.0


def test_sense_mapping_uses_documented_subtype_and_calibrated_source_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = (
        (
            "S-AIR",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "AIR",
                "SNAME": "Outdoor",
                "PARENT": "SYS01",
                "SOURCE": 78,
                "PROBE": 77,
                "CALIB": 1,
            },
        ),
        (
            "S-WATER",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "POOL",
                "SNAME": "Water",
                "PARENT": "SYS01",
                "SOURCE": 95,
            },
        ),
        (
            "S-UNKNOWN",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "OTHER",
                "SNAME": "Air Sensor Name Must Not Guess",
                "PARENT": "SYS01",
                "SOURCE": 88,
            },
        ),
    )
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())

    snapshot = transport.read_snapshot()
    temperatures = {item.native_id: item for item in snapshot.temperatures}
    canonical = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot, generated_at=snapshot.observed_at
    )
    values = {item.observation_id: item.value for item in canonical.observations}

    assert temperatures["S-AIR"].kind.value == "air"
    assert temperatures["S-WATER"].kind.value == "water"
    assert temperatures["S-UNKNOWN"].kind.value == "unknown"
    assert values["air.temperature"] == 78.0
    assert values["water.temperature"] == 95.0
    assert 88 not in values.values()
    unknown_raw = next(
        item for item in snapshot.raw_inventory if item.native_id == "S-UNKNOWN"
    )
    assert unknown_raw.subtype == "OTHER"
    assert dict((item.name, item.value) for item in unknown_raw.attributes)["SOURCE"] == 88


def test_disconnect_reconnect_and_clean_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())

    transport._on_disconnected(ConnectionError("lost"))
    assert transport.state.value == "DISCONNECTED"
    with pytest.raises(NativeIntelliCenterReadError):
        transport.read_snapshot()

    transport._on_retrying(30)
    assert transport.state.value == "RECONNECTING"
    transport._on_connected(reconnected=True)
    assert transport.state.value == "AVAILABLE"
    assert transport.diagnostics(generated_at=datetime.now(UTC))["reconnect_count"] == 1

    asyncio.run(transport.async_stop())
    assert transport.state.value == "UNAVAILABLE"
    assert transport._controller.stopped is True


def test_initial_connection_failure_is_isolated_as_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.start_error = ConnectionError("unavailable")
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")

    asyncio.run(transport.async_start())

    assert transport.state.value == "RECONNECTING"
    assert transport.latest_snapshot is None
    assert transport.diagnostics(generated_at=NOW)["last_error_code"] == "CONNECTIONERROR"
    with pytest.raises(NativeIntelliCenterReadError):
        transport.read_snapshot()


def test_read_only_guard_blocks_mutation_and_public_surface_exposes_no_controller_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())

    asyncio.run(transport._controller.send_cmd("GetParamList"))
    with pytest.raises(module.ReadOnlyProtocolViolation):
        asyncio.run(
            transport._controller.request_changes("C0001", {"STATUS": "OFF"})
        )
    with pytest.raises(module.ReadOnlyProtocolViolation):
        asyncio.run(transport._controller.send_cmd("SetLightEffect"))

    public = {name for name in dir(transport) if not name.startswith("_")}
    assert public == {
        "async_start",
        "async_stop",
        "connected",
        "diagnostics",
        "latest_snapshot",
        "read_snapshot",
        "state",
    }
    assert transport._controller.sent_operations == ["GetParamList"]
    assert transport.diagnostics(generated_at=datetime.now(UTC))[
        "blocked_disallowed_command_count"
    ] == 2


def test_diagnostics_are_bounded_recorder_safe_and_explicitly_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10", transport="websocket"
    )
    asyncio.run(transport.async_start())
    for index in range(60):
        transport._controller.model.add_object(
            f"U{index:03d}",
            {
                "OBJTYP": "FUTURE_TYPE",
                "SUBTYP": "UNEXPECTED",
                "SNAME": "x" * 100,
                "PARENT": "SYS01",
            },
        )
    transport._on_updated({})

    diagnostics = dict(transport.diagnostics(generated_at=datetime.now(UTC)))

    assert diagnostics["selected_transport"] == "websocket"
    assert diagnostics["total_native_object_count"] == 72
    assert diagnostics["unknown_object_type_count"] == 61
    assert diagnostics["inventory_truncated"] is True
    assert len(diagnostics["raw_inventory"]) == 20
    assert diagnostics["authority"] == "none"
    assert diagnostics["command_delivery_enabled"] is False
    assert diagnostics["physical_delivery_enabled"] is False
    assert diagnostics["read_only_safety_mode"] is True
    assert len(json.dumps(diagnostics).encode("utf-8")) < 8_000


def test_production_path_has_no_ha_control_or_direct_socket_write() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    coordinator = (MODULE_PATH.parent / "coordinator.py").read_text(encoding="utf-8")
    lifecycle = (MODULE_PATH.parent / "__init__.py").read_text(encoding="utf-8")

    for prohibited in (
        "hass.services",
        "async_call",
        "turn_on",
        "turn_off",
        "set_temperature",
        "set_speed",
        "set_circuit_state",
        "set_light_effect",
        "write_command",
        "send_command",
        ".send(",
        ".write(",
    ):
        assert prohibited not in source

    assert "allowed_read_only_protocol_operations" in source
    assert '{"getparamlist", "requestparamlist"}' in source
    assert 'require_allowed("setparamlist")' in source
    assert 'async_entries("intellicenter")' not in coordinator
    assert "async_start_independent_intellicenter" in lifecycle
    assert "async_stop_independent_intellicenter" in lifecycle


def test_body_state_change_refreshes_stale_spa_target_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)

    FakeModelController.initial_objects = _objects() + (
        (
            "B1202",
            {
                "OBJTYP": "BODY",
                "SUBTYP": "SPA",
                "SNAME": "Spa",
                "PARENT": "SYS01",
                "STATUS": "OFF",
                "HTMODE": "0",
                "LSTTMP": "98",
                "LOTMP": "94",
                "HEATER": "H0001",
            },
        ),
    )

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        transport._controller.model.add_object(
            "H0002",
            {
                "OBJTYP": "HEATER",
                "SUBTYP": "SOLAR",
                "SNAME": "Solar",
                "PARENT": "SYS01",
            },
        )

        transport._controller.command_response_queues["RequestParamList"] = [
            {
                "objectList": [
                    {
                        "objnam": "B1202",
                        "params": {
                            "LOTMP": "98",
                            "HEATER": "H0002",
                            "HTMODE": "1",
                            "STATUS": "ON",
                            "LSTTMP": "97",
                        },
                    }
                ]
            },
            {
                "objectList": [
                    {
                        "objnam": "H0002",
                        "params": {
                            "OBJTYP": "HEATER",
                            "SUBTYP": "SOLAR",
                            "SNAME": "Solar",
                        },
                    }
                ]
            },
        ]

        spa = transport._controller.model["B1202"]
        assert spa is not None
        spa.properties["STATUS"] = "ON"
        spa.properties["HTMODE"] = "1"

        transport._on_updated(
            {
                "B1202": {
                    "STATUS": "ON",
                    "HTMODE": "1",
                }
            }
        )

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert (
            "RequestParamList",
            {
                "objectList": [
                    {
                        "objnam": "B1202",
                        "keys": [
                            "LOTMP",
                            "HEATER",
                            "HTMODE",
                            "STATUS",
                            "LSTTMP",
                        ],
                    }
                ]
            },
        ) in transport._controller.sent_requests

        assert (
            "RequestParamList",
            {
                "objectList": [
                    {
                        "objnam": "H0002",
                        "keys": ["OBJTYP", "SUBTYP", "SNAME"],
                    }
                ]
            },
        ) in transport._controller.sent_requests

        snapshot = transport.read_snapshot()
        spa_body = next(
            body for body in snapshot.bodies if body.native_id == "B1202"
        )
        assert spa_body.target_temperature == 98.0
        assert spa_body.raw_heater_id == "H0002"
        assert spa_body.active_heat_source == "solar"

        assert set(transport._controller.sent_operations) == {
            "RequestParamList"
        }

        await transport.async_stop()
        assert not transport._body_metadata_refresh_tasks
        assert not transport._body_metadata_refresh_pending

    asyncio.run(exercise())


def test_lotmp_update_does_not_recursively_request_body_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        transport._on_updated(
            {
                "B1101": {
                    "LOTMP": "90",
                }
            }
        )

        await asyncio.sleep(0)

        assert transport._controller.sent_operations == []

        await transport.async_stop()

    asyncio.run(exercise())


def test_body_update_during_pending_refresh_forces_one_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        calls: list[str] = []

        async def refresh(
            objnam: str,
            *,
            applying_body_ids: set[str],
        ) -> None:
            del applying_body_ids
            calls.append(objnam)

            if len(calls) == 1:
                # Simulate a new real BODY transition arriving while the
                # first refresh is still pending.
                transport._on_updated(
                    {
                        objnam: {
                            "HEATER": "H0002",
                        }
                    }
                )

            await asyncio.sleep(0)

        transport._controller.refresh_body_metadata = refresh

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        for _ in range(6):
            await asyncio.sleep(0)

        assert calls == ["B1101", "B1101"]
        assert not transport._body_metadata_refresh_pending
        assert not transport._body_metadata_refresh_dirty

        await transport.async_stop()

    asyncio.run(exercise())


def test_unsolicited_lotmp_and_heater_update_still_refreshes_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        calls: list[str] = []

        async def refresh(
            objnam: str,
            *,
            applying_body_ids: set[str],
        ) -> None:
            del applying_body_ids
            calls.append(objnam)

        transport._controller.refresh_body_metadata = refresh

        transport._on_updated(
            {
                "B1101": {
                    "LOTMP": "90",
                    "HEATER": "H0002",
                    "HTMODE": "1",
                }
            }
        )

        for _ in range(4):
            await asyncio.sleep(0)

        assert calls == ["B1101"]

        await transport.async_stop()

    asyncio.run(exercise())


def test_internal_body_refresh_application_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        transport._body_metadata_refresh_applying.add("B1101")
        try:
            transport._on_updated(
                {
                    "B1101": {
                        "LOTMP": "90",
                        "HEATER": "H0002",
                        "HTMODE": "1",
                    }
                }
            )
        finally:
            transport._body_metadata_refresh_applying.discard("B1101")

        await asyncio.sleep(0)

        assert transport._controller.sent_operations == []
        assert not transport._body_metadata_refresh_pending

        await transport.async_stop()

    asyncio.run(exercise())
