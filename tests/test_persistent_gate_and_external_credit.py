"""HA service/RestoreEntity races and native external-circulation accounting."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from test_home_assistant_native_switch import _load_executable_switch_module
from test_reset_recovery_lifecycle import _button_module, _snapshot


class Gate:
    def __init__(self):
        self.enabled = False
        self.calls = []
        self.driver = Mock()
        self.circulation_ownership = Mock()
        self.note_reset_authority_reopened = Mock()
        self.arm_restart_recovery_adoption = Mock()
        self.arm_quick_restart_recovery = Mock()

    def set_enabled(self, value):
        self.calls.append(value)
        self.enabled = value


def reset_switch_fixture(monkeypatch):
    switch_module = _load_executable_switch_module()
    button_module = _button_module(monkeypatch)
    gate = Gate()
    listeners = []
    runtime = SimpleNamespace(
        thermal_automatic_runtime=gate,
        physical_command_authority=PoolOSPhysicalCommandAuthority(),
        thermal_runtime_orchestrator=Mock(),
        manual_intellicenter=SimpleNamespace(
            async_set_body_active=AsyncMock(), async_set_body_heat_source=AsyncMock()),
        pool_automatic_control=Mock(), spa_automatic_control=Mock(),
    )
    coordinator = SimpleNamespace(native_intellicenter_snapshot=_snapshot(active=False, rpm=0),
        async_add_listener=lambda cb: listeners.append(cb) or (lambda: None))
    runtime.coordinator = coordinator
    async def refresh():
        coordinator.native_intellicenter_snapshot = _snapshot(active=False, rpm=0)
        for cb in tuple(listeners):
            cb()
    coordinator.async_refresh_native_reset_baseline_evidence = AsyncMock(return_value=True)
    coordinator.async_request_refresh = AsyncMock(side_effect=refresh)
    entry = SimpleNamespace(runtime_data=runtime, entry_id="operator-gate", async_on_unload=Mock())
    button = button_module.PoolOSResetControlButton(coordinator, entry)
    entity = switch_module.PoolOSThermalAutomaticExecutionSwitch(entry)
    publications = []
    entity.async_write_ha_state = lambda: publications.append(entity.is_on)
    entity.async_on_remove = Mock()
    return entity, button, entry, gate, publications


@pytest.mark.parametrize("continuation", ["completion", "refresh", "delayed_restore", "readd"])
def test_operator_off_survives_real_reset_and_post_reset_publication(monkeypatch, continuation):
    async def run():
        entity, button, entry, gate, publications = reset_switch_fixture(monkeypatch)
        await entity.async_turn_on()
        entered = asyncio.Event()
        release = asyncio.Event()
        async def old_state():
            entered.set()
            await release.wait()
            return SimpleNamespace(state="on", attributes={})
        entity.async_get_last_state = old_state
        task = asyncio.create_task(entity.async_added_to_hass())
        waiting = asyncio.create_task(entered.wait())
        await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        await entity.async_turn_off()
        off_index = len(gate.calls)
        await button.async_press()
        assert not entity.is_on
        await button.coordinator.async_request_refresh()
        for _ in range(3):
            await asyncio.sleep(0)
        # The old restore future may resolve arbitrarily later (the live
        # callback was ~93 seconds later); elapsed time cannot increase its priority.
        release.set()
        await task
        if continuation == "readd":
            replacement = type(entity)(entry)
            replacement.async_on_remove = Mock()
            replacement.async_write_ha_state = Mock()
            replacement.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="on", attributes={}))
            await replacement.async_added_to_hass()
        entity.async_write_ha_state()
        assert not entity.is_on
        assert True not in gate.calls[off_index:]
        assert publications[-1] is False
        entry.runtime_data.manual_intellicenter.async_set_body_active.assert_not_called()
        entry.runtime_data.manual_intellicenter.async_set_body_heat_source.assert_not_called()
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


def test_reset_preserves_explicit_on_and_never_calls_enable(monkeypatch):
    async def run():
        entity, button, _, gate, _ = reset_switch_fixture(monkeypatch)
        await entity.async_turn_on()
        before = list(gate.calls)
        await button.async_press()
        await asyncio.sleep(0)
        assert entity.is_on
        assert gate.calls == before
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


@pytest.mark.parametrize("previous", ["on", "off"])
def test_restart_restores_latest_explicit_gate_state_without_session(monkeypatch, previous):
    async def run():
        entity, button, _, _, publications = reset_switch_fixture(monkeypatch)
        await (entity.async_turn_on() if previous == "on" else entity.async_turn_off())
        persisted = SimpleNamespace(state="on" if publications[-1] else "off", attributes={})
        restarted, fresh_button, _, gate, _ = reset_switch_fixture(monkeypatch)
        restarted.async_get_last_state = AsyncMock(return_value=persisted)
        await restarted.async_added_to_hass()
        assert restarted.is_on == (previous == "on")
        gate.driver.restrictive_authority_changed.assert_not_called()
        await button.coordinator.background_tasks.async_stop()
        await fresh_button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["ThermalAutomatic", "FiltrationAutomatic", "GridOutagePhysicalSafety", "ThermalLive"])
def test_sibling_persistent_gate_restore_cannot_overwrite_explicit_off(kind):
    async def run():
        module = _load_executable_switch_module()
        gate = Gate()
        gate.effective_live_enabled = False
        gate.set_effective_live_enabled = lambda value: setattr(gate, "effective_live_enabled", value)
        gate.authority_configuration_changed = Mock()
        runtime = SimpleNamespace(thermal_automatic_runtime=gate, filtration_automatic_runtime=gate,
            grid_outage_safety_runtime=gate, thermal_runtime=gate,
            coordinator=SimpleNamespace(async_add_listener=lambda cb: lambda: None))
        entity = getattr(module, f"PoolOS{kind}ExecutionSwitch" if kind != "GridOutagePhysicalSafety" else "PoolOSGridOutagePhysicalSafetySwitch")(
            SimpleNamespace(entry_id=kind, runtime_data=runtime))
        entity.async_on_remove = Mock()
        entity.async_write_ha_state = Mock()
        entered = asyncio.Event()
        release = asyncio.Event()
        async def restore():
            entered.set()
            await release.wait()
            return SimpleNamespace(state="on", attributes={})
        entity.async_get_last_state = restore
        task = asyncio.create_task(entity.async_added_to_hass())
        await entered.wait()
        await entity.async_turn_off()
        release.set()
        await task
        assert not entity.is_on
    asyncio.run(run())


def test_external_pool_solar_periodic_native_read_keeps_accounting_current(monkeypatch):
    from test_systemic_arbitration_currentness import native_loop
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder
    from test_native_coordinator_refresh_coalescing import _load_coordinator_module
    from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
    from test_home_assistant_native_authoritative_cutover import _load_component_module

    async def run():
        async with native_loop(monkeypatch) as (transport, clock, noise, capture):
            transport._model["B1101"].properties.update(STATUS="ON", HEATER="H0002", HTMODE="1")
            transport._model["P0001"].properties["RPM"] = 2600
            transport._model["C0002"].properties["STATUS"] = "ON"
            native = await capture()
            coordinator_type = _load_coordinator_module().PoolOSCoordinator
            from datetime import datetime
            class CoordinatorClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return clock[0]
            monkeypatch.setitem(coordinator_type._async_update_data.__globals__, "datetime", CoordinatorClock)
            coordinator = object.__new__(coordinator_type)
            coordinator._unloading = False
            coordinator.data = None
            coordinator._observation_lock = asyncio.Lock()
            coordinator._reconciliation_refresh_count = 0
            coordinator.independent_intellicenter_transport = transport
            coordinator.native_intellicenter_snapshot = native
            accounting = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
            authoritative = _load_component_module("authoritative")
            async def observe(**kwargs):
                assert kwargs["observed_at"] == clock[0]
                snapshot = authoritative.build_authoritative_snapshot(
                    native_snapshot=NativeIntelliCenterReadAdapter().capture(transport, generated_at=kwargs["observed_at"]),
                    options={}, states={}, now=kwargs["observed_at"])
                accounting.refresh(snapshot)
                coordinator.data = snapshot
                coordinator.native_intellicenter_snapshot = snapshot.native_snapshot
                return snapshot
            coordinator._async_observe = observe
            coordinator._async_refresh_native_runtime_evidence = partial(coordinator_type._async_refresh_native_runtime_evidence, coordinator)
            for _ in range(121):
                # Actual RPM callbacks do not refresh unchanged BODY or source.
                transport._controller._apply_updates([{"objnam":"P0001", "params":{"RPM":2600}}])
                await coordinator._async_update_data()
                clock[0] += timedelta(seconds=30)
            assert accounting.assessment.currently_earning_credit
            assert accounting.assessment.credited_runtime == timedelta(hours=1)
            assert accounting.assessment.authority == "none"
            assert accounting.assessment.command_delivery_enabled is False
    asyncio.run(run())


def test_unrelated_stale_native_temperature_cannot_poison_fresh_body_credit():
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder, snapshot, LOCAL
    from datetime import datetime
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 10, 4, 11, tzinfo=LOCAL)
    shared_id = "intellicenter_native:test:BODY:B1101"
    for seconds in (0, 60):
        at = start + timedelta(seconds=seconds)
        view = snapshot(at, pool_active=True, solar_active=True)
        view.observations = tuple(replace(item,
            source_id=shared_id if item.observation_id in {"pool.active", "pool.temperature"} else item.source_id,
            observed_at=at - timedelta(seconds=121) if item.observation_id == "pool.temperature" else at)
            for item in view.observations)
        view.stale_entities = (shared_id,)
        runtime.refresh(view)
    assert runtime.assessment.currently_earning_credit
    assert runtime.assessment.credited_runtime == timedelta(seconds=60)
    assert runtime.assessment.highest_validated_pool_temperature_f is None


@pytest.mark.parametrize("concept", ["pool.active", "spa.active", "pump.rpm"])
def test_stale_critical_native_fact_cannot_earn_credit_even_if_health_is_good(concept):
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder, snapshot, LOCAL
    from datetime import datetime
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 10, 4, 11, tzinfo=LOCAL)
    view = snapshot(start, pool_active=True, solar_active=True)
    view.observations = tuple(replace(item, observed_at=start - timedelta(seconds=121))
        if item.observation_id == concept else item for item in view.observations)
    runtime.refresh(view)
    assert not runtime.assessment.currently_earning_credit


@pytest.mark.parametrize("complete", [False, True])
def test_external_solar_credit_then_later_tou_uses_exact_remaining_debt(complete):
    from datetime import datetime
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder, snapshot, LOCAL
    from test_filtration_automatic_execution import _enabled_driver, _frame
    from poolos.filtration_policy import FiltrationDisposition
    from poolos.integration import SetBodyActive

    async def run():
        runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
        start = datetime(2026, 10, 4, 8, tzinfo=LOCAL)
        for minute in range(3):
            runtime.refresh(snapshot(start + timedelta(minutes=minute), pool_active=True, solar_active=True))
        required = runtime.assessment.required_runtime
        duration = required if complete else timedelta(hours=1)
        minute = 3
        while timedelta(minutes=minute) <= duration:
            runtime.refresh(snapshot(start + timedelta(minutes=minute), pool_active=True, solar_active=True))
            minute += 1
        end = start + duration
        # A real user OFF closes the last provable interval; accounting issues
        # no shutdown and retains no BODY/PUMP/THERMAL provenance.
        runtime.refresh(snapshot(end + timedelta(seconds=1), pool_active=False, rpm=0))
        credited = runtime.assessment.credited_runtime
        assert credited == min(required, duration + timedelta(seconds=1))
        assert runtime.assessment.total_remaining_runtime == max(timedelta(0), required - credited)
        assert runtime.assessment.authority == "none"
        tou = start.replace(hour=22, minute=1)
        runtime.refresh(snapshot(tou, pool_active=False, rpm=0))
        driver, delivery, factory = _enabled_driver()
        frame = replace(_frame(tou, pool=False, rpm=0, configured=2600), filtration=runtime.assessment)
        delivery.issued_at = tou
        await driver.process_epoch(frame, delivery_factory=factory)
        if complete:
            assert runtime.assessment.disposition is FiltrationDisposition.SATISFIED
            assert not delivery.operations
            assert driver.ownership.filtration_lease is None
        else:
            assert runtime.assessment.independent_disposition is FiltrationDisposition.RUN_NOW
            assert len(delivery.operations) == 1
            assert isinstance(delivery.operations[0], SetBodyActive)
            assert delivery.operations[0].active
            assert driver.ownership.filtration_lease is not None
    asyncio.run(run())


@pytest.mark.parametrize("solar", [False, True])
@pytest.mark.parametrize("rpm,spa,credit", [(2600,False,True), (700,False,False), (2600,True,False)])
def test_external_circulation_credit_is_physical_route_and_rpm_not_owner(solar, rpm, spa, credit):
    from datetime import datetime
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder, snapshot, LOCAL
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 10, 4, 8, tzinfo=LOCAL)
    for minute in (0, 30, 60):
        runtime.refresh(snapshot(start + timedelta(minutes=minute), pool_active=True,
            spa_active=spa, rpm=rpm, solar_active=solar))
    assert runtime.assessment.credited_runtime == (timedelta(hours=1) if credit else timedelta(0))
    assert runtime.assessment.currently_earning_credit is credit
    assert runtime.assessment.authority == "none"
    assert runtime.assessment.command_delivery_enabled is False


def test_external_credit_restart_duplicate_and_delayed_intervals_never_double_count():
    from datetime import datetime
    from test_home_assistant_filtration_runtime import PoolOSFiltrationRuntime, FakeCoordinator, FakeRecorder, snapshot, recorded, LOCAL
    start = datetime(2026, 10, 4, 8, tzinfo=LOCAL)
    history = tuple(replace(event, observations=tuple(
        {**item, "value": True} if item["observation_id"] == "solar.active" else item
        for item in event.observations))
        for event in (recorded(start + timedelta(minutes=m), pool_active=True) for m in (0,30,60)))
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(history)))
    asyncio.run(runtime.async_restore(restored_at=start + timedelta(hours=1)))
    before = runtime.assessment.credited_runtime
    assert before == timedelta(hours=1)
    # Reviewed restore overlap reconstructs only the recorded interval. The
    # unobserved restart gap is not credited; subsequent fresh work is.
    for minute in (60, 60, 61, 45, 62, 62):
        runtime.refresh(snapshot(start + timedelta(minutes=minute), pool_active=True, solar_active=True))
    assert runtime.assessment.credited_runtime == before + timedelta(minutes=2)
    assert runtime.assessment.temporal_regressions_ignored >= 1


@pytest.mark.parametrize("kind", ["MaintenanceMode", "PoolAutonomousControl", "SpaAutonomousControl"])
@pytest.mark.parametrize("enabled", [False, True])
def test_sibling_restraints_restore_cannot_overwrite_newer_operator_choice(kind, enabled):
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppression, SpaAutomaticControlSuppression
    from test_home_assistant_filtration_runtime import LOCAL
    async def run():
        module = _load_executable_switch_module()
        runtime = SimpleNamespace(physical_command_authority=PoolOSPhysicalCommandAuthority(),
            external_change_runtime=Mock(), pool_automatic_control=PoolAutomaticControlSuppression(),
            spa_automatic_control=SpaAutomaticControlSuppression(),
            coordinator=SimpleNamespace(local_timezone=LOCAL, async_update_listeners=Mock()))
        entity = getattr(module, f"PoolOS{kind}Switch")(SimpleNamespace(entry_id="sibling", runtime_data=runtime))
        entity.async_on_remove = Mock()
        entity.async_write_ha_state = Mock()
        entered = asyncio.Event()
        release = asyncio.Event()
        async def restore():
            entered.set()
            await release.wait()
            return SimpleNamespace(state="off" if enabled else "on", attributes={})
        entity.async_get_last_state = restore
        task = asyncio.create_task(entity.async_added_to_hass())
        await entered.wait()
        await (entity.async_turn_on() if enabled else entity.async_turn_off())
        release.set()
        await task
        assert entity.is_on is enabled
    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_config_reload_operator_intent_handover_beats_opposite_restore(monkeypatch, enabled):
    """Execute the actual setup handover statements, then actual switch restore."""
    import ast
    from pathlib import Path
    async def run():
        entity, button, entry, _, _ = reset_switch_fixture(monkeypatch)
        await (entity.async_turn_on() if enabled else entity.async_turn_off())
        old_runtime = entry.runtime_data
        new_gate = Gate()
        tree = ast.parse((Path(__file__).resolve().parents[1] / "custom_components/poolos/__init__.py").read_text())
        setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
        nodes = [n for n in setup.body if (
            isinstance(n, ast.Assign) and (
                any(isinstance(t, ast.Name) and t.id == "prior_operator_intents" for t in n.targets)
                or any(isinstance(t, ast.Attribute) and t.attr == "runtime_data" for t in n.targets)))
            or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "update"
                and isinstance(n.value.func.value, ast.Attribute) and n.value.func.value.attr == "persistent_gate_intents")]
        assert len(nodes) == 3
        def data(**kwargs):
            return SimpleNamespace(**kwargs, persistent_gate_intents={}, restored_gate_intents=set())
        scope = {n.id: Mock() for node in nodes for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        scope.update(entry=entry, PoolOSRuntimeData=data, getattr=getattr, dict=dict,
            coordinator=old_runtime.coordinator, thermal_automatic_runtime=new_gate)
        from datetime import datetime, UTC
        scope.update(datetime=datetime, UTC=UTC)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "setup_gate_handover", "exec"), scope)
        replacement = type(entity)(entry)
        replacement.async_on_remove = Mock()
        replacement.async_write_ha_state = Mock()
        replacement.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="off" if enabled else "on", attributes={}))
        await replacement.async_added_to_hass()
        assert replacement.is_on is enabled
        assert entry.runtime_data.persistent_gate_intents == old_runtime.persistent_gate_intents
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


def test_reload_explicit_on_does_not_admit_cached_pre_off_checkpoint(monkeypatch):
    from poolos.thermal_runtime_ownership import ThermalQuickRestartCheckpoint
    async def run():
        entity, button, _, _, _ = reset_switch_fixture(monkeypatch)
        await entity.async_turn_off()
        await entity.async_turn_on()
        # New config-entry runtime inherits current desired intent, not a
        # permission to use an old cache's physical checkpoint after OFF.
        gate = Gate()
        current = SimpleNamespace(thermal_automatic_runtime=gate,
            coordinator=button.coordinator,
            persistent_gate_intents=dict(entity._runtime.persistent_gate_intents))
        replacement = type(entity)(SimpleNamespace(entry_id="operator-gate", runtime_data=current))
        replacement.async_on_remove = Mock()
        replacement.async_write_ha_state = Mock()
        replacement.async_get_last_state = AsyncMock(return_value=SimpleNamespace(
            state="on", attributes={"quick_restart_checkpoint": {"old": "verified_before_off"}}))
        parser = Mock(return_value=object())
        monkeypatch.setattr(ThermalQuickRestartCheckpoint, "from_restore_state", parser)
        await replacement.async_added_to_hass()
        assert replacement.is_on
        parser.assert_not_called()
        gate.arm_quick_restart_recovery.assert_not_called()
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


def test_restored_on_uses_actual_runtime_fresh_epoch_gate_without_delivery():
    from test_home_assistant_thermal_automatic_runtime import _load_module, _runtime
    from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus
    async def run():
        runtime, _, _, coordinator, _ = _runtime(_load_module())
        runtime.orchestrator = ThermalRuntimeOrchestrator()
        runtime.driver = ThermalAutomaticExecutionDriver(runtime.orchestrator)
        coordinator.async_add_listener = lambda cb: lambda: None
        entity = _load_executable_switch_module().PoolOSThermalAutomaticExecutionSwitch(
            SimpleNamespace(entry_id="fresh-restore", runtime_data=SimpleNamespace(
                thermal_automatic_runtime=runtime, coordinator=coordinator)))
        entity.async_on_remove = Mock()
        entity.async_write_ha_state = Mock()
        entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="on", attributes={}))
        await entity.async_added_to_hass()
        assert entity.is_on
        assert runtime.driver.requested_enabled
        assert runtime.driver.assessment.blocker == "automatic_thermal_fresh_epoch_required_after_enable"
        assert not runtime.driver.assessment.command_delivery_performed
        assert runtime.driver.active_session is None
        assert runtime.orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
        assert runtime._task is None
    asyncio.run(run())


@pytest.mark.parametrize("spa", [False, True])
def test_real_reset_preserves_explicit_body_autonomy_off(monkeypatch, spa):
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppression, SpaAutomaticControlSuppression
    async def run():
        _, button, entry, _, _ = reset_switch_fixture(monkeypatch)
        entry.runtime_data.pool_automatic_control = PoolAutomaticControlSuppression()
        entry.runtime_data.spa_automatic_control = SpaAutomaticControlSuppression()
        cls = (_load_executable_switch_module().PoolOSSpaAutonomousControlSwitch if spa
            else _load_executable_switch_module().PoolOSPoolAutonomousControlSwitch)
        entity = cls(entry)
        entity.async_write_ha_state = Mock()
        await entity.async_turn_off()
        assert not entity.is_on
        await button.async_press()
        await asyncio.sleep(0)
        assert not entity.is_on
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())


@pytest.mark.parametrize("spa", [False, True])
def test_real_reset_still_clears_transient_body_session_cancellation(monkeypatch, spa):
    from datetime import datetime, UTC
    from poolos.pool_automatic_control_suppression import (
        PoolAutomaticControlSuppression, SpaAutomaticControlSuppression,
        PoolAutomaticControlSuppressionSource, SpaAutomaticControlSuppressionSource)
    async def run():
        _, button, entry, _, _ = reset_switch_fixture(monkeypatch)
        entry.runtime_data.pool_automatic_control = PoolAutomaticControlSuppression()
        entry.runtime_data.spa_automatic_control = SpaAutomaticControlSuppression()
        control = entry.runtime_data.spa_automatic_control if spa else entry.runtime_data.pool_automatic_control
        source = (SpaAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF if spa
            else PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF)
        control.suppress(source=source, suppressed_at=datetime.now(UTC), reason="positive_session_off")
        await button.async_press()
        await asyncio.sleep(0)
        assert not control.state.suppressed
        await button.coordinator.background_tasks.async_stop()
    asyncio.run(run())
