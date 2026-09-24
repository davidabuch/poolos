"""Recovery-line probe cleanup through the HA read-only reobservation boundary."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from functools import partial

import pytest

from test_independent_intellicenter_transport import (
    _load_module as load_transport,
    FakeModelController,
    _objects,
)
from test_native_coordinator_refresh_coalescing import _load_coordinator_module
from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter

from test_thermal_automatic_execution import (
    NOW,
    FakeDelivery,
    FakeDeliveryFactory,
    _frame,
)
from test_home_assistant_thermal_automatic_runtime import _load_module, _runtime
from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator, ThermalRequestedMode


@pytest.mark.parametrize("native_age_seconds", [1, 9, 119])
@pytest.mark.parametrize("scheduled", [True, False])
@pytest.mark.parametrize("shutdown", ["target", "solar_loss", "pool_priority", "pump_timeout"])
def test_probe_residual_wait_requests_post_entitlement_native_evidence(
    monkeypatch, scheduled, shutdown, native_age_seconds
):
    async def scenario():
        orchestrator = ThermalRuntimeOrchestrator()
        driver = ThermalAutomaticExecutionDriver(orchestrator)
        evaluator = ThermalRuntimeEvaluator()
        delivery = FakeDelivery()
        factory = FakeDeliveryFactory(delivery, driver=driver)

        def frame(seconds, active, rpm, *, missing=False, old_topology=False):
            at = NOW + timedelta(seconds=seconds)
            return _frame(
                orchestrator,
                at,
                pool_active=active,
                pump_rpm=rpm,
                configured_rpm=rpm or 2600,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=81,
                pool_target=78,
                solar_temperature=125,
                missing=("pool.temperature",) if missing else (),
                evaluator=evaluator,
                driver=driver,
                observation_times={
                    concept: max(
                        NOW + timedelta(seconds=4),
                        min(at, NOW + timedelta(seconds=123))
                        - timedelta(seconds=native_age_seconds),
                    )
                    for concept in ("pool.active", "spa.active", "pool.raw_heater_id")
                }
                if old_topology
                else {},
                filtration_remaining=timedelta(0),
            )

        baseline = frame(0, False, 0, missing=True)
        driver.note_disabled_epoch(baseline)
        driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
        for seconds, active, rpm in ((1, False, 0), (2, True, 2600), (3, True, 1500)):
            await driver.process_epoch(
                frame(seconds, active, rpm, missing=True), delivery_factory=factory
            )
        lease = orchestrator.ownership.state.lease
        assert lease is not None and lease.body_activation is not None
        assert lease.pump_setpoint is not None
        for seconds in (33, 63, 123, 124):
            result = await driver.process_epoch(
                frame(seconds, True, 1500, old_topology=True), delivery_factory=factory
            )
        assert result.blocker == "circulation_body_activity_evidence_not_current"
        assert orchestrator.ownership.residual_termination is not None
        assert driver.cleanup_provenance is None
        runtime, _, _, coordinator, _ = _runtime(_load_module())
        runtime.driver = driver
        runtime.orchestrator = orchestrator
        native_module = load_transport(monkeypatch)
        objects = dict(_objects())
        objects["B1101"].update(STATUS="ON", HTMODE="0", HEATER="00000")
        objects["B1102"] = dict(objects["B1101"], SNAME="Spa", STATUS="OFF")
        objects["P0001"].update(RPM=1500)
        FakeModelController.initial_objects = tuple(objects.items())
        transport = native_module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
        await transport.async_start()
        for _ in range(30):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break
        clock_at = [NOW + timedelta(seconds=125)]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock_at[0]

        monkeypatch.setattr(native_module, "datetime", Clock)
        # The controller answers each requested key, including unchanged values.
        # No fake NotifyList is injected to rescue the lifecycle.
        requests = []

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            requests.append(extra)
            kind = extra["condition"].split(" = ")[1]
            keys = extra["objectList"][0]["keys"]
            return {
                "objectList": [
                    {
                        "objnam": obj.objnam,
                        "params": {key: obj[key] for key in keys if obj[key] is not None},
                    }
                    for obj in transport._model.get_by_type(kind)
                ]
            }

        transport._controller.send_cmd = read

        # pyintellicenter 0.1.20 only invokes its callback for CHANGED values.
        # Re-reading unchanged BODY STATUS therefore cannot be relied upon to
        # schedule the separate source-metadata RequestParamList worker.
        def unchanged_updates(entries):
            for entry in entries:
                obj = transport._model[entry["objnam"]]
                obj.properties.update(entry["params"])
            return {}

        transport._controller._apply_updates = unchanged_updates
        coordinator_type = _load_coordinator_module().PoolOSCoordinator
        coordinator._unloading = False
        coordinator.independent_intellicenter_transport = transport
        coordinator._async_refresh_native_runtime_evidence = partial(
            coordinator_type._async_refresh_native_runtime_evidence, coordinator
        )
        coordinator.async_refresh_native_cleanup_topology_evidence = partial(
            coordinator_type.async_refresh_native_cleanup_topology_evidence, coordinator
        )
        publications = []
        transport._set_snapshot_update_callback(
            lambda: publications.append(transport.read_snapshot())
        )
        if not scheduled:
            await coordinator.async_refresh_native_cleanup_topology_evidence()
        runtime._sync_cleanup_topology_reobservation()
        task = runtime._cleanup_topology_reobservation_task
        if task is not None:
            await task
        try:
            assert requests, "Residual waiting must request native evidence before cleanup capture"
            assert publications
            body_keys = next(
                request["objectList"][0]["keys"]
                for request in requests
                if request["condition"] == "OBJTYP = BODY"
            )
            assert {"HEATER", "HTMODE", "STATUS"} <= set(body_keys), (
                "Cleanup must actually read source selection, not refresh its cached timestamp"
            )
            native = NativeIntelliCenterReadAdapter().capture(
                transport, generated_at=NOW + timedelta(seconds=126)
            )
            mapped = {obs.observation_id: obs for obs in native.observations}
            assert mapped["pool.active"].value is True
            assert mapped["spa.active"].value is False
            assert mapped["pool.raw_heater_id"].value == "00000"
            retained = orchestrator.ownership.residual_termination
            assert all(
                mapped[c].observed_at > retained.retained_at
                for c in ("pool.active", "spa.active", "pool.raw_heater_id")
            )
            refreshed_frame = _frame(
                orchestrator,
                NOW + timedelta(seconds=126),
                pool_active=True,
                pump_rpm=1500,
                configured_rpm=1500,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=81,
                pool_target=78,
                solar_temperature=125,
                evaluator=evaluator,
                driver=driver,
                observation_times={c: obs.observed_at for c, obs in mapped.items()},
                filtration_remaining=timedelta(0),
            )
            await driver.process_epoch(refreshed_frame, delivery_factory=factory)
            assert driver.cleanup_provenance is not None
            # Capture is a second strict boundary, not permission to reuse the
            # earlier residual refresh. Reobserve unchanged topology again.
            captured = driver.cleanup_provenance
            clock_at[0] = NOW + timedelta(seconds=127)
            runtime._sync_cleanup_topology_reobservation()
            await runtime._cleanup_topology_reobservation_task
            native = NativeIntelliCenterReadAdapter().capture(
                transport, generated_at=NOW + timedelta(seconds=128)
            )
            mapped = {obs.observation_id: obs for obs in native.observations}
            assert mapped["pool.active"].observed_at > captured.established_at
            cleanup_frame = _frame(
                orchestrator,
                NOW + timedelta(seconds=128),
                pool_active=True,
                pump_rpm=1500,
                configured_rpm=1500,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=81,
                pool_target=78,
                solar_temperature=125,
                evaluator=evaluator,
                driver=driver,
                observation_times={c: obs.observed_at for c, obs in mapped.items()},
                filtration_remaining=timedelta(0),
            )
            result = await driver.process_epoch(cleanup_frame, delivery_factory=factory)
            from poolos.integration import SetBodyActive

            assert isinstance(delivery.calls[-1], SetBodyActive), result
            assert delivery.calls[-1].active is False
            for seconds, rpm in ((129, 900), (130, 0)):
                result = await driver.process_epoch(
                    frame(seconds, False, rpm), delivery_factory=factory
                )
                if rpm:
                    assert driver.cleanup_provenance is not None
            assert driver.cleanup_provenance is None, result
            assert not driver._reenable_required
            # Continue the SAME evaluator/driver after Pool completion. Native
            # Spa activation starts configured circulation before any RPM step.
            from poolos.integration import ThermalBody, SetHeatMode, SetPumpSpeed, PhysicalHeatMode

            spa_active = False
            rpm = 0
            configured = 2600
            heater = "00000"
            calls_seen = len(delivery.calls)
            first_spa_generation = None
            stable_epochs = 0
            for seconds in range(131, 451):
                spa_frame = _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=False,
                    body=ThermalBody.HOT_TUB,
                    spa_active=spa_active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    spa_heater=heater,
                    solar_active=heater == "H0002",
                    pool_temperature=81,
                    pool_target=78,
                    spa_temperature=81,
                    spa_target=100,
                    solar_temperature=140,
                    mode=ThermalRequestedMode.SOLAR_PREFERRED,
                    evaluator=evaluator,
                    driver=driver,
                )
                result = await driver.process_epoch(spa_frame, delivery_factory=factory)
                for operation in delivery.calls[calls_seen:]:
                    if isinstance(operation, SetBodyActive):
                        assert operation.equipment_id == ThermalBody.HOT_TUB.value
                        spa_active = operation.active
                        rpm = 2600 if spa_active else 0
                    elif isinstance(operation, SetPumpSpeed):
                        configured = rpm = operation.rpm
                    elif isinstance(operation, SetHeatMode):
                        assert operation.mode is not PhysicalHeatMode.GAS
                        heater = "H0002" if operation.mode is PhysicalHeatMode.SOLAR else "00000"
                calls_seen = len(delivery.calls)
                lease = orchestrator.ownership.state.lease
                if spa_active and heater == "H0002" and rpm == 2900:
                    assert lease is not None and lease.body is ThermalBody.HOT_TUB
                    assert lease.owns_body and lease.owns_pump_setpoint and lease.owns_heat_source
                    assert lease.body_activation is not None
                    assert lease.body_activation != captured.body_activation
                    assert lease.pump_setpoint is not None
                    assert lease.heat_source is not None
                    if first_spa_generation is None:
                        first_spa_generation = lease.generation
                    else:
                        assert lease.generation == first_spa_generation
                    stable_epochs += 1
            assert stable_epochs >= 120, (
                stable_epochs,
                result.blocker,
                [
                    (
                        type(c).__name__,
                        getattr(c, "rpm", getattr(c, "active", getattr(c, "mode", None))),
                    )
                    for c in delivery.calls
                ],
            )
            spa_origin = orchestrator.ownership.state.lease.body_activation
            coastdown_deadline = None
            coastdown_command_count = None
            for seconds in range(451, 580):
                result = await driver.process_epoch(
                    _frame(
                        orchestrator,
                        NOW + timedelta(seconds=seconds),
                        pool_active=False,
                        body=ThermalBody.HOT_TUB,
                        spa_active=spa_active,
                        pump_rpm=rpm,
                        configured_rpm=configured,
                        spa_heater=heater,
                        solar_active=heater == "H0002",
                        pool_temperature=81,
                        pool_target=90 if shutdown == "pool_priority" else 78,
                        spa_temperature=100 if shutdown in {"target", "pump_timeout"} else 81,
                        spa_target=100,
                        solar_temperature=110 if shutdown == "solar_loss" else 140,
                        mode=ThermalRequestedMode.SOLAR_PREFERRED,
                        evaluator=evaluator,
                        driver=driver,
                    ),
                    delivery_factory=factory,
                )
                if not spa_active and rpm == 900:
                    if shutdown == "pump_timeout":
                        assert len(delivery.calls) == coastdown_command_count
                        if result.blocker == "hot_tub_cleanup_verification_timed_out":
                            assert NOW + timedelta(seconds=seconds) >= coastdown_deadline
                            assert driver.cleanup_provenance is None
                            return
                    assert driver.cleanup_provenance is not None, (
                        "Spa BODY OFF is not completed shutdown while pump remains nonzero", result
                    )
                    assert driver.cleanup_attempt.deadline == coastdown_deadline
                    if shutdown != "pump_timeout":
                        rpm = 0
                for operation in delivery.calls[calls_seen:]:
                    if isinstance(operation, SetBodyActive):
                        assert operation.equipment_id == ThermalBody.HOT_TUB.value
                        assert operation.active is False
                        spa_active = False
                        rpm = 900
                        coastdown_deadline = driver.cleanup_attempt.deadline
                        coastdown_command_count = len(delivery.calls)
                    elif isinstance(operation, SetHeatMode):
                        assert operation.mode is PhysicalHeatMode.OFF
                        heater = "00000"
                    else:
                        pytest.fail(f"Unexpected Spa termination command: {operation}")
                calls_seen = len(delivery.calls)
                if not spa_active and rpm == 0 and driver.cleanup_provenance is None:
                    break
            assert shutdown != "pump_timeout", "Spa coastdown must fail on its fixed deadline"
            assert not spa_active and rpm == 0 and heater == "00000", result
            assert driver.cleanup_provenance is None
            assert orchestrator.ownership.residual_termination is None
            assert not driver._reenable_required
            if shutdown == "pool_priority":
                pool_active = False
                for seconds in range(580, 800):
                    result = await driver.process_epoch(
                        _frame(
                            orchestrator,
                            NOW + timedelta(seconds=seconds),
                            pool_active=pool_active,
                            spa_active=False,
                            pump_rpm=rpm,
                            configured_rpm=configured,
                            pool_heater=heater,
                            solar_active=heater == "H0002",
                            pool_temperature=81,
                            pool_target=90,
                            solar_temperature=140,
                            mode=ThermalRequestedMode.SOLAR,
                            evaluator=evaluator,
                            driver=driver,
                        ),
                        delivery_factory=factory,
                    )
                    for operation in delivery.calls[calls_seen:]:
                        if isinstance(operation, SetBodyActive):
                            assert operation.equipment_id == ThermalBody.POOL.value
                            pool_active = operation.active
                            rpm = 2600 if pool_active else 0
                        elif isinstance(operation, SetPumpSpeed):
                            rpm = configured = operation.rpm
                        elif isinstance(operation, SetHeatMode):
                            assert operation.mode is not PhysicalHeatMode.GAS
                            heater = (
                                "H0002" if operation.mode is PhysicalHeatMode.SOLAR else "00000"
                            )
                    calls_seen = len(delivery.calls)
                assert pool_active and rpm == 2900 and heater == "H0002", result
                lease = orchestrator.ownership.state.lease
                assert lease.body is ThermalBody.POOL
                assert lease.body_activation not in (spa_origin, captured.body_activation)
                assert lease.generation > first_spa_generation
        finally:
            await transport.async_stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["false", "exception", "invalidated", "replacement"])
def test_residual_reobservation_is_bounded_and_cannot_create_authority(outcome):
    """A read request is generation-bound observation work, never provenance."""
    from types import SimpleNamespace

    async def scenario():
        runtime, _, _, coordinator, driver = _runtime(_load_module())
        driver.requested_enabled = True
        residual = SimpleNamespace(entitlement_id="residual-generation-1")
        ownership = SimpleNamespace(residual_termination=residual)
        runtime.orchestrator = SimpleNamespace(ownership=ownership)
        calls = []

        async def refresh():
            calls.append("read")
            if outcome == "exception":
                raise OSError("native read failed")
            return False

        coordinator.async_refresh_native_cleanup_topology_evidence = refresh
        runtime._sync_cleanup_topology_reobservation()
        old_task = runtime._cleanup_topology_reobservation_task
        if outcome == "invalidated":
            ownership.residual_termination = None
        elif outcome == "replacement":
            ownership.residual_termination = SimpleNamespace(entitlement_id="residual-generation-2")
        await old_task
        assert calls == ([] if outcome in {"invalidated", "replacement"} else ["read"])
        assert driver.cleanup_provenance is None
        assert driver.processed == []
        for _ in range(4):
            runtime._sync_cleanup_topology_reobservation()
            task = runtime._cleanup_topology_reobservation_task
            if task is not None:
                await task
        assert calls == ([] if outcome == "invalidated" else ["read"])
        assert driver.cleanup_provenance is None
        assert driver.processed == []

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response_case",
    [
        "unchanged",
        "source_changed",
        "missing_source",
        "empty",
        "timeout",
        "old_generation",
        "intervening_update",
    ],
)
def test_cleanup_native_read_publishes_only_complete_current_replies(monkeypatch, response_case):
    """A partial read must not re-date cached BODY/source or authorize cleanup."""

    async def scenario():
        native_module = load_transport(monkeypatch)
        objects = dict(_objects())
        objects["B1101"].update(HEATER="00000", HTMODE="0")
        FakeModelController.initial_objects = tuple(objects.items())
        transport = native_module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
        await transport.async_start()
        for _ in range(30):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break
        before = transport.read_snapshot()
        started_at = before.observed_at + timedelta(seconds=1)
        clock_at = [started_at]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock_at[0]

        monkeypatch.setattr(native_module, "datetime", Clock)
        published = []
        transport._set_snapshot_update_callback(lambda: published.append(transport.read_snapshot()))

        async def read(cmd, extra=None):
            assert cmd == "GetParamList"
            clock_at[0] += timedelta(seconds=1)
            kind = extra["condition"].split(" = ")[1]
            keys = extra["objectList"][0]["keys"]
            if kind == "SYSTEM":
                if response_case == "empty":
                    return {"objectList": []}
                if response_case == "timeout":
                    raise native_module.ICTimeoutError("test read timeout")
                if response_case == "old_generation":
                    transport._discovery_generation += 1
                if response_case == "intervening_update":
                    transport._model["B1101"].properties["HEATER"] = "H0001"
                    transport._on_updated({})
            entries = []
            for obj in transport._model.get_by_type(kind):
                params = {key: obj[key] for key in keys if obj[key] is not None}
                if kind == "BODY":
                    if response_case == "missing_source":
                        params.pop("HEATER")
                    elif response_case == "source_changed":
                        params["HEATER"] = "H0001"
                entries.append({"objnam": obj.objnam, "params": params})
            return {"objectList": entries}

        transport._controller.send_cmd = read

        # Match the dependency's no-callback behavior for unchanged responses;
        # the transport's explicit complete-read publication is under test.
        def apply(entries):
            for entry in entries:
                transport._model[entry["objnam"]].properties.update(entry["params"])
            return {}

        transport._controller._apply_updates = apply
        try:
            result = await transport._async_refresh_owned_pump_session_evidence(
                cleanup_topology=True
            )
            if response_case in {"unchanged", "source_changed"}:
                assert result is True
                assert len(published) == 1
                assert published[0].observed_at == started_at
                assert published[0].observed_at < clock_at[0]
                # A newer entitlement created between these replies cannot
                # mistake the completion time for post-boundary source proof.
                assert published[0].observed_at < started_at + timedelta(seconds=1)
                observations = (
                    NativeIntelliCenterReadAdapter()
                    .capture(transport, generated_at=published[0].observed_at)
                    .observations
                )
                source = next(
                    item for item in observations if item.observation_id == "pool.raw_heater_id"
                )
                assert source.value == ("H0001" if response_case == "source_changed" else "00000")
            elif response_case == "intervening_update":
                assert result is False
                assert len(published) == 1
                assert transport.read_snapshot().bodies[0].raw_heater_id == "H0001"
            else:
                assert result is False
                assert published == []
                assert transport.read_snapshot() is before
        finally:
            await transport.async_stop()

    asyncio.run(scenario())
