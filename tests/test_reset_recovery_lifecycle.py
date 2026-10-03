"""Behavioral Reset recovery across the HA button/native observation boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority


def _button_module(monkeypatch):
    package = ModuleType("_reset_lifecycle_poolos")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/poolos")]
    package.PoolOSRuntimeData = object
    monkeypatch.setitem(sys.modules, package.__name__, package)

    class Entity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    for name, values in {
        "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
        "homeassistant.config_entries": {"ConfigEntry": Entity},
        "homeassistant.core": {"HomeAssistant": object},
        "homeassistant.helpers.entity": {"EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic")},
        "homeassistant.helpers.entity_platform": {"AddConfigEntryEntitiesCallback": object},
        "homeassistant.helpers.update_coordinator": {"CoordinatorEntity": Entity},
        f"{package.__name__}.const": {"DOMAIN": "poolos"},
        f"{package.__name__}.coordinator": {"PoolOSCoordinator": object},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        f"{package.__name__}.button", Path(package.__path__[0]) / "button.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _snapshot(*, active, rpm):
    at = datetime.now(UTC)
    return SimpleNamespace(
        generated_at=at,
        observations=tuple(
            SimpleNamespace(
                observation_id=key, value=value, observed_at=at, quality="good",
                source_kind="live", source_id="intellicenter_native:test:object",
            )
            for key, value in {
                "pool.active": active, "spa.active": False, "pump.rpm": rpm,
                "pool.raw_heater_id": "H0002" if active else "00000",
                "spa.raw_heater_id": "00000", "solar.active": active, "heater.active": False,
            }.items()
        ),
    )


def test_reset_listener_completion_schedules_fresh_post_close_epoch(monkeypatch):
    """Listener fallback must publish a fresh epoch after Reset authority closes."""

    module = _button_module(monkeypatch)

    async def run():
        listeners = []
        authority = PoolOSPhysicalCommandAuthority()
        runtime = SimpleNamespace(
            physical_command_authority=authority,
            manual_intellicenter=SimpleNamespace(
                async_set_body_heat_source=AsyncMock(),
                async_set_body_active=AsyncMock(),
            ),
            thermal_automatic_runtime=SimpleNamespace(
                driver=Mock(),
                circulation_ownership=Mock(),
                note_reset_authority_reopened=Mock(),
            ),
            thermal_runtime_orchestrator=Mock(),
            pool_automatic_control=Mock(),
            spa_automatic_control=Mock(),
        )
        post_close_refresh = AsyncMock()
        coordinator = SimpleNamespace(
            native_intellicenter_snapshot=_snapshot(active=False, rpm=0),
            async_request_refresh=post_close_refresh,
            async_add_listener=lambda listener: (
                listeners.append(listener) or (lambda: listeners.remove(listener))
            ),
        )
        entry = SimpleNamespace(
            runtime_data=runtime,
            entry_id="test",
            async_on_unload=Mock(),
        )
        button = module.PoolOSResetControlButton(coordinator, entry)

        generation = authority.begin_reset_recovery()
        button._reset_generation = generation
        button._reset_observation_after = datetime.now(UTC) - timedelta(seconds=1)
        button._reset_running = False
        button._reset_sessions_invalidated = True

        button._observe_reset_completion()
        await asyncio.sleep(0)

        assert not authority.reset_recovery_active
        runtime.thermal_automatic_runtime.note_reset_authority_reopened.assert_called_once_with()
        post_close_refresh.assert_awaited_once_with()

    asyncio.run(run())


@pytest.mark.parametrize("exit_path", [
    "window_exhausted", "cancelled_final_refresh", "delivery_exception", "cancelled_reduction",
    "actual_task_cancel",
])
@pytest.mark.parametrize("unusable", ["stale", "missing", "old_epoch", "bad_quality", "simulated"])
def test_reset_safe_native_update_closes_fence_after_button_exits(monkeypatch, exit_path, unusable):
    """A later safe snapshot must recover without pressing Reset or restarting HA."""
    module = _button_module(monkeypatch)

    async def run():
        listeners = []
        authority = PoolOSPhysicalCommandAuthority()
        runtime = SimpleNamespace(
            physical_command_authority=authority,
            manual_intellicenter=SimpleNamespace(
                async_set_body_heat_source=AsyncMock(), async_set_body_active=AsyncMock()
            ),
            thermal_automatic_runtime=SimpleNamespace(
                driver=Mock(),
                circulation_ownership=Mock(),
                note_reset_authority_reopened=Mock(),
            ),
            thermal_runtime_orchestrator=Mock(),
            pool_automatic_control=Mock(), spa_automatic_control=Mock(),
        )

        refresh_entered = asyncio.Event()

        async def refresh():
            if exit_path == "actual_task_cancel":
                if refresh_entered.is_set():
                    raise asyncio.CancelledError
                coordinator.native_intellicenter_snapshot = _snapshot(active=False, rpm=900)
                refresh_entered.set()
                await asyncio.Future()
            if exit_path == "cancelled_final_refresh":
                raise asyncio.CancelledError

        coordinator = SimpleNamespace(
            native_intellicenter_snapshot=_snapshot(active=True, rpm=2900),
            async_request_refresh=refresh,
            async_add_listener=lambda listener: listeners.append(listener) or (lambda: listeners.remove(listener)),
            async_update_listeners=lambda: [listener() for listener in tuple(listeners)],
        )
        entry = SimpleNamespace(runtime_data=runtime, entry_id="test", async_on_unload=Mock())
        button = module.PoolOSResetControlButton(coordinator, entry)
        if exit_path in {"delivery_exception", "cancelled_reduction"}:
            runtime.manual_intellicenter.async_set_body_heat_source.side_effect = (
                RuntimeError("recoverable transport error")
                if exit_path == "delivery_exception" else asyncio.CancelledError()
            )
        monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
        try:
            if exit_path == "actual_task_cancel":
                task = asyncio.create_task(button.async_press())
                await refresh_entered.wait()
                task.cancel()
                await task
            else:
                await button.async_press()
        except (RuntimeError, asyncio.CancelledError):
            pass
        assert authority.reset_recovery_active
        generation = authority.reset_recovery_generation
        commands = runtime.manual_intellicenter.async_set_body_active.call_count
        coordinator.native_intellicenter_snapshot = _snapshot(active=False, rpm=900)
        coordinator.async_update_listeners()
        assert authority.reset_recovery_active
        bad = _snapshot(active=False, rpm=0)
        if unusable == "missing":
            bad.observations = tuple(o for o in bad.observations if o.observation_id != "spa.raw_heater_id")
        elif unusable == "stale":
            for item in bad.observations:
                item.observed_at -= timedelta(seconds=31)
        elif unusable == "old_epoch":
            for item in bad.observations:
                item.observed_at = button._reset_observation_after
        elif unusable == "bad_quality":
            bad.observations[0].quality = "invalid"
        else:
            bad.observations[0].source_kind = "simulated"
        coordinator.native_intellicenter_snapshot = bad
        coordinator.async_update_listeners()
        assert authority.reset_recovery_active
        coordinator.native_intellicenter_snapshot = _snapshot(active=False, rpm=0)
        coordinator.async_update_listeners()
        assert not authority.reset_recovery_active, (
            "Authoritative safe OFF/0 after button exit must close the same Reset epoch"
        )
        assert authority.reset_recovery_generation == generation
        assert runtime.manual_intellicenter.async_set_body_active.call_count == commands
        # Entry unload removes the continuation; constructing a new button does
        # not infer a Reset epoch from matching hardware or the authority flag.
        entry.async_on_unload.call_args.args[0]()
        assert not listeners
        authority.begin_reset_recovery()
        module.PoolOSResetControlButton(coordinator, entry)
        coordinator.async_update_listeners()
        assert authority.reset_recovery_active

    asyncio.run(run())


def test_reset_refresh_timeout_accepts_fresh_safe_native_truth(monkeypatch):
    """A timed-out explicit refresh may use independently arrived safe native truth."""
    module = _button_module(monkeypatch)

    async def run():
        authority = PoolOSPhysicalCommandAuthority()
        runtime = SimpleNamespace(
            physical_command_authority=authority,
            manual_intellicenter=SimpleNamespace(
                async_set_body_heat_source=AsyncMock(),
                async_set_body_active=AsyncMock(),
            ),
            thermal_automatic_runtime=SimpleNamespace(
                driver=Mock(), circulation_ownership=Mock()
            ),
            thermal_runtime_orchestrator=Mock(),
            pool_automatic_control=Mock(),
            spa_automatic_control=Mock(),
        )
        listeners = []

        async def refresh():
            return None

        coordinator = SimpleNamespace(
            native_intellicenter_snapshot=_snapshot(active=True, rpm=2900),
            async_request_refresh=refresh,
            async_add_listener=lambda listener: (
                listeners.append(listener) or (lambda: listeners.remove(listener))
            ),
        )

        async def timeout_with_safe_native_truth(awaitable, *, timeout):
            assert timeout == module._RESET_REFRESH_TIMEOUT_SECONDS
            awaitable.close()
            coordinator.native_intellicenter_snapshot = _snapshot(
                active=False, rpm=0
            )
            for listener in tuple(listeners):
                listener()
            raise TimeoutError

        entry = SimpleNamespace(
            runtime_data=runtime, entry_id="test", async_on_unload=Mock()
        )
        button = module.PoolOSResetControlButton(coordinator, entry)
        monkeypatch.setattr(module.asyncio, "wait_for", timeout_with_safe_native_truth)
        monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())

        await button.async_press()

        assert not authority.reset_recovery_active
        assert button._reset_running is False
        runtime.manual_intellicenter.async_set_body_heat_source.assert_awaited_once_with(
            "B1101", "00000", reset_recovery=True
        )
        runtime.manual_intellicenter.async_set_body_active.assert_awaited_once_with(
            "B1101", False, reset_recovery=True
        )

    asyncio.run(run())


def test_reset_owned_solar_reduces_then_acquires_fresh_solar_without_restart(monkeypatch):
    from test_thermal_automatic_execution import (
        NOW, FakeDelivery, FakeDeliveryFactory, _frame,
    )
    from poolos.integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed
    from poolos.ownership_evidence import OwnershipAuthority, OwnershipDomain
    from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator, ThermalRequestedMode

    module = _button_module(monkeypatch)

    async def run():
        orchestrator = ThermalRuntimeOrchestrator()
        driver = ThermalAutomaticExecutionDriver(orchestrator)
        evaluator = ThermalRuntimeEvaluator()
        authority = PoolOSPhysicalCommandAuthority()
        clock = NOW

        class Clock:
            @staticmethod
            def now(tz):
                return clock

        monkeypatch.setattr(module, "datetime", Clock)
        monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
        active, rpm, configured, source = False, 0, 2600, "00000"

        class Delivery(FakeDelivery):
            async def deliver(self, operation, *, correlation_id):
                assert not authority.reset_recovery_active
                return await super().deliver(operation, correlation_id=correlation_id)

        delivery = Delivery()
        factory = FakeDeliveryFactory(delivery, driver=driver)

        def frame(seconds):
            return _frame(
                orchestrator, NOW + timedelta(seconds=seconds), pool_active=active,
                spa_active=False, pump_rpm=rpm, configured_rpm=configured,
                pool_heater=source, solar_active=source == "H0002",
                pool_temperature=82, pool_target=90, solar_temperature=140,
                mode=ThermalRequestedMode.SOLAR, evaluator=evaluator, driver=driver,
                missing=("pool.temperature",) if seconds in {0, 1, 2, 3, 301, 302} else (),
            )

        baseline = frame(0)
        driver.note_disabled_epoch(baseline)
        driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

        async def heat(start, end):
            nonlocal clock, active, rpm, configured, source
            for second in range(start, end):
                clock = NOW + timedelta(seconds=second)
                before = len(delivery.calls)
                result = await driver.process_epoch(frame(second), delivery_factory=factory)
                for operation in delivery.calls[before:]:
                    if isinstance(operation, SetBodyActive):
                        active = operation.active
                        rpm = 2600 if active else 0
                    elif isinstance(operation, SetPumpSpeed):
                        rpm = configured = operation.rpm
                    elif isinstance(operation, SetHeatMode):
                        assert operation.mode is not PhysicalHeatMode.GAS
                        source = "H0002" if operation.mode is PhysicalHeatMode.SOLAR else "00000"
            assert active and rpm == 2900 and source == "H0002", result
            lease = orchestrator.ownership.state.lease
            assert all(lease.domain_state(domain).authority is OwnershipAuthority.POOLOS for domain in OwnershipDomain)
            return lease

        predecessor = await heat(1, 240)
        listeners = []
        runtime = SimpleNamespace(
            physical_command_authority=authority,
            manual_intellicenter=SimpleNamespace(
                async_set_body_heat_source=AsyncMock(), async_set_body_active=AsyncMock()
            ),
            thermal_automatic_runtime=SimpleNamespace(driver=driver, circulation_ownership=driver.circulation_ownership),
            thermal_runtime_orchestrator=orchestrator,
            pool_automatic_control=Mock(), spa_automatic_control=Mock(),
        )
        steps = iter(((True, 2900), (False, 900), (False, 0)))

        async def refresh():
            nonlocal clock
            clock += timedelta(seconds=1)
            body_on, actual = next(steps, (False, 0))
            snap = _snapshot(active=body_on, rpm=actual)
            for item in snap.observations:
                item.observed_at = clock
            coordinator.native_intellicenter_snapshot = snap
            for listener in tuple(listeners):
                listener()

        coordinator = SimpleNamespace(
            native_intellicenter_snapshot=_snapshot(active=True, rpm=2900),
            async_request_refresh=refresh,
            async_add_listener=lambda listener: listeners.append(listener) or (lambda: None),
        )
        entry = SimpleNamespace(runtime_data=runtime, entry_id="test", async_on_unload=Mock())
        button = module.PoolOSResetControlButton(coordinator, entry)
        await button.async_press()
        assert not authority.reset_recovery_active
        assert orchestrator.ownership.state.lease is None
        runtime.manual_intellicenter.async_set_body_active.assert_awaited_once_with(
            "B1101", False, reset_recovery=True
        )
        runtime.manual_intellicenter.async_set_body_heat_source.assert_awaited_once_with(
            "B1101", "00000", reset_recovery=True
        )
        active, rpm, configured, source = False, 0, 2600, "00000"
        successor = await heat(301, 550)
        assert successor.body_session_id != predecessor.body_session_id
        assert successor.body_activation != predecessor.body_activation
        assert not driver._reenable_required

    asyncio.run(run())
