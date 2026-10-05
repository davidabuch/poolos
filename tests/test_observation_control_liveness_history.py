"""Historical publication clocks cannot replace genuine idle-state observation.

The reference projection freezes v0.11.88/99d5585's adapter rule: every canonical
concept uses transport.observed_at. It is test evidence, not a legacy executor.
Current sequences traverse the real transport, adapter and coordinator methods.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
from poolos.native_observation_freshness import NATIVE_STEADY_STATE_FRESHNESS
from test_native_coordinator_refresh_coalescing import _load_coordinator_module
from test_systemic_arbitration_currentness import native_loop


def historical_v088_projection(native, transport):
    """Freeze 99d5585 adapter's shared transport-clock rule for comparison."""
    return tuple(replace(item, observed_at=transport.observed_at) for item in native.observations)


def fresh(item, at):
    return timedelta(0) <= at - item.observed_at <= NATIVE_STEADY_STATE_FRESHNESS.max_age


def coordinator_harness(monkeypatch, transport, native, clock):
    coordinator_type = _load_coordinator_module().PoolOSCoordinator

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setitem(coordinator_type._async_update_data.__globals__, "datetime", Clock)
    coordinator = object.__new__(coordinator_type)
    coordinator._unloading = False
    coordinator.data = None
    coordinator._observation_lock = asyncio.Lock()
    coordinator._reconciliation_refresh_count = 0
    coordinator.independent_intellicenter_transport = transport
    coordinator.native_intellicenter_snapshot = native

    async def observe(*, observed_at, trigger):
        assert trigger == "periodic_reconciliation"
        mapped = NativeIntelliCenterReadAdapter().capture(transport, generated_at=observed_at)
        coordinator.native_intellicenter_snapshot = mapped
        coordinator.data = mapped
        return mapped

    coordinator._async_observe = observe
    return coordinator


@pytest.mark.parametrize("callbacks", [False, True])
def test_idle_reconciliation_restores_historical_evidence_liveness_truthfully(monkeypatch, callbacks):
    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            initial = await capture()
            coordinator = coordinator_harness(monkeypatch, transport, initial, clock)
            start = clock[0]
            for _ in range(8):
                clock[0] += timedelta(seconds=30)
                if callbacks:
                    # Motor keepalive on idle equipment used to stamp ALL facts.
                    transport._controller._apply_updates([
                        {"objnam": "P0001", "params": {"RPM": 0}}
                    ])
                current = NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0])
                historical = historical_v088_projection(current, transport.latest_snapshot)
                if clock[0] - start > timedelta(seconds=120):
                    body = next(o for o in current.observations if o.observation_id == "pool.active")
                    # On the old rule a motor callback renews BODY without a BODY
                    # read; modern truthful clocks correctly refuse that inference.
                    assert not fresh(body, clock[0]) or body.observed_at > start
                    if callbacks:
                        assert fresh(next(o for o in historical if o.observation_id == "pool.active"), clock[0])
                mapped = await coordinator._async_update_data()
                values = {o.observation_id: o for o in mapped.observations}
                for concept in ("pool.active", "spa.active", "pump.rpm", "pool.raw_heater_id",
                                "spa.raw_heater_id", "solar.active", "waterfall.active", "jets.active", "slide.active"):
                    assert fresh(values[concept], clock[0]), (concept, values[concept].observed_at, clock[0])
                record = transport._last_successful_arbitration_evidence
                assert values["pool.active"].observed_at == record.started_at
                assert values["pool.active"].value is False
                assert values["spa.active"].value is False
                assert values["pump.rpm"].value == 0
                # A read must not change native configured intent or issue a
                # physical command: native_loop's send_cmd accepts GetParamList only.
                assert transport._model["p0102"]["SPEED"] == 2600
            assert (
                transport._last_successful_arbitration_evidence.started_at
                == start + timedelta(seconds=180)
            )
            assert coordinator._reconciliation_refresh_count == 8
            assert coordinator.data.generated_at == clock[0]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["partial", "disconnected"])
def test_idle_failed_reread_cannot_renew_old_facts(monkeypatch, failure):
    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            native = await capture()
            coordinator = coordinator_harness(monkeypatch, transport, native, clock)
            original = {o.observation_id: o.observed_at for o in native.observations}
            clock[0] += timedelta(seconds=121)
            if failure == "partial":
                original_send = transport._controller.send_cmd
                async def partial(cmd, extra=None):
                    if extra["condition"].endswith("BODY"):
                        return {"objectList": []}
                    return await original_send(cmd, extra)
                transport._controller.send_cmd = partial
            else:
                coordinator.independent_intellicenter_transport = None
            mapped = await coordinator._async_update_data()
            by_id = {o.observation_id: o for o in mapped.observations}
            assert by_id["pool.active"].observed_at == original["pool.active"]
            assert not fresh(by_id["pool.active"], clock[0])
    asyncio.run(run())


def test_stop_boundary_prevents_idle_read_and_publication(monkeypatch):
    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            native = await capture()
            coordinator = coordinator_harness(monkeypatch, transport, native, clock)
            coordinator.data = native
            coordinator._unloading = True
            before = transport._last_successful_arbitration_evidence
            assert await coordinator._async_update_data() is native
            assert transport._last_successful_arbitration_evidence is before
            assert coordinator._reconciliation_refresh_count == 0
    asyncio.run(run())


@pytest.mark.parametrize("age", [29, 120, 121])
def test_historical_motor_keepalive_clock_was_not_body_observation(monkeypatch, age):
    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            original = await capture()
            body_time = next(o.observed_at for o in original.observations if o.observation_id == "pool.active")
            clock[0] += timedelta(seconds=age)
            transport._controller._apply_updates([{"objnam": "P0001", "params": {"RPM": 0}}])
            native = NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0])
            current = next(o for o in native.observations if o.observation_id == "pool.active")
            old = next(o for o in historical_v088_projection(native, transport.latest_snapshot) if o.observation_id == "pool.active")
            assert old.value == current.value is False
            assert fresh(old, clock[0])
            assert current.observed_at == body_time
            assert fresh(current, clock[0]) is (age <= 120)
    asyncio.run(run())


def test_quiet_idle_then_new_pool_opportunity_acquires_from_fresh_observations(monkeypatch):
    from poolos.integration import SetBodyActive, ThermalBody
    from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus
    from test_thermal_automatic_execution import FakeDelivery, FakeDeliveryFactory, _frame

    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            native = await capture()
            coordinator = coordinator_harness(monkeypatch, transport, native, clock)
            orchestrator = ThermalRuntimeOrchestrator()
            driver = ThermalAutomaticExecutionDriver(orchestrator)
            delivery = FakeDelivery()
            factory = FakeDeliveryFactory(delivery, driver=driver)

            def frame(native):
                values = {o.observation_id: o.value for o in native.observations}
                return _frame(orchestrator, clock[0], pool_active=False, spa_active=False,
                    pump_rpm=0, configured_rpm=2600, pool_heater=values["pool.raw_heater_id"],
                    spa_heater=values["spa.raw_heater_id"], pool_temperature=81, pool_target=90,
                    solar_temperature=125, filtration_remaining=timedelta(0),
                    driver=driver, real_probe_continuity=True,
                    observation_times={o.observation_id: o.observed_at for o in native.observations})

            baseline = frame(native)
            driver.note_disabled_epoch(baseline)
            driver.set_enabled(True, changed_at=clock[0], current_epoch_identity=baseline.epoch_identity)
            # No active lease, pending receipt, cleanup or lifecycle reread owner.
            for _ in range(8):
                clock[0] += timedelta(seconds=30)
                native = await coordinator._async_update_data()
                assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
                assert not delivery.calls
            result = await driver.process_epoch(frame(native), delivery_factory=factory)
            assert any(isinstance(op, SetBodyActive) and op.active and op.equipment_id == ThermalBody.POOL.value
                       for op in delivery.calls), result
            assert orchestrator.ownership.state.lease.body_activation is not None
    asyncio.run(run())


def test_historical_scenario_matrix_maps_all_30_classes_to_executable_regressions():
    import ast
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    matrix = json.loads((root / "docs/ownership/observation_control_liveness_history.json").read_text())
    assert [s["id"] for s in matrix["scenarios"]] == list(range(1, 31))
    assert [r["release"] for r in matrix["releases"]] == [f"v0.11.{n}" for n in range(84, 105)]
    for row in matrix["scenarios"]:
        assert row["scenario"] and row["evidence"] and row["regressions"]
        for reference in row["regressions"]:
            file, name = reference.split("::")
            assert any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
                       for node in ast.walk(ast.parse((root / file).read_text()))), reference


def test_idle_native_refresh_is_throttled_inside_freshness_window(monkeypatch):
    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            native = await capture()
            coordinator = coordinator_harness(monkeypatch, transport, native, clock)
            baseline_read_id = transport._last_successful_arbitration_evidence.read_id

            for _ in range(2):
                clock[0] += timedelta(seconds=30)
                await coordinator._async_update_data()
            assert transport._last_successful_arbitration_evidence.read_id == baseline_read_id

            clock[0] += timedelta(seconds=30)
            await coordinator._async_update_data()
            assert transport._last_successful_arbitration_evidence.read_id == baseline_read_id + 1

            body = next(
                item
                for item in coordinator.native_intellicenter_snapshot.observations
                if item.observation_id == "pool.active"
            )
            assert fresh(body, clock[0])

    asyncio.run(run())
