"""Behavioral safety tests for native Pool PMPCIRC RPM writes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from poolos.intellicenter_readonly import (
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
)

from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority


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
private_pyintellicenter.BODY_ATTR = "BODY"
private_pyintellicenter.CHEM_TYPE = "CHEM"
private_pyintellicenter.HEATER_ATTR = "HEATER"
private_pyintellicenter.MAX_ATTR = "MAX"
private_pyintellicenter.MIN_ATTR = "MIN"
private_pyintellicenter.PARENT_ATTR = "PARENT"
private_pyintellicenter.PMPCIRC_TYPE = "PMPCIRC"
private_pyintellicenter.PUMP_TYPE = "PUMP"
private_pyintellicenter.PRIM_ATTR = "PRIM"
private_pyintellicenter.SEC_ATTR = "SEC"
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

    def get_by_type(self, objtype: str) -> list[Any]:
        return [
            item
            for item in self._objects.values()
            if item.objtype == objtype
        ]


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

    async def set_chlorinator_output(
        self,
        objnam: str,
        primary: int,
        secondary: int | None = None,
    ) -> None:
        changes = {"PRIM": str(primary)}
        if secondary is not None:
            changes["SEC"] = str(secondary)
        await self.request_changes(objnam, changes)

    async def set_circuit_state(self, objnam: str, active: bool) -> None:
        await self.request_changes(objnam, {"STATUS": "ON" if active else "OFF"})

    async def set_light_effect(self, objnam: str, effect: str) -> None:
        await self.request_changes(objnam, {"EFFECT": effect})

    async def set_heating_setpoint(self, objnam: str, target: int) -> None:
        await self.request_changes(objnam, {"LOTMP": str(target)})


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
    gateway._command_authority = PoolOSPhysicalCommandAuthority()
    gateway._command_authority.resolve_maintenance(False)
    gateway._command_authority.set_controller_mode("auto")

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


def test_pump_speed_expectation_tracks_configured_pmpcirc_not_actual_rpm(
    pump_object_factory,
    pump_circuit_object_factory,
) -> None:
    pump = pump_object_factory(objnam="PMP01")
    circuit = pump_circuit_object_factory(
        objnam="p0102",
        pump_id="PMP01",
        rpm_setpoint=2600,
    )
    gateway, recorder = _gateway([pump, circuit])
    gateway._command_authority.replace_native_truth(
        {(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT, "p0102"): 2600.0}
    )

    _run(gateway.async_set_pump_circuit_speed("p0102", 2900))
    observed_at = datetime.now(UTC)
    assert gateway._command_authority.correlate(
        concept="pump.rpm",
        native_object_id="PMP01",
        value=2900.0,
        observed_at=observed_at,
    ) is None
    assert gateway._command_authority.diagnostics(
        now=observed_at
    )["pending_expectation_count"] == 1
    assert gateway._command_authority.correlate(
        concept=POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        native_object_id="wrong-pmpcirc",
        value=2900.0,
        observed_at=observed_at,
    ) is None
    assert gateway._command_authority.correlate(
        concept=POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        native_object_id="p0102",
        value=2900.0,
        observed_at=observed_at,
    ) is not None
    assert recorder.calls == [("p0102", {"SPEED": "2900"})]


def test_no_op_manual_command_dispatches_without_leaving_expectation() -> None:
    gateway, recorder = _gateway([])
    gateway._command_authority.replace_native_truth(
        {("pool.raw_heater_id", "B1101"): "H0002"}
    )

    _run(gateway.async_set_body_heat_source("B1101", "H0002"))

    assert recorder.calls == [("B1101", {"HEATER": "H0002"})]
    assert gateway._command_authority.diagnostics(
        now=datetime.now(UTC)
    )["pending_expectation_count"] == 0
    assert gateway._command_authority.correlate(
        concept="pool.raw_heater_id",
        native_object_id="B1101",
        value="H0002",
        observed_at=datetime.now(UTC),
    ) is None


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
    assert (
        gateway._command_authority.diagnostics(
            now=datetime.now(UTC)
        )["pending_expectation_count"]
        == 0
    )


def test_queued_command_rechecks_maintenance_inside_command_lock() -> None:
    async def scenario() -> None:
        gateway, recorder = _gateway([])
        await gateway._command_lock.acquire()
        task = asyncio.create_task(
            gateway.async_set_body_heat_source("B1101", "H0002")
        )
        await asyncio.sleep(0)
        assert gateway._command_authority.diagnostics(
            now=datetime.now(UTC)
        )["pending_expectation_count"] == 1

        gateway._command_authority.resolve_maintenance(True)
        gateway._command_lock.release()
        with pytest.raises(
            ManualIntelliCenterCommandError,
            match="maintenance_mode",
        ):
            await task
        assert recorder.calls == []
        assert gateway._command_authority.diagnostics(
            now=datetime.now(UTC)
        )["pending_expectation_count"] == 0

    asyncio.run(scenario())


def test_already_dispatched_command_may_finish_after_maintenance_turns_on() -> None:
    class BlockingController(_RecordingController):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def request_changes(
            self, objnam: str, changes: dict[str, str]
        ) -> None:
            self.calls.append((objnam, dict(changes)))
            self.started.set()
            await self.release.wait()

    async def scenario() -> None:
        controller = BlockingController()
        gateway, _ = _gateway([], controller)
        task = asyncio.create_task(
            gateway.async_set_body_heat_source("B1101", "H0002")
        )
        await controller.started.wait()
        gateway._command_authority.resolve_maintenance(True)
        controller.release.set()
        receipt = await task
        assert receipt.value == "H0002"
        assert controller.calls == [("B1101", {"HEATER": "H0002"})]
        assert gateway._command_authority.diagnostics(
            now=datetime.now(UTC)
        )["pending_expectation_count"] == 0

    asyncio.run(scenario())


def test_maintenance_blocks_every_public_mutation_surface(
    chemistry_object_factory,
    pump_object_factory,
    pump_circuit_object_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chlorinator = chemistry_object_factory(
        objnam="CHR01",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=52,
        secondary_output=4,
    )
    pump = pump_object_factory(objnam="PMP01")
    circuit = pump_circuit_object_factory(
        objnam="p0102",
        pump_id="PMP01",
    )
    gateway, recorder = _gateway([chlorinator, pump, circuit])
    gateway._command_authority.resolve_maintenance(True)
    monkeypatch.setattr(manual_module, "LIGHT_EFFECTS", {"Romance": "ROMANCE"})

    operations = (
        gateway.async_set_body_active("B1101", True),
        gateway.async_set_body_active("B1202", True),
        gateway.async_set_circuit_state("C0002", True),
        gateway.async_set_circuit_state("C0003", True),
        gateway.async_set_circuit_state("C0004", True),
        gateway.async_set_circuit_state("FTR01", True),
        gateway.async_set_light_effect("C0002", "Romance"),
        gateway.async_set_body_heat_source("B1101", "H0002"),
        gateway.async_set_body_heat_source("B1202", "H0001"),
        gateway.async_set_intellichlor_output("B1101", 60),
        gateway.async_set_intellichlor_output("B1202", 5),
        gateway.async_set_heating_setpoint("B1101", 88),
        gateway.async_set_heating_setpoint("B1202", 100),
        gateway.async_set_pump_circuit_speed("p0102", 2900),
    )
    for operation in operations:
        with pytest.raises(
            ManualIntelliCenterCommandError,
            match="maintenance_mode",
        ):
            _run(operation)

    assert recorder.calls == []


@pytest.mark.parametrize(
    ("body_objnam", "percent", "expected"),
    (
        ("B1101", 0, ("CHR01", {"PRIM": "0"})),
        ("B1101", 100, ("CHR01", {"PRIM": "100"})),
        ("B1202", 0, ("CHR01", {"PRIM": "52", "SEC": "0"})),
        ("B1202", 100, ("CHR01", {"PRIM": "52", "SEC": "100"})),
    ),
)
def test_intellichlor_output_uses_proven_body_ordered_payload(
    chemistry_object_factory,
    body_objnam: str,
    percent: int,
    expected: tuple[str, dict[str, str]],
) -> None:
    chlorinator = chemistry_object_factory(
        objnam="CHR01",
        name="IntelliChlor",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=52,
        secondary_output=4,
    )
    gateway, recorder = _gateway([chlorinator])

    receipt = _run(
        gateway.async_set_intellichlor_output(body_objnam, percent)
    )

    assert recorder.calls == [expected]
    assert receipt.body_objnam == body_objnam
    assert receipt.operation == "intellichlor_output"
    assert receipt.value == percent


@pytest.mark.parametrize("value", (-1, 101, True, 52.5, "52"))
def test_intellichlor_output_rejects_invalid_values_before_delivery(
    chemistry_object_factory,
    value: object,
) -> None:
    chlorinator = chemistry_object_factory(
        objnam="CHR01",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=52,
        secondary_output=4,
    )
    gateway, recorder = _gateway([chlorinator])

    with pytest.raises(ValueError):
        _run(gateway.async_set_intellichlor_output("B1101", value))

    assert recorder.calls == []


def test_intellichlor_output_fails_closed_on_missing_or_ambiguous_object(
    chemistry_object_factory,
) -> None:
    first = chemistry_object_factory(
        objnam="CHR01",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=52,
        secondary_output=4,
    )
    second = chemistry_object_factory(
        objnam="CHR02",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=50,
        secondary_output=5,
    )

    for objects in ([], [first, second]):
        gateway, recorder = _gateway(objects)
        with pytest.raises(
            ManualIntelliCenterCommandError,
            match="exactly one commissioned IntelliChlor",
        ):
            _run(gateway.async_set_intellichlor_output("B1101", 50))
        assert recorder.calls == []


def test_spa_output_fails_closed_when_primary_readback_is_unknown(
    chemistry_object_factory,
) -> None:
    chlorinator = chemistry_object_factory(
        objnam="CHR01",
        subtype="ICHLOR",
        body_ids="B1101 B1202",
        primary_output=None,
        secondary_output=4,
    )
    gateway, recorder = _gateway([chlorinator])

    with pytest.raises(
        ManualIntelliCenterCommandError,
        match="Pool output is unavailable",
    ):
        _run(gateway.async_set_intellichlor_output("B1202", 5))

    assert recorder.calls == []


def test_intellichlor_body_order_not_primary_secondary_words_controls_mapping(
    chemistry_object_factory,
) -> None:
    chlorinator = chemistry_object_factory(
        objnam="CHR01",
        subtype="ICHLOR",
        body_ids="B1202 B1101",
        primary_output=4,
        secondary_output=52,
    )
    gateway, recorder = _gateway([chlorinator])

    _run(gateway.async_set_intellichlor_output("B1202", 8))
    _run(gateway.async_set_intellichlor_output("B1101", 60))

    assert recorder.calls == [
        ("CHR01", {"PRIM": "8"}),
        ("CHR01", {"PRIM": "4", "SEC": "60"}),
    ]
