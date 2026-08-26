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

    def attributes_to_track(self) -> list[dict[str, object]]:
        """Build the RequestParamList entries used by ICModelController.start()."""

        return [
            {
                "objnam": item.objnam,
                "keys": sorted(self.attribute_map[item.objtype]),
            }
            for item in self
            if item.objtype in self.attribute_map
        ]


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
                    "HITMP": "104",
                    "LSTTMP": "82",
                    "LOTMP": "86",
                    "MODE": "0",
                    "VOL": "15000",
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
        "HITMP_ATTR": "HITMP",
        "HTMODE_ATTR": "HTMODE",
        "LOTMP_ATTR": "LOTMP",
        "LSTTMP_ATTR": "LSTTMP",
        "MODE_ATTR": "MODE",
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
        "VOL_ATTR": "VOL",
    }
    for name, value in constants.items():
        setattr(pyic, name, value)
    pyic.ICBaseController = FakeModelController
    pyic.ICConnectionHandler = FakeConnectionHandler
    pyic.ICModelController = FakeModelController
    pyic.PoolModel = FakePoolModel
    pyic.PoolObject = FakePoolObject

    exceptions = ModuleType("pyintellicenter.exceptions")

    class FakeICConnectionError(Exception):
        pass

    class FakeICTimeoutError(Exception):
        pass

    exceptions.ICConnectionError = FakeICConnectionError
    exceptions.ICTimeoutError = FakeICTimeoutError

    pyic.ICConnectionError = FakeICConnectionError
    pyic.ICTimeoutError = FakeICTimeoutError

    attributes = ModuleType("pyintellicenter.attributes")
    attributes.ALL_ATTRIBUTES_BY_TYPE = {
        str(params["OBJTYP"]): {"SNAME", "PARENT", "SUBTYP", "STATUS"}
        for _, params in _objects()
        if params["OBJTYP"] != "FUTURE_TYPE"
    }
    attributes.ALL_ATTRIBUTES_BY_TYPE["SENSE"] = {
        "CALIB",
        "HNAME",
        "LISTORD",
        "MODE",
        "NAME",
        "PARENT",
        "PROBE",
        "READY",
        "SNAME",
        "SOURCE",
        "STATIC",
        "STATUS",
        "SUBTYP",
    }
    monkeypatch.setitem(sys.modules, "pyintellicenter", pyic)
    monkeypatch.setitem(sys.modules, "pyintellicenter.attributes", attributes)
    monkeypatch.setitem(sys.modules, "pyintellicenter.exceptions", exceptions)
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


def test_body_monitoring_matches_working_narrow_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BODY NotifyList monitoring must request prompt canonical LOTMP evidence."""

    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )

    assert transport._model.attribute_map["BODY"] == {
        "SNAME",
        "HEATER",
        "HITMP",
        "HTMODE",
        "LOTMP",
        "LSTTMP",
        "MODE",
        "STATUS",
        "VOL",
    }
    assert "SETTMP" not in transport._model.attribute_map["BODY"]
    assert "SETPT" not in transport._model.attribute_map["BODY"]

    asyncio.run(transport.async_start())
    body_request = next(
        item
        for item in transport._model.attributes_to_track()
        if item["objnam"] == "B1101"
    )
    assert body_request == {
        "objnam": "B1101",
        "keys": [
            "HEATER",
            "HITMP",
            "HTMODE",
            "LOTMP",
            "LSTTMP",
            "MODE",
            "SNAME",
            "STATUS",
            "VOL",
        ],
    }

    # Narrowing BODY must not reduce any other known object's monitoring map.
    assert transport._model.attribute_map["PUMP"] == {
        "SNAME",
        "PARENT",
        "SUBTYP",
        "STATUS",
    }
    assert transport._model.attribute_map["SENSE"] == {"SNAME", "SOURCE"}

    body_inventory = next(
        item
        for item in transport.read_snapshot().raw_inventory
        if item.native_id == "B1101"
    )
    raw_names = {item.name for item in body_inventory.attributes}
    assert transport._model.attribute_map["BODY"] <= raw_names
    asyncio.run(transport.async_stop())


def test_startup_requests_exact_narrow_sense_monitoring_for_every_sensor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real controller startup must send only calibrated SENSE evidence keys."""

    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects() + (
        (
            "SSS11",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "SOLAR",
                "SNAME": "Solar",
                "SOURCE": "64",
            },
        ),
        (
            "SSW11",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "POOL",
                "SNAME": "Water",
                "SOURCE": "79",
            },
        ),
    )
    original_start = FakeModelController.start

    async def start_with_monitoring(self: FakeModelController) -> None:
        await original_start(self)
        await self.send_cmd(
            "RequestParamList",
            {"objectList": self.model.attributes_to_track()},
        )

    monkeypatch.setattr(FakeModelController, "start", start_with_monitoring)
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )

    asyncio.run(transport.async_start())

    startup_request = transport._controller.sent_requests[0]
    assert startup_request[0] == "RequestParamList"
    object_list = startup_request[1]["objectList"]
    sense_requests = [
        item
        for item in object_list
        if str(item["objnam"]).startswith("S")
        and transport._model[str(item["objnam"])].objtype == "SENSE"
    ]
    assert sense_requests == [
        {"objnam": "S0001", "keys": ["SNAME", "SOURCE"]},
        {"objnam": "SSS11", "keys": ["SNAME", "SOURCE"]},
        {"objnam": "SSW11", "keys": ["SNAME", "SOURCE"]},
    ]
    assert all(
        not ({"PROBE", "CALIB", "STATUS", "READY"} & set(item["keys"]))
        for item in sense_requests
    )

    body_request = next(item for item in object_list if item["objnam"] == "B1101")
    assert body_request["keys"] == [
        "HEATER",
        "HITMP",
        "HTMODE",
        "LOTMP",
        "LSTTMP",
        "MODE",
        "SNAME",
        "STATUS",
        "VOL",
    ]
    pump_request = next(item for item in object_list if item["objnam"] == "P0001")
    assert pump_request["keys"] == ["PARENT", "SNAME", "STATUS", "SUBTYP"]


def test_reconnect_and_dynamic_discovery_retain_narrow_sense_monitoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every regenerated or newly discovered SENSE request uses one contract."""

    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )
    asyncio.run(transport.async_start())

    initial = next(
        item
        for item in transport._model.attributes_to_track()
        if item["objnam"] == "S0001"
    )
    transport._on_disconnected(ConnectionError("test reconnect"))
    transport._on_connected(reconnected=True)
    regenerated = next(
        item
        for item in transport._model.attributes_to_track()
        if item["objnam"] == "S0001"
    )

    transport._model.add_object(
        "S-DYNAMIC",
        {
            "OBJTYP": "SENSE",
            "SUBTYP": "SOLAR",
            "SNAME": "New Solar Sensor",
            "SOURCE": "101",
        },
    )
    dynamic = next(
        item
        for item in transport._model.attributes_to_track()
        if item["objnam"] == "S-DYNAMIC"
    )

    asyncio.run(
        transport._controller.send_cmd(
            "RequestParamList",
            {"objectList": [regenerated]},
        )
    )
    asyncio.run(
        transport._controller.send_cmd(
            "RequestParamList",
            {"objectList": [dynamic]},
        )
    )

    assert initial == regenerated == {
        "objnam": "S0001",
        "keys": ["SNAME", "SOURCE"],
    }
    assert dynamic == {
        "objnam": "S-DYNAMIC",
        "keys": ["SNAME", "SOURCE"],
    }
    assert transport._controller.sent_requests[-2:] == [
        ("RequestParamList", {"objectList": [regenerated]}),
        ("RequestParamList", {"objectList": [dynamic]}),
    ]


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


@pytest.mark.parametrize(
    ("native_id", "subtype", "initial", "updated", "concept"),
    (
        ("SSS11", "SOLAR", "64", "139", "solar.temperature"),
        ("_A135", "AIR", "70", "85", "air.temperature"),
        ("SSW11", "POOL", "79", "90", "water.temperature"),
    ),
)
def test_sense_source_update_reaches_canonical_native_surface(
    monkeypatch: pytest.MonkeyPatch,
    native_id: str,
    subtype: str,
    initial: str,
    updated: str,
    concept: str,
) -> None:
    """A current calibrated SOURCE update reaches the HA-facing native snapshot."""

    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = (
        (
            native_id,
            {
                "OBJTYP": "SENSE",
                "SUBTYP": subtype,
                "SNAME": subtype.title(),
                "SOURCE": initial,
                "PROBE": "999",
            },
        ),
    )
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )
    asyncio.run(transport.async_start())

    def canonical_value() -> object:
        snapshot = transport.read_snapshot()
        canonical = NativeIntelliCenterReadAdapter().map_snapshot(
            snapshot,
            generated_at=snapshot.observed_at,
        )
        return next(
            item.value
            for item in canonical.observations
            if item.observation_id == concept
        )

    assert canonical_value() == float(initial)

    transport._controller._apply_updates(
        [{"objnam": native_id, "params": {"SOURCE": updated}}]
    )

    temperature = next(
        item
        for item in transport.read_snapshot().temperatures
        if item.native_id == native_id
    )
    assert temperature.temperature == float(updated)
    assert canonical_value() == float(updated)


def test_probe_only_change_never_replaces_calibrated_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical broad-model PROBE churn cannot become canonical evidence."""

    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = (
        (
            "SSS11",
            {
                "OBJTYP": "SENSE",
                "SUBTYP": "SOLAR",
                "SNAME": "Solar",
                "SOURCE": "64",
                "PROBE": "100",
            },
        ),
    )
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )
    asyncio.run(transport.async_start())

    transport._controller._apply_updates(
        [{"objnam": "SSS11", "params": {"PROBE": "139"}}]
    )

    snapshot = transport.read_snapshot()
    solar = next(item for item in snapshot.temperatures if item.native_id == "SSS11")
    canonical = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=snapshot.observed_at,
    )
    solar_value = next(
        item.value
        for item in canonical.observations
        if item.observation_id == "solar.temperature"
    )
    assert solar.temperature == 64.0
    assert solar_value == 64.0


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
    assert "def async_start_independent_intellicenter" in coordinator
    assert "self.async_start_independent_intellicenter()" in coordinator
    assert "async_activate_poolos_post_start" in lifecycle
    assert "coordinator.async_activate_post_start()" in lifecycle
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
                            "SNAME",
                            "HEATER",
                            "HITMP",
                            "HTMODE",
                            "LOTMP",
                            "LSTTMP",
                            "MODE",
                            "STATUS",
                            "VOL",
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

        # C5.6 performs one legitimate reconciliation after connection.
        # Let that lifecycle work finish before isolating this test's behavior.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks
        transport._controller.sent_operations.clear()
        transport._controller.sent_requests.clear()

        calls: list[str] = []

        async def refresh(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            del applying_body_ids
            assert generation_is_current()
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

        # C5.6 performs one legitimate reconciliation after connection.
        # Let that lifecycle work finish before isolating this test's behavior.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks
        transport._controller.sent_operations.clear()
        transport._controller.sent_requests.clear()

        calls: list[str] = []

        async def refresh(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            del applying_body_ids
            assert generation_is_current()
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

        # C5.6 performs one legitimate reconciliation after connection.
        # Let that lifecycle work finish before isolating this test's behavior.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks
        transport._controller.sent_operations.clear()
        transport._controller.sent_requests.clear()

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


def test_connection_reconciliation_refreshes_all_known_bodies(
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
                "STATUS": "ON",
                "HTMODE": "1",
                "LSTTMP": "97",
                "LOTMP": "94",
                "HEATER": "H0001",
            },
        ),
    )

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        refreshed: list[str] = []

        async def refresh_body_metadata(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            del applying_body_ids
            assert generation_is_current()
            refreshed.append(objnam)

            if objnam == "B1202":
                body = transport._controller.model[objnam]
                assert body is not None
                body.properties["LOTMP"] = "98"
                transport._on_updated(
                    {
                        objnam: {
                            "LOTMP": "98",
                        }
                    }
                )

        transport._controller.refresh_body_metadata = refresh_body_metadata

        await transport.async_start()

        for _ in range(12):
            await asyncio.sleep(0)

        assert "B1101" in refreshed
        assert "B1202" in refreshed

        snapshot = transport.read_snapshot()
        spa = next(body for body in snapshot.bodies if body.native_id == "B1202")
        assert spa.target_temperature == 98.0

        await transport.async_stop()

    asyncio.run(exercise())


def test_reconnect_reconciliation_recovers_after_failed_body_refresh(
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
                "STATUS": "ON",
                "HTMODE": "1",
                "LSTTMP": "97",
                "LOTMP": "94",
                "HEATER": "H0001",
            },
        ),
    )

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        spa_attempts = 0

        async def refresh_body_metadata(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            nonlocal spa_attempts
            del applying_body_ids

            assert generation_is_current()

            if objnam != "B1202":
                return

            spa_attempts += 1
            if spa_attempts <= 2:
                # C5.6 permits exactly one same-generation retry. Fail both
                # attempts so this test continues to exercise recovery that
                # specifically requires a later reconnect/reconciliation.
                raise module.ICConnectionError("simulated refresh failure")

            body = transport._controller.model[objnam]
            assert body is not None
            body.properties["LOTMP"] = "98"
            transport._on_updated(
                {
                    objnam: {
                        "LOTMP": "98",
                    }
                }
            )

        transport._controller.refresh_body_metadata = refresh_body_metadata

        await transport.async_start()

        for _ in range(12):
            await asyncio.sleep(0)

        # Initial attempt plus the one bounded same-generation retry must both
        # have been exhausted before reconnect recovery is exercised.
        assert spa_attempts == 2

        transport._on_disconnected(ConnectionError("lost"))
        transport._on_connected(reconnected=True)

        for _ in range(20):
            await asyncio.sleep(0)

        # Reconnect creates a new authoritative generation and therefore must
        # make at least one fresh reconciliation attempt.
        assert spa_attempts >= 3

        snapshot = transport.read_snapshot()
        spa = next(body for body in snapshot.bodies if body.native_id == "B1202")
        assert spa.target_temperature == 98.0
        assert transport.diagnostics(generated_at=NOW)["reconnect_count"] == 1

        await transport.async_stop()

    asyncio.run(exercise())


def test_transient_body_refresh_failure_retries_once_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        # Drain the legitimate initial C5.6 connection reconciliation so this
        # test isolates only the explicit BODY transition below.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        attempts = 0

        async def refresh_body_metadata(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            nonlocal attempts
            del applying_body_ids

            assert generation_is_current()
            assert objnam == "B1101"

            attempts += 1
            if attempts == 1:
                raise module.ICConnectionError(
                    "simulated transient RequestParamList failure"
                )

            body = transport._controller.model[objnam]
            assert body is not None
            body.properties["LOTMP"] = "98"

            # Production refresh_body_metadata applies the response through
            # _apply_updates(), which republishes the immutable snapshot.
            transport._on_updated(
                {
                    objnam: {
                        "LOTMP": "98",
                    }
                }
            )

        transport._controller.refresh_body_metadata = refresh_body_metadata

        generation_before = transport._discovery_generation

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        for _ in range(12):
            await asyncio.sleep(0)

        assert attempts == 2
        assert transport._discovery_generation == generation_before

        snapshot = transport.read_snapshot()
        body = next(
            item for item in snapshot.bodies if item.native_id == "B1101"
        )
        assert body.target_temperature == 98.0

        assert not transport._body_metadata_refresh_pending
        assert not transport._body_metadata_refresh_dirty

        await transport.async_stop()

    asyncio.run(exercise())


def test_transient_body_refresh_timeout_retries_once_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        # Drain initial C5.6 reconciliation so this test isolates the
        # explicit BODY transition and its timeout retry.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        attempts = 0

        async def refresh_body_metadata(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            nonlocal attempts
            del applying_body_ids

            assert generation_is_current()
            assert objnam == "B1101"

            attempts += 1

            if attempts == 1:
                raise module.ICTimeoutError(
                    "simulated transient RequestParamList timeout"
                )

            body = transport._controller.model[objnam]
            assert body is not None
            body.properties["LOTMP"] = "99"

            transport._on_updated(
                {
                    objnam: {
                        "LOTMP": "99",
                    }
                }
            )

        transport._controller.refresh_body_metadata = refresh_body_metadata

        generation_before = transport._discovery_generation

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        for _ in range(12):
            await asyncio.sleep(0)

        assert attempts == 2
        assert transport._discovery_generation == generation_before

        snapshot = transport.read_snapshot()
        body = next(
            item for item in snapshot.bodies if item.native_id == "B1101"
        )
        assert body.target_temperature == 99.0

        assert not transport._body_metadata_refresh_pending
        assert not transport._body_metadata_refresh_dirty

        await transport.async_stop()

    asyncio.run(exercise())


def test_unexpected_body_refresh_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        # Drain initial C5.6 reconciliation before isolating this worker.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        attempts = 0

        async def refresh_body_metadata(
            objnam: str,
            *,
            applying_body_ids: set[str],
            generation_is_current,
        ) -> None:
            nonlocal attempts
            del objnam, applying_body_ids
            assert generation_is_current()
            attempts += 1
            raise TypeError("simulated programming failure")

        transport._controller.refresh_body_metadata = refresh_body_metadata

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        for _ in range(12):
            await asyncio.sleep(0)

        # Unexpected software/data failures must never enter the bounded
        # transient retry path.
        assert attempts == 1
        assert transport._last_error_code == "TYPEERROR"
        assert not transport._body_metadata_refresh_pending
        assert not transport._body_metadata_refresh_dirty

        await transport.async_stop()

    asyncio.run(exercise())


def test_retrying_state_rejects_inflight_body_response_before_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        # Drain initial reconciliation so the blocked request below belongs
        # unambiguously to the current authoritative generation.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        transport._controller.sent_operations.clear()
        transport._controller.sent_requests.clear()

        original_send_cmd = transport._controller.send_cmd
        body_request_started = asyncio.Event()
        release_body_response = asyncio.Event()
        intercepted = False

        async def delayed_send_cmd(
            cmd: str,
            extra: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            nonlocal intercepted

            if (
                not intercepted
                and cmd == "RequestParamList"
                and extra
                and extra.get("objectList")
                and extra["objectList"][0].get("objnam") == "B1101"
            ):
                intercepted = True
                body_request_started.set()
                await release_body_response.wait()

                return {
                    "objectList": [
                        {
                            "objnam": "B1101",
                            "params": {
                                "LOTMP": "113",
                                "HEATER": "H0001",
                                "HTMODE": "1",
                                "STATUS": "ON",
                                "LSTTMP": "99",
                            },
                        }
                    ]
                }

            return await original_send_cmd(cmd, extra)

        transport._controller.send_cmd = delayed_send_cmd

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        await body_request_started.wait()

        old_generation = transport._discovery_generation

        # Match the real ICConnectionHandler ordering: reconnection begins
        # immediately, while the debounced on_disconnected callback may arrive
        # later. RECONNECTING must already revoke authority from the old request.
        transport._on_retrying(30)

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.RECONNECTING
        )
        assert transport._discovery_generation == old_generation

        release_body_response.set()

        for _ in range(10):
            await asyncio.sleep(0)

        body = transport._controller.model["B1101"]
        assert body is not None
        assert body["LOTMP"] != "113"

        # Complete the remainder of the real handler lifecycle.
        transport._on_disconnected(ConnectionError("debounced disconnect"))
        transport._on_connected(reconnected=True)

        assert transport._discovery_generation == old_generation + 1

        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.AVAILABLE
        )
        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        # The new authoritative generation must have performed a fresh BODY
        # reconciliation rather than allowing the old request to become current.
        assert any(
            cmd == "RequestParamList"
            and request
            and request.get("objectList")
            and request["objectList"][0].get("objnam") == "B1101"
            for cmd, request in transport._controller.sent_requests
        )

        transport._controller.send_cmd = original_send_cmd
        await transport.async_stop()

    asyncio.run(exercise())


def test_late_model_update_cannot_resurrect_retrying_or_disconnected_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        # Drain the initial C5.6 reconciliation so this test begins from a
        # stable authoritative AVAILABLE generation.
        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.AVAILABLE
        )

        generation = transport._discovery_generation
        snapshot_before = transport.latest_snapshot
        last_update_before = transport._last_native_update

        transport._on_retrying(30)

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.RECONNECTING
        )

        # Simulate a late callback from model work associated with the old
        # connection. It must not restore AVAILABLE, publish a connected
        # snapshot, or make old-generation refresh work authoritative again.
        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.RECONNECTING
        )
        assert transport._discovery_generation == generation
        assert transport.latest_snapshot is snapshot_before
        assert transport._last_native_update == last_update_before
        assert not transport._body_metadata_refresh_pending

        transport._on_disconnected(ConnectionError("lost"))

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.DISCONNECTED
        )

        disconnected_snapshot = transport.latest_snapshot
        disconnected_last_update = transport._last_native_update

        transport._on_updated(
            {
                "B1101": {
                    "HEATER": "H0002",
                }
            }
        )

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.DISCONNECTED
        )
        assert transport._discovery_generation == generation
        assert transport.latest_snapshot is disconnected_snapshot
        assert transport._last_native_update == disconnected_last_update
        assert not transport._body_metadata_refresh_pending

        # Only the connection lifecycle callback may restore availability.
        transport._on_connected(reconnected=True)

        assert (
            transport.state
            is module.IndependentIntelliCenterTransportState.AVAILABLE
        )
        assert transport._discovery_generation == generation + 1

        await transport.async_stop()

    asyncio.run(exercise())


def test_old_generation_body_response_is_rejected_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        original_send_cmd = transport._controller.send_cmd
        body_request_started = asyncio.Event()
        release_body_response = asyncio.Event()

        async def delayed_send_cmd(
            cmd: str,
            extra: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if (
                cmd == "RequestParamList"
                and extra
                and extra.get("objectList")
                and extra["objectList"][0].get("objnam") == "B1101"
            ):
                body_request_started.set()
                await release_body_response.wait()
                return {
                    "objectList": [
                        {
                            "objnam": "B1101",
                            "params": {
                                "LOTMP": "111",
                                "HEATER": "H0001",
                                "HTMODE": "1",
                                "STATUS": "ON",
                                "LSTTMP": "99",
                            },
                        }
                    ]
                }
            return await original_send_cmd(cmd, extra)

        transport._controller.send_cmd = delayed_send_cmd

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        await body_request_started.wait()

        old_generation = transport._discovery_generation
        transport._on_disconnected(ConnectionError("lost"))

        release_body_response.set()

        for _ in range(10):
            await asyncio.sleep(0)

        body = transport._controller.model["B1101"]
        assert body is not None
        assert body["LOTMP"] != "111"
        assert transport._discovery_generation == old_generation

        transport._controller.send_cmd = original_send_cmd
        await transport.async_stop()

    asyncio.run(exercise())


def test_old_generation_body_response_is_rejected_after_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    FakeModelController.initial_objects = _objects()

    async def exercise() -> None:
        transport = module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        await transport.async_start()

        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        assert not transport._connection_reconciliation_tasks
        assert not transport._body_metadata_refresh_tasks

        original_send_cmd = transport._controller.send_cmd
        body_request_started = asyncio.Event()
        release_body_response = asyncio.Event()

        async def delayed_send_cmd(
            cmd: str,
            extra: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if (
                cmd == "RequestParamList"
                and extra
                and extra.get("objectList")
                and extra["objectList"][0].get("objnam") == "B1101"
                and not body_request_started.is_set()
            ):
                body_request_started.set()
                await release_body_response.wait()
                return {
                    "objectList": [
                        {
                            "objnam": "B1101",
                            "params": {
                                "LOTMP": "112",
                                "HEATER": "H0001",
                                "HTMODE": "1",
                                "STATUS": "ON",
                                "LSTTMP": "100",
                            },
                        }
                    ]
                }
            return await original_send_cmd(cmd, extra)

        transport._controller.send_cmd = delayed_send_cmd

        transport._on_updated(
            {
                "B1101": {
                    "HTMODE": "1",
                }
            }
        )

        await body_request_started.wait()

        old_generation = transport._discovery_generation

        transport._on_disconnected(ConnectionError("lost"))
        transport._on_connected(reconnected=True)

        assert transport._discovery_generation == old_generation + 1

        release_body_response.set()

        for _ in range(20):
            await asyncio.sleep(0)

        body = transport._controller.model["B1101"]
        assert body is not None
        assert body["LOTMP"] != "112"

        transport._controller.send_cmd = original_send_cmd
        await transport.async_stop()

    asyncio.run(exercise())


def test_source_uses_lotmp_for_body_target_temperature() -> None:
    """LOTMP is the pyintellicenter heating setpoint contract."""
    source = (
        Path("custom_components/poolos/independent_intellicenter.py")
        .read_text(encoding="utf-8")
    )

    lotmp_index = source.index("_number(item[LOTMP_ATTR])", source.index("def _copy_body("))
    settmp_index = source.index("_number(item[_SETTMP_ATTR])", lotmp_index)
    setpt_index = source.index("_number(item[_SETPT_ATTR])", settmp_index)

    assert lotmp_index < settmp_index < setpt_index


def test_source_never_continuously_monitors_auxiliary_body_targets() -> None:
    """SETTMP/SETPT must remain fallbacks, not NotifyList subscriptions."""
    source = (
        Path("custom_components/poolos/independent_intellicenter.py")
        .read_text(encoding="utf-8")
    )

    contract = source[source.index("_BODY_MONITOR_ATTRIBUTES = (") :]
    contract = contract[: contract.index(")")]

    assert "LOTMP_ATTR" in contract
    assert "_SETTMP_ATTR" not in contract
    assert "_SETPT_ATTR" not in contract


def test_copy_body_prefers_lotmp_over_stale_setpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale auxiliary SETPT must not mask the LOTMP heating target."""
    module = _load_module(monkeypatch)

    model = FakePoolModel({"BODY": set(), "HEATER": set()})
    body = model.add_object(
        "B1202",
        {
            "OBJTYP": "BODY",
            "SUBTYP": "SPA",
            "SNAME": "Spa",
            "STATUS": "OFF",
            "HTMODE": "0",
            "LSTTMP": "86",
            "LOTMP": "98",
            "SETPT": "101",
            "HEATER": "H0001",
        },
    )
    assert body is not None

    controller = FakeModelController(
        "192.0.2.10",
        model,
        keepalive_interval=90.0,
        transport="tcp",
    )

    copied = module._copy_body(body, controller)

    assert copied is not None
    assert copied.target_temperature == 98.0


def test_copy_body_falls_back_to_lotmp_when_setpt_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use LOTMP when SETPT is not available."""
    module = _load_module(monkeypatch)

    model = FakePoolModel({"BODY": set(), "HEATER": set()})
    body = model.add_object(
        "B1202",
        {
            "OBJTYP": "BODY",
            "SUBTYP": "SPA",
            "SNAME": "Spa",
            "STATUS": "OFF",
            "HTMODE": "0",
            "LSTTMP": "86",
            "LOTMP": "98",
            "HEATER": "H0001",
        },
    )
    assert body is not None

    controller = FakeModelController(
        "192.0.2.10",
        model,
        keepalive_interval=90.0,
        transport="tcp",
    )

    copied = module._copy_body(body, controller)

    assert copied is not None
    assert copied.target_temperature == 98.0


def test_copy_body_prefers_lotmp_over_stale_settmp_and_setpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale SETTMP/SETPT pair must not mask the LOTMP heating target."""
    module = _load_module(monkeypatch)

    model = FakePoolModel({"BODY": set(), "HEATER": set()})
    body = model.add_object(
        "B1202",
        {
            "OBJTYP": "BODY",
            "SUBTYP": "SPA",
            "SNAME": "Spa",
            "STATUS": "OFF",
            "HTMODE": "0",
            "LSTTMP": "89",
            "LOTMP": "97",
            "SETPT": "98",
            "SETTMP": "98",
            "HEATER": "H0001",
        },
    )
    assert body is not None

    controller = FakeModelController(
        "192.0.2.10",
        model,
        keepalive_interval=90.0,
        transport="tcp",
    )

    copied = module._copy_body(body, controller)

    assert copied is not None
    assert copied.target_temperature == 97.0


def test_copy_body_falls_back_to_settmp_when_lotmp_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use SETTMP only as compatibility evidence when LOTMP is unavailable."""
    module = _load_module(monkeypatch)

    model = FakePoolModel({"BODY": set(), "HEATER": set()})
    body = model.add_object(
        "B1202",
        {
            "OBJTYP": "BODY",
            "SUBTYP": "SPA",
            "SNAME": "Spa",
            "STATUS": "ON",
            "HTMODE": "1",
            "LSTTMP": "95",
            "SETPT": "98",
            "SETTMP": "99",
            "HEATER": "H0001",
        },
    )
    assert body is not None

    controller = FakeModelController(
        "192.0.2.10",
        model,
        keepalive_interval=90.0,
        transport="tcp",
    )

    copied = module._copy_body(body, controller)

    assert copied is not None
    assert copied.target_temperature == 99.0


def test_copy_body_falls_back_to_setpt_when_lotmp_and_settmp_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain SETPT only as the final missing-value compatibility fallback."""

    module = _load_module(monkeypatch)
    model = FakePoolModel({"BODY": set(), "HEATER": set()})
    body = model.add_object(
        "B1202",
        {
            "OBJTYP": "BODY",
            "SUBTYP": "SPA",
            "SNAME": "Spa",
            "STATUS": "OFF",
            "HTMODE": "0",
            "LSTTMP": "95",
            "SETPT": "98",
            "HEATER": "H0001",
        },
    )
    assert body is not None
    controller = FakeModelController(
        "192.0.2.10",
        model,
        keepalive_interval=90.0,
        transport="tcp",
    )

    copied = module._copy_body(body, controller)

    assert copied is not None
    assert copied.target_temperature == 98.0


def test_native_update_notifies_snapshot_update_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native model update must notify the owner after snapshot publication."""

    module = _load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(
        host="192.0.2.10"
    )
    asyncio.run(transport.async_start())

    notifications: list[object] = []
    transport._set_snapshot_update_callback(  # noqa: SLF001
        lambda: notifications.append(transport.latest_snapshot)
    )

    transport._state = module.IndependentIntelliCenterTransportState.AVAILABLE
    transport._running = True

    transport._on_updated({})  # noqa: SLF001

    assert len(notifications) == 1
    assert notifications[0] is transport.latest_snapshot
    assert transport.latest_snapshot is not None
