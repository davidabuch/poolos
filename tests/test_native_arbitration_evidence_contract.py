"""One native read contract across verification, ownership and completion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace

import pytest

from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
from test_independent_intellicenter_transport import (
    FakeModelController, _load_module, _objects,
)
from test_native_coordinator_refresh_coalescing import _load_coordinator_module

ROLES = (
    "owned_pump_session", "filtration_topology", "cleanup_topology",
    "thermal_topology", "reset_baseline", "thermal_safety_topology",
)


def arbitration_objects():
    objects = dict(_objects())
    objects["B1101"].update(HEATER="H0002", HTMODE="1")
    objects["B1102"] = dict(objects["B1101"], SNAME="Spa", STATUS="OFF", HEATER="00000", HTMODE="0")
    objects["p0102"] = objects.pop("PC001")
    objects["p0102"].update(CIRCUIT="C0006", SELECT="RPM", PARENT="P0001", SPEED=2900)
    objects["p0198"] = dict(objects["p0102"], CIRCUIT="C0001")
    objects["P0001"].update(RPM=2900)
    for native_id, name in (("C0002", "Solar"), ("C0003", "Waterfall"), ("C0004", "Jets"), ("C0005", "Slide")):
        objects[native_id] = dict(objects["C0001"], SNAME=name, USE=name, STATUS="OFF")
    return objects


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("fault", [None, "missing_spa", "missing_source", "missing_pump", "missing_circuit", "duplicate_body", "missing_configured"])
def test_every_lifecycle_requires_one_complete_unchanged_arbitration_batch(monkeypatch, role, fault):
    async def scenario():
        module = _load_module(monkeypatch)
        clock = [datetime(2026, 10, 3, 18, tzinfo=UTC)]

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
            if not transport._connection_reconciliation_tasks and not transport._body_metadata_refresh_tasks:
                break
        before = transport.read_snapshot()
        clock[0] += timedelta(seconds=180)
        boundary = clock[0]
        requests, publications = [], []
        transport._set_snapshot_update_callback(lambda: publications.append(transport.read_snapshot()))

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            kind = extra["condition"].split(" = ")[1]
            requests.append(kind)
            keys = extra["objectList"][0]["keys"]
            entries = [{"objnam": obj.objnam, "params": {key: obj[key] for key in keys if obj[key] is not None}}
                       for obj in transport._model.get_by_type(kind)]
            if kind == "BODY":
                if fault == "missing_spa":
                    entries = entries[:1]
                elif fault == "missing_source":
                    entries[0]["params"].pop("HEATER", None)
                elif fault == "duplicate_body":
                    entries.append(entries[0])
            if kind == "PUMP" and fault == "missing_pump":
                entries[0]["params"].pop("RPM", None)
            if kind == "CIRCUIT" and fault == "missing_circuit":
                entries[-1]["params"].pop("STATUS", None)
            if kind == "PMPCIRC" and fault == "missing_configured":
                entries[0]["params"].pop("SPEED", None)
            clock[0] += timedelta(seconds=1)
            return {"objectList": entries}

        transport._controller.send_cmd = read
        coordinator_type = _load_coordinator_module().PoolOSCoordinator
        coordinator = SimpleNamespace(independent_intellicenter_transport=transport, _unloading=False)
        coordinator._async_refresh_native_runtime_evidence = partial(coordinator_type._async_refresh_native_runtime_evidence, coordinator)
        try:
            result = await getattr(coordinator_type, f"async_refresh_native_{role}_evidence")(coordinator)
            if fault:
                assert not result, "Partial/duplicate replies cannot publish a successful arbitration read"
                assert publications == []
                assert transport.read_snapshot() is before
                assert transport.diagnostics(generated_at=clock[0])["last_error_code"].startswith("ARBITRATION_NATIVE_")
                return
            assert result
            assert {"PMPCIRC", "PUMP", "BODY", "SENSE", "CIRCUIT", "SYSTEM"} <= set(requests)
            assert len(publications) == 1
            mapped = {obs.observation_id: obs for obs in NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0]).observations}
            concepts = (
                "pool.active", "spa.active", "pool.raw_heater_id", "spa.raw_heater_id",
                "pool.raw_htmode", "spa.raw_htmode", "pump.rpm",
                "pool.pump_circuit.configured_speed_rpm", "spa.pump_circuit.configured_speed_rpm",
                "solar.active", "waterfall.active", "jets.active", "slide.active",
            )
            assert all(mapped[c].observed_at == boundary for c in concepts)
            assert transport.read_snapshot().inventory_observed_at == boundary
            # Truthful rereads have no historical command or ownership origin.
            assert all("Set" not in operation for operation in transport._controller.sent_operations)
        finally:
            await transport.async_stop()

    asyncio.run(scenario())


def test_overlapping_lifecycle_reads_are_serialized_and_cancellation_releases_contract(monkeypatch):
    async def scenario():
        module = _load_module(monkeypatch)
        FakeModelController.initial_objects = tuple(arbitration_objects().items())
        transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
        await transport.async_start()
        for _ in range(40):
            await asyncio.sleep(0)
            if not transport._connection_reconciliation_tasks and not transport._body_metadata_refresh_tasks:
                break
        calls = []
        gate = asyncio.Event()
        started = asyncio.Event()

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            kind = extra["condition"].split(" = ")[1]
            calls.append(kind)
            started.set()
            await gate.wait()
            await asyncio.sleep(0)
            keys = extra["objectList"][0]["keys"]
            return {"objectList": [{"objnam": obj.objnam, "params": {k: obj[k] for k in keys if obj[k] is not None}}
                                   for obj in transport._model.get_by_type(kind)]}

        transport._controller.send_cmd = read
        before = transport.read_snapshot()
        cancelled = asyncio.create_task(transport._async_refresh_owned_pump_session_evidence())
        await started.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert transport.read_snapshot() is before
        calls.clear()
        gate.set()
        try:
            assert await asyncio.gather(
                transport._async_refresh_owned_pump_session_evidence(),
                transport._async_refresh_owned_pump_session_evidence(cleanup_topology=True),
            ) == [True, True]
            assert calls == ["PMPCIRC", "PUMP", "SENSE", "BODY", "CIRCUIT", "SYSTEM"] * 2
        finally:
            await transport.async_stop()

    asyncio.run(scenario())


def test_residual_loop_keeps_complete_evidence_current_beyond_freshness_window(monkeypatch):
    from test_home_assistant_thermal_automatic_runtime import _load_module as load_runtime, _runtime

    async def scenario():
        module = _load_module(monkeypatch)
        clock = [datetime(2026, 10, 3, 18, tzinfo=UTC)]

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
            if not transport._connection_reconciliation_tasks and not transport._body_metadata_refresh_tasks:
                break
        started = clock[0]
        runtime_module = load_runtime()
        monkeypatch.setattr(runtime_module, "_OWNED_PUMP_SESSION_REOBSERVATION_INTERVAL_SECONDS", 0)
        runtime, _, _, coordinator, driver = _runtime(runtime_module)
        ownership = SimpleNamespace(residual_termination=SimpleNamespace(entitlement_id="fixed-residual"))
        runtime.orchestrator = SimpleNamespace(ownership=ownership)
        driver.requested_enabled = True
        coordinator_type = _load_coordinator_module().PoolOSCoordinator
        coordinator.independent_intellicenter_transport = transport
        coordinator._unloading = False
        coordinator._async_refresh_native_runtime_evidence = partial(coordinator_type._async_refresh_native_runtime_evidence, coordinator)
        reads = []

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            kind = extra["condition"].split(" = ")[1]
            keys = extra["objectList"][0]["keys"]
            return {"objectList": [{"objnam": obj.objnam, "params": {k: obj[k] for k in keys if obj[k] is not None}}
                                   for obj in transport._model.get_by_type(kind)]}

        transport._controller.send_cmd = read

        async def refresh():
            clock[0] += timedelta(seconds=15)
            assert await coordinator_type.async_refresh_native_cleanup_topology_evidence(coordinator)
            mapped = {o.observation_id: o for o in NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0]).observations}
            assert all(mapped[c].observed_at == clock[0] for c in (
                "pool.active", "spa.active", "pump.rpm", "pool.raw_heater_id", "spa.raw_heater_id",
                "pool.pump_circuit.configured_speed_rpm", "solar.active", "waterfall.active", "jets.active", "slide.active",
            ))
            reads.append(clock[0])
            if len(reads) == 12:
                ownership.residual_termination = None
            return True

        coordinator.async_refresh_native_cleanup_topology_evidence = refresh
        try:
            runtime._sync_cleanup_topology_reobservation()
            await asyncio.wait_for(runtime._cleanup_topology_reobservation_task, timeout=1)
            assert reads[-1] - started == timedelta(seconds=180)
            assert driver.cleanup_provenance is None and driver.processed == []
            assert runtime._cleanup_topology_reobservation_task is None
            runtime._sync_cleanup_topology_reobservation()
            assert len(reads) == 12
        finally:
            await transport.async_stop()

    asyncio.run(scenario())
