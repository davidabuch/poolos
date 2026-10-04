"""Exercise the actual entry stop registration before config-entry unload."""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from functools import partial
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from test_home_assistant_thermal_automatic_runtime import _load_module, _runtime
from poolos.pump_speed_session import PumpSpeedSessionPurpose

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/poolos"


def _entry_functions():
    tree = ast.parse((INTEGRATION / "__init__.py").read_text())
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"async_unload_entry", "_async_handle_homeassistant_stop"}
    ]
    namespace = {"datetime": datetime, "UTC": UTC, "PLATFORMS": (), "partial": partial}
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[
                        ast.ImportFrom(
                            module="__future__", names=[ast.alias(name="annotations")], level=0
                        ),
                        *definitions,
                    ],
                    type_ignores=[],
                )
            ),
            str(INTEGRATION / "__init__.py"),
            "exec",
        ),
        namespace,
    )
    stop = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_listen_once"
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "EVENT_HOMEASSISTANT_STOP"
    )
    return namespace, ast.Expression(body=stop.args[1])


def _background_owner():
    path = INTEGRATION / "background_tasks.py"
    spec = importlib.util.spec_from_file_location("poolos_stop_background_owner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PoolOSBackgroundTasks()


def _lifecycle():
    path = INTEGRATION / "lifecycle.py"
    spec = importlib.util.spec_from_file_location("poolos_stop_test_lifecycle", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PoolOSIntegrationLifecycle()


def test_registered_stop_awaits_owned_pump_loop_before_final_write_and_later_unload():
    async def scenario():
        module = _load_module()
        runtime, _, _, coordinator, driver = _runtime(module)
        driver.requested_enabled = True
        driver.pump_session_purpose = PumpSpeedSessionPurpose.PRIMING
        runtime._sync_owned_pump_session_reobservation()
        task = runtime._owned_pump_session_reobservation_task
        await asyncio.sleep(0)
        assert task is not None and not task.done()
        events = []

        async def prepare():
            events.append("coordinator-drained")

        async def old_stop(_event):
            await prepare()

        async def stop_transport():
            assert task.done(), "transport must stop after execution/reobservation"
            events.append("transport-stopped")

        coordinator.async_handle_homeassistant_stop = old_stop
        coordinator.prepare_unload = lambda: events.append("coordinator-inert")
        coordinator.async_prepare_unload = prepare
        coordinator.async_stop_independent_intellicenter = stop_transport
        runtime.orchestrator = SimpleNamespace(
            ownership=SimpleNamespace(state=SimpleNamespace(lease=None))
        )
        runtimes = []
        for name in ("grid", "sanitation", "filtration"):

            async def unload(name=name):
                events.append(name + "-drained")

            runtimes.append(
                SimpleNamespace(
                    prepare_unload=lambda name=name: events.append(name + "-inert"),
                    async_unload=unload,
                )
            )
        data = SimpleNamespace(
            coordinator=coordinator,
            thermal_automatic_runtime=runtime,
            grid_outage_safety_runtime=runtimes[0],
            sanitation_runtime=runtimes[1],
            filtration_automatic_runtime=runtimes[2],
            manual_intellicenter=None,
            thermal_runtime=SimpleNamespace(
                set_orchestration_observer=lambda _: None,
                set_orchestration_failure_observer=lambda _: None,
            ),
            thermal_runtime_orchestrator=SimpleNamespace(unload=lambda **_: None),
        )
        entry = SimpleNamespace(runtime_data=data)
        namespace, expression = _entry_functions()
        if (INTEGRATION / "lifecycle.py").exists():
            data.lifecycle = _lifecycle()
        namespace.update(entry=entry, coordinator=coordinator)
        handler = eval(compile(expression, "stop-registration", "eval"), namespace)
        try:
            await handler(SimpleNamespace(event_type="homeassistant_stop"))
            assert task.done(), "STOP left owned pump-session reobservation running"
            assert runtime._unloaded
            assert runtime._owned_pump_session_reobservation_task is None
            before = list(events)

            async def unload_platforms(*_):
                return True

            hass = SimpleNamespace(
                config_entries=SimpleNamespace(async_unload_platforms=unload_platforms)
            )
            assert await namespace["async_unload_entry"](hass, entry)
            assert events == before, "late config-entry unload repeated shutdown work"
            runtime._sync_owned_pump_session_reobservation()
            assert runtime._owned_pump_session_reobservation_task is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_all_thermal_reobservation_owners_are_cancelled_and_awaited_after_fence():
    async def scenario():
        runtime, hass, _, _, _ = _runtime(_load_module())
        fields = (
            "_owned_pump_session_reobservation_task",
            "_cleanup_topology_reobservation_task",
            "_verification_topology_reobservation_task",
            "_spa_startup_topology_reobservation_task",
            "_shared_hydraulic_reobservation_task",
            "_restart_evidence_preparation_task",
        )
        finished = []

        async def waiting(name):
            try:
                await asyncio.Event().wait()
            finally:
                # A cancellation request alone is insufficient: cleanup must finish.
                await asyncio.sleep(0)
                finished.append(name)

        tasks = []
        for name in fields:
            task = asyncio.create_task(waiting(name))
            tasks.append(task)
            setattr(runtime, name, task)
        runtime._background_tasks.create(
            hass, waiting("auxiliary"), "PoolOS restart origin reevaluation"
        )
        await asyncio.sleep(0)
        runtime.prepare_unload()
        assert runtime._unloaded
        await runtime.async_unload()
        assert sorted(finished) == sorted([*fields, "auxiliary"])
        assert all(task.done() for task in tasks)
        assert all(getattr(runtime, name) is None for name in fields)
        await runtime.async_unload()
        assert len(finished) == len(fields) + 1

    asyncio.run(scenario())


def test_stop_preserves_exact_verified_checkpoint_but_never_creates_one_from_external_spa():
    from test_thermal_quick_restart_recovery import _stable_verified_hot_tub_solar_manager
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipManager

    async def scenario(owned, *, ha_stop=True):
        runtime, _, _, coordinator, _ = _runtime(_load_module())
        manager = (
            _stable_verified_hot_tub_solar_manager() if owned else ThermalRuntimeOwnershipManager()
        )
        runtime.orchestrator = SimpleNamespace(ownership=manager)
        # Physical equality (external Spa ON / Solar / 2900) is deliberately
        # identical. Only accepted and verified historical commands distinguish it.
        physical = {"spa": True, "source": "Solar", "rpm": 2900}
        receipts = manager.state.lease
        before = runtime.quick_restart_restore_payload()
        assert (before is not None) is owned
        commands = []

        async def equipment_command(*_, **__):
            commands.append("unexpected shutdown equipment command")

        async def drain():
            pass

        coordinator.prepare_unload = lambda: None
        coordinator.async_prepare_unload = drain
        coordinator.async_stop_independent_intellicenter = drain
        passive = SimpleNamespace(prepare_unload=lambda: None, async_unload=drain)

        def unload_orchestration(**_):
            runtime.orchestrator.ownership = ThermalRuntimeOwnershipManager()

        data = SimpleNamespace(
            lifecycle=_lifecycle(),
            coordinator=coordinator,
            thermal_automatic_runtime=runtime,
            grid_outage_safety_runtime=passive,
            sanitation_runtime=passive,
            filtration_automatic_runtime=passive,
            manual_intellicenter=SimpleNamespace(
                prepare_stop=lambda: None,
                async_stop=drain,
                async_set_body_active=equipment_command,
                async_set_body_heat_source=equipment_command,
                async_set_pump_circuit_speed=equipment_command,
            ),
            thermal_runtime=SimpleNamespace(
                set_orchestration_observer=lambda _: None,
                set_orchestration_failure_observer=lambda _: None,
            ),
            thermal_runtime_orchestrator=SimpleNamespace(unload=unload_orchestration),
        )
        await data.lifecycle.async_stop(data, homeassistant_stop=ha_stop)
        # Final-write persistence uses only the exact previously eligible evidence.
        assert runtime.quick_restart_restore_payload() == (before if ha_stop else None)
        assert commands == []
        assert manager.state.lease == receipts
        assert physical == {"spa": True, "source": "Solar", "rpm": 2900}
        if owned:
            restored = ThermalRuntimeOwnershipManager()
            assert restored.state.lease is None  # payload is not restored authority
            assert before is not None
        else:
            assert runtime.quick_restart_restore_payload() is None

    asyncio.run(scenario(True))
    asyncio.run(scenario(False))
    asyncio.run(scenario(True, ha_stop=False))  # config-entry reload does not arm restore


def test_auxiliary_work_is_rejected_after_stop_and_cancelled_work_finishes():
    async def scenario():
        path = INTEGRATION / "background_tasks.py"
        spec = importlib.util.spec_from_file_location("poolos_auxiliary_stop_test", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        import sys

        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        owner = module.PoolOSBackgroundTasks()
        finished = asyncio.Event()
        calls = []

        async def waiting():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        hass = SimpleNamespace(async_create_task=lambda coro, name: asyncio.create_task(coro))
        owner.create(hass, waiting(), "pending Reset refresh / safety interlock")
        await asyncio.sleep(0)
        await owner.async_stop()
        assert finished.is_set()

        async def late():
            calls.append("must not issue command")

        coroutine = late()
        owner.create(hass, coroutine, "late callback")
        assert coroutine.cr_frame is None  # rejected coroutine closed, not scheduled
        await owner.async_stop()
        assert not calls and not owner._tasks

    asyncio.run(scenario())


def test_upstream_reconnect_and_debounce_are_awaited_without_unowned_disconnect_task():
    from poolos.integration.connection_lifecycle import async_quiesce_connection_handler

    async def scenario():
        completed = []

        async def loop(name):
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                completed.append(name)

        tasks = [asyncio.create_task(loop(name)) for name in ("reconnect", "debounce")]
        handler = SimpleNamespace(
            _stopped=False, _starter_task=tasks[0], _disconnect_debounce_task=tasks[1]
        )
        await asyncio.sleep(0)
        await async_quiesce_connection_handler(handler)
        assert handler._stopped
        assert all(task.done() for task in tasks)
        assert sorted(completed) == ["debounce", "reconnect"]
        await async_quiesce_connection_handler(handler)
        assert len(completed) == 2

    asyncio.run(scenario())


def _manual_gateway_methods():
    tree = ast.parse((INTEGRATION / "manual_intellicenter.py").read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ManualIntelliCenterControl"
    )
    cls.body = [
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"available", "prepare_stop", "_async_deliver", "_require_available"}
    ]

    class Error(RuntimeError):
        pass

    namespace = {
        "datetime": datetime,
        "UTC": UTC,
        "ManualIntelliCenterState": SimpleNamespace(AVAILABLE="available"),
        "ManualIntelliCenterCommandError": Error,
        "ManualIntelliCenterCommandNotDispatchedError": type("NotDispatched", (Error,), {}),
        "ManualIntelliCenterCommandOutcomeUnknownError": type("Unknown", (Error,), {}),
        "PhysicalCommandDeniedError": type("Denied", (Error,), {}),
    }
    module = ast.Module(
        body=[*ast.parse("from __future__ import annotations").body, cls], type_ignores=[]
    )
    exec(compile(ast.fix_missing_locations(module), "manual-stop-boundary", "exec"), namespace)
    return namespace


def test_stop_denies_queued_dispatch_without_fabricating_operator_or_command_provenance():
    import pytest

    async def scenario():
        namespace = _manual_gateway_methods()
        manual = namespace["ManualIntelliCenterControl"]()
        manual._stopping = False
        manual._state = "available"
        manual._command_lock = asyncio.Lock()
        records = []
        manual._command_authority = SimpleNamespace(
            note_operator_request=lambda *_, **__: records.append("operator-request"),
            reserve=lambda *_, **__: "expectation",
            cancel=lambda _: records.append("cancel-reservation"),
            require_allowed=lambda _: records.append("final-permission"),
            supersede_dispatched_expectations=lambda _: None,
            mark_dispatch_started=lambda _: records.append("dispatch"),
        )

        async def dispatch():
            records.append("equipment-command")

        kwargs = dict(
            request=object(), consequence=object(), dispatch=dispatch, failure_message="failed"
        )
        # A user request queued before stop cannot dispatch after stop even if its
        # earlier final-gateway assessment allowed it.
        await manual._command_lock.acquire()
        task = asyncio.create_task(manual._async_deliver(**kwargs))
        await asyncio.sleep(0)
        assert records == ["operator-request"]
        manual.prepare_stop()
        manual._command_lock.release()
        with pytest.raises(namespace["ManualIntelliCenterCommandNotDispatchedError"]):
            await task
        assert records == ["operator-request", "cancel-reservation"]
        records.clear()
        with pytest.raises(namespace["ManualIntelliCenterCommandNotDispatchedError"]):
            await manual._async_deliver(**kwargs)
        assert records == []  # stop creates neither intent nor accepted provenance

    asyncio.run(scenario())


def test_already_dispatched_command_settles_truthful_result_without_shutdown_cleanup():
    async def scenario():
        namespace = _manual_gateway_methods()
        manual = namespace["ManualIntelliCenterControl"]()
        manual._stopping = False
        manual._state = "available"
        manual._command_lock = asyncio.Lock()
        started, release = asyncio.Event(), asyncio.Event()
        records = []
        manual._command_authority = SimpleNamespace(
            note_operator_request=lambda *_, **__: None,
            reserve=lambda *_, **__: "existing-expectation",
            cancel=lambda _: records.append("cancel"),
            require_allowed=lambda _: None,
            supersede_dispatched_expectations=lambda _: None,
            mark_dispatch_started=lambda _: records.append("original-dispatch"),
        )

        async def dispatch():
            started.set()
            await release.wait()
            records.append("original-accepted-result")

        owner = _background_owner()
        hass = SimpleNamespace(async_create_task=lambda coro, name: asyncio.create_task(coro))
        task = owner.create(
            hass,
            manual._async_deliver(
                request=object(), consequence=object(), dispatch=dispatch, failure_message="failed"
            ),
            "inflight safety interlock",
            cancel_on_stop=False,
        )
        await started.wait()
        manual.prepare_stop()
        stop = asyncio.create_task(owner.async_stop())
        await asyncio.sleep(0)
        assert task is not None and not task.done() and not stop.done()
        release.set()
        await stop
        assert records == ["original-dispatch", "original-accepted-result"]

    asyncio.run(scenario())


def test_filtration_keepalive_and_verification_cancel_after_same_synchronous_fence():
    from test_home_assistant_filtration_automatic_runtime import (
        _load_module as load_filtration,
        _runtime as filtration_runtime,
    )

    async def scenario():
        runtime, _, authority, _, driver = filtration_runtime(load_filtration())
        completed = []

        async def waiting(name):
            try:
                await asyncio.Event().wait()
            finally:
                completed.append(name)

        fields = [
            "_owned_filtration_reobservation_task",
            "_verification_topology_reobservation_task",
        ]
        tasks = []
        for field in fields:
            task = asyncio.create_task(waiting(field))
            tasks.append(task)
            setattr(runtime, field, task)
        await asyncio.sleep(0)
        runtime.prepare_unload()
        assert runtime._unloaded and driver.unloaded and authority.unloaded
        await runtime.async_unload()
        assert all(task.done() for task in tasks)
        assert sorted(completed) == sorted(fields)
        await runtime.async_unload()
        assert len(completed) == 2

    asyncio.run(scenario())


def test_coordinator_stop_fences_native_start_refresh_and_auxiliary_callbacks():
    from test_native_coordinator_refresh_coalescing import _harness

    async def scenario():
        coordinator = _harness()
        path = INTEGRATION / "background_tasks.py"
        spec = importlib.util.spec_from_file_location("poolos_coordinator_stop_aux", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        import sys

        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        coordinator.background_tasks = module.PoolOSBackgroundTasks()
        coordinator._analysis_task = None
        coordinator._remove_state_listener = None
        stopped = []

        async def transport_stop():
            stopped.append("native-stop")

        coordinator.independent_intellicenter_transport = SimpleNamespace(
            _set_snapshot_update_callback=lambda _: None, async_stop=transport_stop
        )

        async def pending():
            await asyncio.Event().wait()

        coordinator._native_intellicenter_refresh_task = asyncio.create_task(pending())
        coordinator._independent_intellicenter_start_task = asyncio.create_task(pending())
        tasks = [
            coordinator._native_intellicenter_refresh_task,
            coordinator._independent_intellicenter_start_task,
        ]
        coordinator.background_tasks.create(coordinator.hass, pending(), "late entity refresh")
        await asyncio.sleep(0)
        coordinator.prepare_unload()
        coordinator.async_start_independent_intellicenter()
        coordinator._async_schedule_native_intellicenter_refresh()
        assert coordinator._independent_intellicenter_start_task is tasks[1]
        assert coordinator._native_intellicenter_refresh_task is tasks[0]
        await coordinator.async_prepare_unload()
        await coordinator.async_stop_independent_intellicenter()
        assert all(task.done() for task in tasks)
        assert not coordinator.background_tasks._tasks
        assert stopped == ["native-stop"]

    asyncio.run(scenario())


def test_concurrent_stop_and_unload_drain_once_even_when_persistence_fails(caplog):
    async def scenario():
        lifecycle = _lifecycle()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def drain():
            started.set()
            await release.wait()
            calls.append("drained")

        async def failed_persistence():
            raise OSError("store unavailable")

        async def coordinator_drain():
            calls.append("coordinator-drained")

        async def disconnect():
            calls.append("disconnected")

        async def unused_drain():
            pass

        owner = SimpleNamespace(prepare_unload=lambda: calls.append("fenced"), async_unload=drain)
        passive = SimpleNamespace(prepare_unload=lambda: None, async_unload=unused_drain)
        data = SimpleNamespace(
            coordinator=SimpleNamespace(
                prepare_unload=lambda: None,
                async_prepare_unload=coordinator_drain,
                async_stop_independent_intellicenter=disconnect,
            ),
            manual_intellicenter=None,
            thermal_runtime=SimpleNamespace(
                set_orchestration_observer=lambda _: None,
                set_orchestration_failure_observer=lambda _: None,
            ),
            thermal_runtime_orchestrator=SimpleNamespace(unload=lambda **_: None),
            grid_outage_safety_runtime=owner,
            sanitation_runtime=SimpleNamespace(
                prepare_unload=lambda: None, async_unload=failed_persistence
            ),
            thermal_automatic_runtime=passive,
            filtration_automatic_runtime=passive,
        )
        first = asyncio.create_task(lifecycle.async_stop(data))
        await started.wait()
        second = asyncio.create_task(lifecycle.async_stop(data))
        await asyncio.sleep(0)
        assert calls == ["fenced"]
        release.set()
        await asyncio.gather(first, second)
        await lifecycle.async_stop(data)
        assert calls == ["fenced", "drained", "coordinator-drained", "disconnected"]
        assert "runtime drain failed" in caplog.text

    asyncio.run(scenario())


def test_stop_denies_manual_body_off_before_restraint_callback():
    from test_home_assistant_native_pump_rpm_behavior import _gateway
    import pytest

    async def scenario():
        gateway, recorder = _gateway([])
        restraints = []
        gateway._pool_manual_off_requested = restraints.append
        gateway._spa_manual_off_requested = restraints.append
        gateway.prepare_stop()
        for body in ("B1101", "B1202"):
            with pytest.raises(RuntimeError, match="stopping"):
                await gateway.async_set_body_active(body, False)
        assert restraints == []
        assert recorder.calls == []

    asyncio.run(scenario())


def test_stop_also_awaits_reobservation_cancelled_at_previous_purpose_boundary():
    async def scenario():
        module = _load_module()
        module._OWNED_PUMP_SESSION_REOBSERVATION_INTERVAL_SECONDS = 0.001
        runtime, _, _, coordinator, driver = _runtime(module)
        started, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def refresh():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                await release.wait()
            return True

        coordinator.async_refresh_native_owned_pump_session_evidence = refresh
        driver.requested_enabled = True
        driver.pump_session_purpose = PumpSpeedSessionPurpose.PRIMING
        runtime._sync_owned_pump_session_reobservation()
        task = runtime._owned_pump_session_reobservation_task
        await started.wait()
        driver.pump_session_purpose = None
        runtime._sync_owned_pump_session_reobservation()
        await cancelling.wait()
        assert runtime._owned_pump_session_reobservation_task is None
        stop = asyncio.create_task(runtime.async_unload())
        await asyncio.sleep(0)
        try:
            assert not stop.done(), "STOP dropped a cancelling previous-purpose reread"
            release.set()
            await stop
            assert task is not None and task.done()
        finally:
            release.set()
            await asyncio.gather(task, stop, return_exceptions=True)

    asyncio.run(scenario())
