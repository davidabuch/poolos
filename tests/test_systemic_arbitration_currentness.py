"""Native rereads must tolerate compatible telemetry without renewing old facts."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
from test_independent_intellicenter_transport import FakeModelController, _load_module
from test_native_arbitration_evidence_contract import arbitration_objects
from test_thermal_automatic_execution import NOW


@asynccontextmanager
async def native_loop(monkeypatch):
    module = _load_module(monkeypatch)
    clock = [NOW]
    noise = [False]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(module, "datetime", Clock)
    objects = arbitration_objects()
    objects["B1101"].update(STATUS="OFF", HEATER="00000", HTMODE="0", LSTTMP=88)
    objects["B1102"].update(STATUS="OFF", HEATER="00000", HTMODE="0")
    objects["P0001"].update(RPM=0)
    objects["p0102"].update(SPEED=2600)
    FakeModelController.initial_objects = tuple(objects.items())
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    await transport.async_start()
    for _ in range(40):
        await asyncio.sleep(0)

    async def read(cmd, extra=None):
        assert cmd == "GetParamList"
        kind = extra["condition"].split(" = ")[1]
        if noise[0] and kind == "PUMP":
            transport._controller._apply_updates([{"objnam": "P0001",
                "params": {"RPM": transport._model["P0001"]["RPM"]}}])
        keys = extra["objectList"][0]["keys"]
        return {"objectList": [{"objnam": obj.objnam,
                "params": {key: obj[key] for key in keys if obj[key] is not None}}
                for obj in transport._model.get_by_type(kind)]}

    transport._controller.send_cmd = read

    async def capture():
        # Deliberately consume whatever the real publication path produced;
        # failed reads must not be papered over by stamping fixture evidence.
        await transport._async_refresh_arbitration_evidence()
        return NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0])

    try:
        yield transport, clock, noise, capture
    finally:
        await transport.async_stop()


@pytest.mark.parametrize("notification", ["pump", "temperature", "unchanged_body"])
def test_complete_read_survives_compatible_interleaved_native_publication(monkeypatch, notification):
    async def scenario():
        module = _load_module(monkeypatch)
        clock = [NOW]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]

        monkeypatch.setattr(module, "datetime", Clock)
        FakeModelController.initial_objects = tuple(arbitration_objects().items())
        transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
        await transport.async_start()
        for _ in range(40):
            await asyncio.sleep(0)
        clock[0] += timedelta(seconds=121)
        boundary = clock[0]
        queries = []

        async def read(cmd, extra=None):
            kind = extra["condition"].split(" = ")[1]
            queries.append(kind)
            if kind == "PUMP":
                clock[0] += timedelta(seconds=1)
                native_id, field = {
                    "pump": ("P0001", "RPM"),
                    "temperature": ("S0001", "SOURCE"),
                    "unchanged_body": ("B1101", "STATUS"),
                }[notification]
                transport._controller._apply_updates([
                    {"objnam": native_id, "params": {field: transport._model[native_id][field]}}
                ])
            keys = extra["objectList"][0]["keys"]
            return {"objectList": [{"objnam": obj.objnam,
                    "params": {key: obj[key] for key in keys if obj[key] is not None}}
                    for obj in transport._model.get_by_type(kind)]}

        transport._controller.send_cmd = read
        try:
            result = await transport._async_refresh_arbitration_evidence()
            mapped = {o.observation_id: o for o in NativeIntelliCenterReadAdapter().capture(
                transport, generated_at=clock[0]).observations}
            assert result, f"Complete compatible read was discarded after {queries}"
            for concept in ("pool.active", "spa.active", "pump.rpm", "solar.active",
                            "pool.raw_heater_id", "spa.raw_heater_id", "waterfall.active",
                            "jets.active", "slide.active"):
                assert mapped[concept].observed_at >= boundary, concept
            assert queries == ["PMPCIRC", "PUMP", "SENSE", "BODY", "CIRCUIT", "SYSTEM"]
        finally:
            await transport.async_stop()

    asyncio.run(scenario())


def test_filtration_completion_during_native_callbacks_reaches_verified_off(monkeypatch):
    from poolos.integration import SetBodyActive, SetPumpSpeed
    from test_filtration_automatic_execution import _enabled_driver, _frame

    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            driver, delivery, factory = _enabled_driver()
            count = 0
            for epoch in range(45):
                clock[0] += timedelta(seconds=5)
                native = await capture()
                mapped = {o.observation_id: o for o in native.observations}
                frame = _frame(clock[0], pool=mapped["pool.active"].value,
                    rpm=int(mapped["pump.rpm"].value),
                    configured=int(mapped["pool.pump_circuit.configured_speed_rpm"].value),
                    satisfied=epoch >= 35)
                frame = replace(frame, observations=tuple(mapped[o.observation_id]
                    for o in frame.observations))
                delivery.issued_at = clock[0]
                result = await driver.process_epoch(frame, delivery_factory=factory)
                for op in delivery.operations[count:]:
                    if isinstance(op, SetBodyActive):
                        transport._model["B1101"].properties["STATUS"] = "ON" if op.active else "OFF"
                        transport._model["P0001"].properties["RPM"] = 3000 if op.active else 0
                    elif isinstance(op, SetPumpSpeed):
                        transport._model["P0001"].properties["RPM"] = op.rpm
                        transport._model["p0102"].properties["SPEED"] = op.rpm
                count = len(delivery.operations)
                if epoch == 3:
                    assert driver.ownership.filtration_lease.verified
                    noise[0] = True
            assert frame.filtration.total_remaining_runtime == timedelta(0)
            assert transport._model["B1101"]["STATUS"] == "OFF", result
            assert transport._model["P0001"]["RPM"] == 0
            assert driver.ownership.filtration_lease is None
            assert len(delivery.operations) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("flush", [False, True])
def test_pool_probe_retains_accepted_body_and_pump_during_native_callbacks(monkeypatch, flush):
    from poolos.integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed
    from poolos.thermal_automatic_execution import ThermalAutomaticDriverState, ThermalAutomaticExecutionDriver
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from poolos.thermal_runtime_assessment import ThermalRequestedMode, ThermalRuntimeEvaluator
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus
    from test_thermal_automatic_execution import _frame, FakeDelivery, FakeDeliveryFactory

    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            orchestrator = ThermalRuntimeOrchestrator()
            driver = ThermalAutomaticExecutionDriver(orchestrator)
            evaluator = ThermalRuntimeEvaluator()
            delivery = FakeDelivery()
            factory = FakeDeliveryFactory(delivery, driver=driver)
            count = 0
            probe_origin = None
            for epoch in range(220):
                clock[0] += timedelta(seconds=5)
                temperature = ([102, 99, 96, 91, 88][min(epoch, 4)] if flush else 88)
                transport._model["B1101"].properties["LSTTMP"] = temperature
                native = await capture()
                mapped = {o.observation_id: o for o in native.observations}
                frame = _frame(orchestrator, clock[0], pool_active=mapped["pool.active"].value,
                    pump_rpm=int(mapped["pump.rpm"].value),
                    configured_rpm=int(mapped["pool.pump_circuit.configured_speed_rpm"].value),
                    pool_heater=mapped["pool.raw_heater_id"].value,
                    solar_active=mapped["solar.active"].value,
                    pool_temperature=temperature, pool_target=90 if epoch < 50 else 78,
                    solar_temperature=93 if epoch < 18 else 125,
                    mode=ThermalRequestedMode.SOLAR, evaluator=evaluator, driver=driver,
                    real_probe_continuity=True,
                    filtration_remaining=timedelta(0),
                    observation_times={c: o.observed_at for c, o in mapped.items()})
                if epoch == 0:
                    driver.note_disabled_epoch(frame)
                    driver.set_enabled(True, changed_at=clock[0], current_epoch_identity=frame.epoch_identity)
                    continue
                result = await driver.process_epoch(frame, delivery_factory=factory)
                for op in delivery.calls[count:]:
                    if isinstance(op, SetBodyActive):
                        transport._model["B1101"].properties["STATUS"] = "ON" if op.active else "OFF"
                        transport._model["P0001"].properties["RPM"] = 3000 if op.active else 0
                    elif isinstance(op, SetPumpSpeed):
                        transport._model["P0001"].properties["RPM"] = op.rpm
                        transport._model["p0102"].properties["SPEED"] = op.rpm
                    elif isinstance(op, SetHeatMode):
                        assert op.mode is not PhysicalHeatMode.GAS
                        selected = op.mode is PhysicalHeatMode.SOLAR
                        transport._model["B1101"].properties.update(
                            HEATER="H0002" if selected else "00000",
                            HTMODE="1" if selected else "0",
                        )
                        transport._model["C0002"].properties["STATUS"] = "ON" if selected else "OFF"
                count = len(delivery.calls)
                if epoch == 2:
                    assert orchestrator.ownership.state.lease.body_activation is not None
                    noise[0] = True
                if epoch == 17:
                    lease = orchestrator.ownership.state.lease
                    assert lease.status is ThermalRuntimeOwnershipStatus.OWNED, result
                    assert lease.owns_body and lease.owns_pump_setpoint
                    assert transport._model["P0001"]["RPM"] == 1500
                    assert driver.probe_execution_evidence().phase.value == "acquiring"
                    probe_origin = lease.body_activation
                if epoch == 49:
                    lease = orchestrator.ownership.state.lease
                    assert result.state is ThermalAutomaticDriverState.CONVERGED, result
                    assert lease.status is ThermalRuntimeOwnershipStatus.OWNED
                    assert lease.body_activation == probe_origin
                    assert lease.owns_body and lease.owns_pump_setpoint and lease.owns_heat_source
                    assert transport._model["P0001"]["RPM"] == 2900
                    assert transport._model["C0002"]["STATUS"] == "ON"
            assert transport._model["B1101"]["STATUS"] == "OFF", result
            assert transport._model["P0001"]["RPM"] == 0
            assert transport._model["B1101"]["HEATER"] == "00000"
            assert transport._model["C0002"]["STATUS"] == "OFF"
            assert driver.cleanup_provenance is None
            assert orchestrator.ownership.residual_termination is None
            assert not driver._reenable_required
            assert orchestrator.ownership.state.status is not ThermalRuntimeOwnershipStatus.OWNED

    asyncio.run(scenario())


def test_pending_filtration_temporarily_missing_circuit_retains_fixed_attempt():
    from test_filtration_automatic_execution import _enabled_driver, _frame
    from poolos.filtration_automatic_execution import FiltrationAutomaticDriverState

    async def scenario():
        driver, delivery, factory = _enabled_driver()
        at = delivery.issued_at
        await driver.process_epoch(_frame(at, pool=False, rpm=0, configured=2600), delivery_factory=factory)
        await driver.process_epoch(_frame(at + timedelta(seconds=1), pool=True,
            rpm=3000, configured=2600), delivery_factory=factory)
        lease = driver.ownership.filtration_lease
        attempt = driver.attempt
        result = await driver.process_epoch(_frame(at + timedelta(seconds=2), pool=True,
            rpm=2600, configured=2600, missing=("waterfall.active",)), delivery_factory=factory)
        assert result.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION, result
        assert driver.attempt is attempt
        retained = driver.ownership.filtration_lease
        assert retained.lease_id == lease.lease_id and retained.generation == lease.generation
        assert retained.body_activation == lease.body_activation
        assert retained.pump_setpoint == lease.pump_setpoint
        assert len(delivery.operations) == 2
        result = await driver.process_epoch(_frame(at + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600), delivery_factory=factory)
        assert result.state is FiltrationAutomaticDriverState.OWNED
        await driver.process_epoch(_frame(at + timedelta(seconds=4), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        await driver.process_epoch(_frame(at + timedelta(seconds=5), pool=False,
            rpm=0, configured=2600, satisfied=True), delivery_factory=factory)
        assert driver.ownership.filtration_lease is None
        assert len(delivery.operations) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["body", "pump", "source", "shared", "assignment", "returned_assignment", "returned_mode", "generation", "disconnect"])
def test_contradictory_or_invalidated_read_cannot_refresh_sibling_evidence(monkeypatch, domain):
    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, noise, _capture):
            clock[0] += timedelta(seconds=121)
            before = transport.read_snapshot()
            read = transport._controller.send_cmd
            async def hostile(cmd, extra=None):
                kind = extra["condition"].split(" = ")[1]
                response = await read(cmd, extra)
                if kind == "PMPCIRC" and domain in {"returned_assignment", "returned_mode"}:
                    response["objectList"][0]["params"].update(
                        {"CIRCUIT": "C0001"} if domain == "returned_assignment" else {"SELECT": "GPM"})
                if kind == "SYSTEM":
                    clock[0] += timedelta(seconds=1)
                    if domain == "generation":
                        transport._discovery_generation += 1
                    elif domain == "disconnect":
                        transport._on_disconnected(None)
                    elif not domain.startswith("returned_"):
                        native_id, field, value = {
                            "body": ("B1101", "STATUS", "ON"),
                            "pump": ("P0001", "RPM", 3200),
                            "source": ("B1101", "HEATER", "H0001"),
                            "shared": ("C0003", "STATUS", "ON"),
                            "assignment": ("p0102", "CIRCUIT", "C0001"),
                        }[domain]
                        transport._controller._apply_updates([{"objnam": native_id, "params": {field: value}}])
                return response
            transport._controller.send_cmd = hostile
            assert not await transport._async_refresh_arbitration_evidence()
            assert transport._arbitration_evidence.failure_reason is not None
            assert not transport._arbitration_evidence.admits_boundary(NOW, generation=transport.discovery_generation)
            # The truthful intervening callback remains visible; the discarded
            # batch cannot stamp unrelated OFF circuits as newly observed.
            current = transport.read_snapshot() if transport.connected else transport.latest_snapshot
            old_jets = next(o for o in before.raw_inventory if o.native_id == "C0004")
            new_jets = next(o for o in current.raw_inventory if o.native_id == "C0004")
            assert new_jets == old_jets

    asyncio.run(scenario())


@pytest.mark.parametrize("delay", [0, 1, 15, 29, 31, 121])
def test_read_completion_cannot_renew_start_or_admit_intervening_command(monkeypatch, delay):
    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, _noise, capture):
            clock[0] += timedelta(seconds=1)
            start = clock[0]
            read = transport._controller.send_cmd
            async def delayed(cmd, extra=None):
                if extra["condition"].endswith("SYSTEM"):
                    clock[0] += timedelta(seconds=delay)
                return await read(cmd, extra)
            transport._controller.send_cmd = delayed
            snapshot = await capture()
            record = snapshot.transport_snapshot.arbitration_evidence
            assert record.started_at == start
            assert record.completed_at == start + timedelta(seconds=delay)
            assert record.required_fields and record.topology_identity
            assert record.admits_boundary(start - timedelta(seconds=1), generation=transport.discovery_generation)
            assert not record.admits_boundary(start, generation=transport.discovery_generation)
            assert not record.admits_boundary(start + timedelta(seconds=1), generation=transport.discovery_generation)
            assert not record.admits_boundary(NOW, generation=transport.discovery_generation + 1)
            assert all(o.observed_at <= start for o in snapshot.observations)
            assert record.diagnostics()["authority"] == "none"

    asyncio.run(scenario())


def test_pending_filtration_unusable_evidence_expires_at_original_deadline():
    from test_filtration_automatic_execution import _enabled_driver, _frame
    from poolos.filtration_automatic_execution import FiltrationAutomaticDriverState
    from poolos.ownership_evidence import OwnershipDomain, OwnershipHealth

    async def scenario():
        driver, delivery, factory = _enabled_driver()
        at = delivery.issued_at
        await driver.process_epoch(_frame(at, pool=False, rpm=0, configured=2600), delivery_factory=factory)
        await driver.process_epoch(_frame(at + timedelta(seconds=1), pool=True,
            rpm=3000, configured=2600), delivery_factory=factory)
        attempt = driver.attempt
        for second in (2, 15, 29):
            await driver.process_epoch(_frame(at + timedelta(seconds=second), pool=True,
                rpm=2600, configured=2600, missing=("waterfall.active",)), delivery_factory=factory)
            assert driver.attempt is attempt
        result = await driver.process_epoch(_frame(attempt.deadline, pool=True,
            rpm=2600, configured=2600, missing=("waterfall.active",)), delivery_factory=factory)
        assert result.state is FiltrationAutomaticDriverState.FAILED
        assert result.blocker == "automatic_filtration_verification_timed_out"
        lease = driver.ownership.filtration_lease
        assert lease.body_activation is not None and lease.body_verified
        assert lease.domain_state(OwnershipDomain.PUMP).health is OwnershipHealth.FAULTED
        assert len(delivery.operations) == 2

    asyncio.run(scenario())


def test_pending_filtration_has_read_retry_owner_before_full_verification(monkeypatch):
    from test_home_assistant_filtration_automatic_runtime import _load_module as load_runtime, _runtime
    from test_filtration_automatic_execution import _enabled_driver, _frame

    async def scenario():
        runtime, _hass, _authority, _coordinator, _fake = _runtime(load_runtime())
        driver, delivery, factory = _enabled_driver()
        at = delivery.issued_at
        await driver.process_epoch(_frame(at, pool=False, rpm=0, configured=2600), delivery_factory=factory)
        runtime.driver = driver
        runtime.ownership = driver.ownership
        assert not driver.ownership.filtration_lease.verified
        assert runtime._owned_filtration_reobservation_required()
        calls = []
        sleep = asyncio.sleep

        async def next_epoch(_seconds):
            await sleep(0)

        async def read():
            calls.append(driver.attempt.receipt_id)
            if len(calls) == 1:
                return False
            # Fresh evidence can resume the same receipt; do not manufacture a
            # new command, generation or deadline merely to retry observation.
            driver.attempt = None
            return True

        runtime.coordinator.async_refresh_native_owned_pump_session_evidence = read
        monkeypatch.setattr(asyncio, "sleep", next_epoch)
        await runtime._owned_filtration_reobservation_loop()
        assert len(calls) == 2 and calls[0] == calls[1]
        assert len(delivery.operations) == 1
        assert not runtime._owned_filtration_reobservation_required()
        runtime.prepare_unload()
        assert not runtime._owned_filtration_reobservation_required()

    asyncio.run(scenario())


@pytest.mark.parametrize("native_id,field,value", [
    ("S0001", "SOURCE", 88), ("B1101", "LSTTMP", 88), ("P0001", "PWR", 213),
])
def test_newer_measurement_during_read_does_not_starve_topology_or_get_overwritten(
    monkeypatch, native_id, field, value,
):
    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, _noise, capture):
            clock[0] += timedelta(seconds=121)
            start = clock[0]
            old = transport._model[native_id][field]
            new_value = value if old != value else value + 1
            read = transport._controller.send_cmd
            async def burst(cmd, extra=None):
                response = await read(cmd, extra)
                if extra["condition"].endswith("SYSTEM"):
                    clock[0] += timedelta(seconds=1)
                    transport._controller._apply_updates([
                        {"objnam": native_id, "params": {field: new_value}}])
                return response
            transport._controller.send_cmd = burst
            snapshot = await capture()
            assert snapshot.transport_snapshot.arbitration_evidence.failure_reason is None
            assert snapshot.transport_snapshot.arbitration_evidence.completed_at is not None
            assert transport._model[native_id][field] == new_value
            assert transport._attribute_observed_at[(native_id, field)] == clock[0]
            mapped = {o.observation_id: o for o in snapshot.observations}
            assert mapped["waterfall.active"].observed_at == start
            assert mapped["spa.active"].observed_at == start

    asyncio.run(scenario())


def test_cancelled_native_read_has_no_completed_generation(monkeypatch):
    async def scenario():
        async with native_loop(monkeypatch) as (transport, clock, _noise, _capture):
            started = asyncio.Event()
            gate = asyncio.Event()
            before = transport.read_snapshot()
            read = transport._controller.send_cmd
            async def pending(cmd, extra=None):
                started.set()
                await gate.wait()
                return await read(cmd, extra)
            transport._controller.send_cmd = pending
            task = asyncio.create_task(transport._async_refresh_arbitration_evidence())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            record = transport._arbitration_evidence
            assert record.failure_reason == "ARBITRATION_NATIVE_READ_CANCELLED"
            assert not record.admits_boundary(NOW - timedelta(seconds=1), generation=transport.discovery_generation)
            assert transport.read_snapshot() is before
            assert not transport._arbitration_read_lock.locked()

    asyncio.run(scenario())


def test_reset_authority_reopen_preserves_quarantined_thermal_gate():
    from test_home_assistant_thermal_automatic_runtime import _load_module as load_runtime, _runtime
    from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator

    runtime, _hass, _authority, _coordinator, _fake = _runtime(load_runtime())
    runtime.orchestrator = ThermalRuntimeOrchestrator()
    runtime.driver = ThermalAutomaticExecutionDriver(runtime.orchestrator)
    runtime._desired_enabled = False
    generation = runtime._authority_epoch_generation
    runtime.driver.restrictive_authority_changed(changed_at=NOW)
    runtime.orchestrator.reset_session_authority(reset_at=NOW)
    runtime.note_reset_authority_reopened()
    assert not runtime.driver.requested_enabled
    assert not runtime.enabled
    assert runtime._authority_epoch_generation == generation + 1
    assert not runtime._owned_pump_session_reobservation_required()


def test_prediction_matrix_accounts_for_every_requested_case_and_real_tests():
    import ast
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    matrix = json.loads((root / "docs/ownership/systemic_currentness_prediction_matrix.json").read_text())
    ids = [case["id"] for case in matrix["cases"]]
    assert ids == ([chr(n) for n in range(ord("A"), ord("Z") + 1)]
                   + ["A" + chr(n) for n in range(ord("A"), ord("Z") + 1)]
                   + ["B" + chr(n) for n in range(ord("A"), ord("Z") + 1)]
                   + ["C" + chr(n) for n in range(ord("A"), ord("J") + 1)])
    for case in matrix["cases"]:
        assert case["accepted_case"] and case["mechanism"] and case["coverage"]
        for ref in case["regressions"]:
            path, name = ref.split("::")
            functions = {n.name for n in ast.walk(ast.parse((root / path).read_text()))
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assert name in functions, ref
