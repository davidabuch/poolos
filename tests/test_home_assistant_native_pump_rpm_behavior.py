"""Behavioral safety tests for native Pool PMPCIRC RPM writes."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "poolos"
    / "manual_intellicenter.py"
)


class _StubConnectionHandler:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _StubModelController:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


class _StubPoolModel:
    pass


private_pyintellicenter = ModuleType("pyintellicenter")
private_pyintellicenter.ICBaseController = object
private_pyintellicenter.ICConnectionHandler = _StubConnectionHandler
private_pyintellicenter.ICModelController = _StubModelController
private_pyintellicenter.PoolModel = _StubPoolModel

private_pyintellicenter.LIGHT_EFFECTS = {}
private_pyintellicenter.HEATER_ATTR = "HEATER"
private_pyintellicenter.MAX_ATTR = "MAX"
private_pyintellicenter.MIN_ATTR = "MIN"
private_pyintellicenter.PARENT_ATTR = "PARENT"
private_pyintellicenter.PMPCIRC_TYPE = "PMPCIRC"
private_pyintellicenter.PUMP_TYPE = "PUMP"
private_pyintellicenter.SELECT_ATTR = "SELECT"
private_pyintellicenter.SPEED_ATTR = "SPEED"
private_pyintellicenter.STATUS_ATTR = "STATUS"
private_pyintellicenter.STATUS_OFF = "OFF"
private_pyintellicenter.STATUS_ON = "ON"

original_pyintellicenter = sys.modules.get("pyintellicenter")

try:
    sys.modules["pyintellicenter"] = private_pyintellicenter

    SPEC = importlib.util.spec_from_file_location(
        "poolos_manual_intellicenter_behavior_test",
        MODULE_PATH,
    )

    assert SPEC is not None
    assert SPEC.loader is not None

    manual_module = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = manual_module
    SPEC.loader.exec_module(manual_module)

finally:
    if original_pyintellicenter is None:
        sys.modules.pop("pyintellicenter", None)
    else:
        sys.modules["pyintellicenter"] = original_pyintellicenter


ManualIntelliCenterCommandError = (
    manual_module.ManualIntelliCenterCommandError
)
ManualIntelliCenterControl = manual_module.ManualIntelliCenterControl
ManualIntelliCenterState = manual_module.ManualIntelliCenterState


class _Model:
    def __init__(self, objects: list[Any]) -> None:
        self._objects = {
            item.objnam: item
            for item in objects
        }

    def __getitem__(self, objnam: str) -> Any:
        return self._objects.get(objnam)


class _RecordingController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.error: Exception | None = None

    async def request_changes(
        self,
        objnam: str,
        changes: dict[str, str],
    ) -> None:
        if self.error is not None:
            raise self.error

        self.calls.append(
            (
                objnam,
                dict(changes),
            )
        )


def _gateway(
    objects: list[Any],
    controller: _RecordingController | None = None,
) -> tuple[ManualIntelliCenterControl, _RecordingController]:
    recorder = controller or _RecordingController()

    gateway = ManualIntelliCenterControl.__new__(
        ManualIntelliCenterControl
    )

    gateway._model = _Model(objects)
    gateway._controller = recorder
    gateway._state = ManualIntelliCenterState.AVAILABLE
    gateway._command_lock = asyncio.Lock()
    gateway._last_error_code = None

    return gateway, recorder


def _run(coro):
    return asyncio.run(coro)


def test_only_exact_pool_pmpcirc_id_is_accepted(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory()
    circuit = pump_circuit_object_factory(objnam="p0102")
    gateway, recorder = _gateway([pump, circuit])

    with pytest.raises(
        ValueError,
        match="unsupported manual-control pump circuit",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p9999",
                2900,
            )
        )

    assert recorder.calls == []


def test_allowlisted_id_must_be_live_pmpcirc(
    pump_object_factory,
) -> None:
    wrong_type = pump_object_factory(objnam="p0102")
    gateway, recorder = _gateway([wrong_type])

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="not a live PMPCIRC",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p0102",
                2900,
            )
        )

    assert recorder.calls == []


def test_pmpcirc_requires_explicit_rpm_mode(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory()

    for mode in ("GPM", None):
        circuit = pump_circuit_object_factory(
            objnam="p0102",
            mode=mode,
        )
        gateway, recorder = _gateway([pump, circuit])

        with pytest.raises(
            ManualIntelliCenterCommandError,
            match="not configured for RPM control",
        ):
            _run(
                gateway.async_set_pump_circuit_speed(
                    "p0102",
                    2900,
                )
            )

        assert recorder.calls == []


def test_pmpcirc_parent_must_be_live_pump(
    pump_circuit_object_factory,
) -> None:
    circuit = pump_circuit_object_factory(
        objnam="p0102",
        pump_id="P404",
    )
    gateway, recorder = _gateway([circuit])

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="parent is not a live pump object",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p0102",
                2900,
            )
        )

    assert recorder.calls == []


def test_native_parent_min_max_are_required(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    circuit = pump_circuit_object_factory(objnam="p0102")

    for minimum, maximum in (
        (None, 3450),
        (450, None),
        ("invalid", 3450),
        (450, "invalid"),
    ):
        pump = pump_object_factory(
            minimum_rpm=minimum,
            maximum_rpm=maximum,
        )
        gateway, recorder = _gateway([pump, circuit])

        with pytest.raises(
            ManualIntelliCenterCommandError,
            match="native RPM limits are unavailable",
        ):
            _run(
                gateway.async_set_pump_circuit_speed(
                    "p0102",
                    2900,
                )
            )

        assert recorder.calls == []


def test_native_parent_min_max_order_must_be_valid(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory(
        minimum_rpm=3000,
        maximum_rpm=2000,
    )
    circuit = pump_circuit_object_factory(objnam="p0102")
    gateway, recorder = _gateway([pump, circuit])

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="RPM limits are invalid",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p0102",
                2900,
            )
        )

    assert recorder.calls == []


def test_requested_rpm_must_be_inside_native_bounds(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory(
        minimum_rpm=450,
        maximum_rpm=3450,
    )
    circuit = pump_circuit_object_factory(objnam="p0102")

    for rpm in (449, 3451):
        gateway, recorder = _gateway([pump, circuit])

        with pytest.raises(
            ValueError,
            match="pump RPM must be between 450 and 3450",
        ):
            _run(
                gateway.async_set_pump_circuit_speed(
                    "p0102",
                    rpm,
                )
            )

        assert recorder.calls == []


def test_fractional_or_non_numeric_rpm_is_rejected_before_delivery(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory()
    circuit = pump_circuit_object_factory(objnam="p0102")

    gateway, recorder = _gateway([pump, circuit])

    for rpm in (2900.5, True, "2900"):
        with pytest.raises(ValueError):
            _run(
                gateway.async_set_pump_circuit_speed(
                    "p0102",
                    rpm,
                )
            )

    assert recorder.calls == []


def test_valid_2900_request_sends_exact_speed_payload_to_p0102(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory(
        minimum_rpm=450,
        maximum_rpm=3450,
    )
    circuit = pump_circuit_object_factory(
        objnam="p0102",
        mode="RPM",
        rpm_setpoint=2600,
    )

    gateway, recorder = _gateway([pump, circuit])

    receipt = _run(
        gateway.async_set_pump_circuit_speed(
            "p0102",
            2900,
        )
    )

    assert recorder.calls == [
        (
            "p0102",
            {"SPEED": "2900"},
        )
    ]

    assert receipt.body_objnam == "p0102"
    assert receipt.operation == "pump_circuit_speed"
    assert receipt.value == 2900


def test_command_failure_is_not_reported_as_success(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory()
    circuit = pump_circuit_object_factory(objnam="p0102")

    recorder = _RecordingController()
    recorder.error = RuntimeError("synthetic transport failure")

    gateway, recorder = _gateway(
        [pump, circuit],
        recorder,
    )

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="failed to set p0102 pump circuit speed",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p0102",
                2900,
            )
        )

    assert recorder.calls == []
    assert gateway._last_error_code == "RUNTIMEERROR"


def test_unavailable_manual_transport_rejects_before_delivery(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory()
    circuit = pump_circuit_object_factory(objnam="p0102")

    gateway, recorder = _gateway([pump, circuit])
    gateway._state = ManualIntelliCenterState.DISCONNECTED

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="command connection is unavailable",
    ):
        _run(
            gateway.async_set_pump_circuit_speed(
                "p0102",
                2900,
            )
        )

    assert recorder.calls == []


def test_body_heat_source_accepts_only_commissioned_matrix() -> None:
    gateway, recorder = _gateway([])

    for body in ("B1101", "B1202"):
        for heater in ("00000", "H0001", "H0002"):
            receipt = _run(
                gateway.async_set_body_heat_source(
                    body,
                    heater,
                )
            )

            assert recorder.calls[-1] == (
                body,
                {"HEATER": heater},
            )
            assert receipt.body_objnam == body
            assert receipt.operation == "body_heat_source"
            assert receipt.value == heater


def test_body_heat_source_rejects_unknown_body_or_heater() -> None:
    gateway, recorder = _gateway([])

    with pytest.raises(
        ValueError,
        match="unsupported manual-control body",
    ):
        _run(
            gateway.async_set_body_heat_source(
                "B9999",
                "H0002",
            )
        )

    with pytest.raises(
        ValueError,
        match="unsupported manual-control heat source",
    ):
        _run(
            gateway.async_set_body_heat_source(
                "B1101",
                "HXSLR",
            )
        )

    with pytest.raises(
        ValueError,
        match="unsupported manual-control heat source",
    ):
        _run(
            gateway.async_set_body_heat_source(
                "B1202",
                "H9999",
            )
        )

    assert recorder.calls == []


def test_body_heat_source_never_writes_htmode() -> None:
    gateway, recorder = _gateway([])

    _run(
        gateway.async_set_body_heat_source(
            "B1202",
            "H0001",
        )
    )

    assert recorder.calls == [
        (
            "B1202",
            {"HEATER": "H0001"},
        )
    ]
    assert "HTMODE" not in recorder.calls[0][1]


def test_body_heat_source_transport_failure_is_not_success() -> None:
    recorder = _RecordingController()
    recorder.error = RuntimeError("synthetic transport failure")

    gateway, recorder = _gateway([], recorder)

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="failed to set B1101 heat source",
    ):
        _run(
            gateway.async_set_body_heat_source(
                "B1101",
                "H0001",
            )
        )

    assert recorder.calls == []
    assert gateway._last_error_code == "RUNTIMEERROR"
