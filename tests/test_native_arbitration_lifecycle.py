"""Physical state simulation driven by genuine complete native read captures."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from poolos.integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed, ThermalBody
from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
from poolos.thermal_automatic_execution import ThermalAutomaticDriverState, ThermalAutomaticExecutionDriver
from poolos.thermal_runtime_assessment import ThermalRequestedMode, ThermalRuntimeEvaluator
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnedConcept, ThermalRuntimeOwnershipStatus
from test_independent_intellicenter_transport import FakeModelController, _load_module
from test_native_arbitration_evidence_contract import arbitration_objects
from test_native_coordinator_refresh_coalescing import _load_coordinator_module
from test_thermal_automatic_execution import NOW, FakeDelivery, FakeDeliveryFactory, _frame


@pytest.mark.parametrize("restart_spa", [False, True])
@pytest.mark.parametrize("interleaved", [False, True])
def test_native_pool_target_down_idle_target_up_and_spa_restart_return(monkeypatch, restart_spa, interleaved):
    async def scenario():
        module = _load_module(monkeypatch)
        clock = [NOW]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]

        monkeypatch.setattr(module, "datetime", Clock)
        objects = arbitration_objects()
        for body_id in ("B1101", "B1102"):
            objects[body_id].update(STATUS="OFF", HEATER="00000", HTMODE="0", LSTTMP=81)
        objects["P0001"]["RPM"] = 0
        FakeModelController.initial_objects = tuple(objects.items())
        transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
        await transport.async_start()
        for _ in range(40):
            await asyncio.sleep(0)
            if not transport._connection_reconciliation_tasks and not transport._body_metadata_refresh_tasks:
                break

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            kind = extra["condition"].split(" = ")[1]
            if interleaved and kind == "PUMP":
                # The real transport publishes these callbacks while a complete
                # read is in flight. Sibling unchanged BODY/circuit clocks must
                # still advance through the complete read, not this callback.
                transport._controller._apply_updates([{"objnam": "P0001",
                    "params": {"RPM": transport._model["P0001"]["RPM"]}}])
            keys = extra["objectList"][0]["keys"]
            return {"objectList": [{"objnam": obj.objnam, "params": {key: obj[key] for key in keys if obj[key] is not None}}
                                   for obj in transport._model.get_by_type(kind)]}

        transport._controller.send_cmd = read
        coordinator_type = _load_coordinator_module().PoolOSCoordinator
        from test_observation_control_liveness_history import coordinator_harness
        coordinator = coordinator_harness(
            monkeypatch, transport,
            NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0]), clock,
        )
        orchestrator = ThermalRuntimeOrchestrator()
        driver = ThermalAutomaticExecutionDriver(orchestrator)
        evaluator = ThermalRuntimeEvaluator()
        delivery = FakeDelivery()
        factory = FakeDeliveryFactory(delivery, driver=driver)
        calls_seen = 0
        trace = []
        recovery_runtime = None

        async def tick(target=90, *, spa=False, roof=125, execute=True):
            nonlocal calls_seen
            clock[0] += timedelta(seconds=15)
            # No NotifyList or invented observation timestamps: unchanged and
            # changed physical values must cross the real batch/adapter boundary.
            # Exercise the production reconciliation admission at idle too;
            # an unconditional test-side capture used to mask that missing read.
            native = await coordinator._async_update_data()
            mapped = {o.observation_id: o for o in native.observations}
            frame = _frame(
                orchestrator, clock[0],
                pool_active=mapped["pool.active"].value,
                spa_active=mapped["spa.active"].value,
                pump_rpm=int(mapped["pump.rpm"].value),
                configured_rpm=int(mapped[f"{'spa' if spa else 'pool'}.pump_circuit.configured_speed_rpm"].value),
                pool_heater=mapped["pool.raw_heater_id"].value,
                spa_heater=mapped["spa.raw_heater_id"].value,
                solar_active=mapped["solar.active"].value,
                pool_temperature=81, pool_target=target, spa_temperature=81, spa_target=100,
                solar_temperature=roof,
                mode=ThermalRequestedMode.SOLAR_PREFERRED if spa else ThermalRequestedMode.SOLAR,
                body=ThermalBody.HOT_TUB if spa else ThermalBody.POOL,
                evaluator=evaluator, driver=driver, real_probe_continuity=True,
                observation_times={c: o.observed_at for c, o in mapped.items()},
                filtration_remaining=timedelta(0),
                spa_session_kind_override=(None if recovery_runtime is None else recovery_runtime.spa_session_kind_for_assessment()),
            )
            if not execute:
                return frame
            result = await driver.process_epoch(frame, delivery_factory=factory)
            trace.append((clock[0].isoformat(), result.blocker, mapped["pool.raw_heater_id"].value, len(delivery.calls), frame.thermal.pool.plan.desired.selected_source))
            for operation in delivery.calls[calls_seen:]:
                body_id = "B1102" if operation.equipment_id == ThermalBody.HOT_TUB.value else "B1101"
                if isinstance(operation, SetBodyActive):
                    transport._model[body_id].properties["STATUS"] = "ON" if operation.active else "OFF"
                    # IntelliCenter BODY activation starts circuit/default flow;
                    # BODY OFF has a nonzero coastdown before a later read.
                    transport._model["P0001"].properties["RPM"] = 2600 if operation.active else 900
                elif isinstance(operation, SetPumpSpeed):
                    transport._model["P0001"].properties["RPM"] = operation.rpm
                    pump_id = "p0198" if spa else "p0102"
                    transport._model[pump_id].properties["SPEED"] = operation.rpm
                elif isinstance(operation, SetHeatMode):
                    assert operation.mode is not PhysicalHeatMode.GAS
                    transport._model[body_id].properties.update(
                        HEATER="H0002" if operation.mode is PhysicalHeatMode.SOLAR else "00000",
                        HTMODE="1" if operation.mode is PhysicalHeatMode.SOLAR else "0",
                    )
                    transport._model["C0002"].properties["STATUS"] = "ON" if operation.mode is PhysicalHeatMode.SOLAR else "OFF"
            calls_seen = len(delivery.calls)
            if not mapped["pool.active"].value and not mapped["spa.active"].value and mapped["pump.rpm"].value == 900:
                assert driver.cleanup_provenance is not None, result
                transport._model["P0001"].properties["RPM"] = 0
            return result

        def stable(body):
            lease = orchestrator.ownership.state.lease
            return bool(lease and lease.status is ThermalRuntimeOwnershipStatus.OWNED
                        and lease.body is body and lease.body_activation and lease.owns_body
                        and lease.owns_pump_setpoint and lease.owns_heat_source
                        and set(lease.verified_concepts) == set(ThermalRuntimeOwnedConcept)
                        and driver.assessment is not None
                        and driver.assessment.state is ThermalAutomaticDriverState.CONVERGED
                        and transport._model["P0001"]["RPM"] == 2900
                        and transport._model["C0002"]["STATUS"] == "ON")

        async def converge(target=90, *, spa=False, roof=125):
            for _ in range(35):
                result = await tick(target, spa=spa, roof=roof)
                if stable(ThermalBody.HOT_TUB if spa else ThermalBody.POOL):
                    return
            pytest.fail(f"Did not converge: {result}")

        try:
            baseline = await tick(execute=False)
            driver.note_disabled_epoch(baseline)
            driver.set_enabled(True, changed_at=clock[0], current_epoch_identity=baseline.epoch_identity)
            await converge()
            first_pool_origin = orchestrator.ownership.state.lease.body_activation
            for _ in range(12):
                await tick()
                assert stable(ThermalBody.POOL)
            # Preserve the configured ten-minute target-satisfaction debounce.
            # The residual must remain live and freshly observed throughout it.
            for _ in range(70):
                result = await tick(78, roof=110)
                if transport._model["B1101"]["STATUS"] == "OFF" and transport._model["P0001"]["RPM"] == 0 and driver.cleanup_provenance is None:
                    break
            assert transport._model["B1101"]["STATUS"] == "OFF", "\n".join(map(str, trace[-22:]))
            assert transport._model["P0001"]["RPM"] == 0
            assert transport._model["B1101"]["HEATER"] == "00000"
            assert orchestrator.ownership.residual_termination is None
            idle_commands = len(delivery.calls)
            for _ in range(12):
                await tick(78, roof=110)
                assert orchestrator.ownership.state.status is not ThermalRuntimeOwnershipStatus.OWNED
                assert driver.cleanup_provenance is None
                assert orchestrator.ownership.residual_termination is None
            assert len(delivery.calls) == idle_commands
            if restart_spa:
                await converge(78, spa=True, roof=140)
                old_spa = orchestrator.ownership.state.lease
                for _ in range(9):
                    await tick(78, spa=True, roof=140)
                checkpoint = orchestrator.ownership.export_restart_checkpoint(captured_at=clock[0])
                assert checkpoint is not None
                orchestrator = ThermalRuntimeOrchestrator()
                driver = ThermalAutomaticExecutionDriver(orchestrator)
                evaluator = ThermalRuntimeEvaluator()
                factory.driver = driver
                from test_home_assistant_thermal_automatic_runtime import _load_module as load_runtime, _runtime

                recovery_runtime, _, _, _, _ = _runtime(load_runtime())
                recovery_runtime.driver = driver
                recovery_runtime.orchestrator = orchestrator
                recovery_runtime.circulation_ownership = driver.circulation_ownership
                recovery_runtime.arm_quick_restart_recovery(checkpoint)
                async def prepare_native():
                    clock[0] += timedelta(seconds=15)
                    return await coordinator_type.async_refresh_native_thermal_topology_evidence(coordinator)

                recovery_runtime.coordinator.async_refresh_native_thermal_topology_evidence = prepare_native
                # Exact verified checkpoint, no pending work. Fresh native batch
                # is necessary; equipment equality without checkpoint is not used.
                frame = await tick(78, spa=True, roof=140, execute=False)
                driver.note_disabled_epoch(frame)
                driver.set_enabled(True, changed_at=clock[0], current_epoch_identity=frame.epoch_identity)
                commands_before_restore = len(delivery.calls)
                recovery_runtime.observe(
                    SimpleNamespace(generated_at=frame.observed_at, observations=frame.observations),
                    frame.thermal, frame.orchestration, frame.external_changes,
                )
                assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
                assert recovery_runtime.quick_restart_recovery_armed
                assert len(delivery.calls) == commands_before_restore
                await recovery_runtime._restart_evidence_preparation_task
                frame = await tick(78, spa=True, roof=140, execute=False)
                recovery_runtime.observe(
                    SimpleNamespace(generated_at=frame.observed_at, observations=frame.observations),
                    frame.thermal, frame.orchestration, frame.external_changes,
                )
                assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED, str(frame.thermal.hot_tub)
                assert orchestrator.ownership.state.lease.body_activation == old_spa.body_activation
                assert len(delivery.calls) == commands_before_restore
                assert not recovery_runtime.quick_restart_recovery_armed
                task = recovery_runtime._owned_pump_session_reobservation_task
                recovery_runtime._cancel_owned_pump_session_reobservation()
                if task is not None:
                    with pytest.raises(asyncio.CancelledError):
                        await task
                for _ in range(20):
                    result = await tick(90, spa=True, roof=140)
                    if transport._model["B1102"]["STATUS"] == "OFF" and transport._model["P0001"]["RPM"] == 0 and driver.cleanup_provenance is None:
                        break
                assert transport._model["B1102"]["STATUS"] == "OFF", result
                assert transport._model["P0001"]["RPM"] == 0
            await converge(90, roof=140)
            assert stable(ThermalBody.POOL)
            assert orchestrator.ownership.state.lease.body_activation != first_pool_origin
            if restart_spa:
                assert orchestrator.ownership.state.lease.body_activation != old_spa.body_activation
            assert driver.cleanup_provenance is None
            assert orchestrator.ownership.residual_termination is None
            assert not driver._reenable_required
            assert len(delivery.correlation_ids) == len(set(delivery.correlation_ids))
        finally:
            await transport.async_stop()

    asyncio.run(scenario())
