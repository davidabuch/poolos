"""Behavioral tests for the HA automatic thermal lifecycle bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from poolos.physical_command_authority import PhysicalAuthorityReason


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "thermal_automatic_runtime.py"
PACKAGE_NAME = "poolos_thermal_automatic_runtime_behavior_test"
NOW = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)


def _load_module() -> ModuleType:
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    homeassistant.core = core
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core

    package = ModuleType(PACKAGE_NAME)
    package.__path__ = [str(MODULE_PATH.parent)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package
    for name, symbol in (
        ("coordinator", "PoolOSCoordinator"),
        ("manual_intellicenter", "ManualIntelliCenterControl"),
        ("observation", "ObservationSnapshot"),
        ("thermal_runtime", "PoolOSThermalRuntime"),
    ):
        stub = ModuleType(f"{PACKAGE_NAME}.{name}")
        setattr(stub, symbol, object)
        sys.modules[stub.__name__] = stub
    delivery = ModuleType(f"{PACKAGE_NAME}.thermal_live_delivery")
    delivery.ManualIntelliCenterThermalLiveDelivery = object
    sys.modules[delivery.__name__] = delivery

    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.thermal_automatic_runtime",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeDriver:
    requested_enabled: bool = False
    last_epoch_identity: str | None = None
    processed: list[str] = field(default_factory=list)
    disabled_epochs: list[str] = field(default_factory=list)
    enabled_changes: list[bool] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    unloaded: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    def set_enabled(self, enabled: bool, **_: object) -> None:
        self.requested_enabled = enabled
        self.enabled_changes.append(enabled)

    def note_disabled_epoch(self, frame: object) -> None:
        identity = frame.epoch_identity
        self.last_epoch_identity = identity
        self.disabled_epochs.append(identity)

    def restrictive_authority_changed(self, **_: object) -> None:
        self.last_epoch_identity = None

    async def process_epoch(self, frame: object, **_: object) -> None:
        self.processed.append(frame.epoch_identity)
        self.started.set()
        await self.release.wait()
        self.last_epoch_identity = frame.epoch_identity

    def fail_closed(self, *, reason: str, **_: object) -> None:
        self.failed.append(reason)

    def unload(self, **_: object) -> None:
        self.unloaded = True
        self.requested_enabled = False

    def diagnostics(self) -> dict[str, object]:
        return {"state": "test", "requested_enabled": self.requested_enabled}


@dataclass
class FakeAuthority:
    base_authority_reason: PhysicalAuthorityReason = PhysicalAuthorityReason.ALLOWED
    epochs: list[str] = field(default_factory=list)
    configurations: list[tuple[bool, bool, str]] = field(default_factory=list)
    unloaded: bool = False
    unload_started: asyncio.Event = field(default_factory=asyncio.Event)

    def configure_automatic_thermal(
        self,
        *,
        driver_enabled: bool,
        thermal_live_enabled: bool,
        commissioning_scope: str,
    ) -> None:
        self.configurations.append(
            (driver_enabled, thermal_live_enabled, commissioning_scope)
        )

    def begin_automatic_thermal_epoch(self, identity: str) -> None:
        self.epochs.append(identity)

    def unload_automatic_thermal_driver(self) -> None:
        self.unloaded = True
        self.unload_started.set()


@dataclass
class FakeHass:
    tasks: list[asyncio.Task[object]] = field(default_factory=list)

    def async_create_task(
        self,
        coroutine: object,
        name: str,
    ) -> asyncio.Task[object]:
        assert name == "PoolOS automatic thermal execution epoch"
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task


def _runtime(module: ModuleType):
    hass = FakeHass()
    authority = FakeAuthority()
    coordinator = SimpleNamespace(
        listener_updates=0,
        async_update_listeners=lambda: setattr(
            coordinator,
            "listener_updates",
            coordinator.listener_updates + 1,
        ),
    )
    thermal = SimpleNamespace(
        effective_live_enabled=True,
        commissioning_scope=SimpleNamespace(value="pool"),
    )
    runtime = module.PoolOSThermalAutomaticRuntime(
        hass=hass,
        coordinator=coordinator,
        thermal_runtime=thermal,
        orchestrator=object(),
        authority=authority,
        manual=object(),
    )
    driver = FakeDriver()
    runtime.driver = driver
    runtime._sync_authority_configuration()
    return runtime, hass, authority, coordinator, driver


def _snapshot(at: datetime) -> SimpleNamespace:
    return SimpleNamespace(generated_at=at, observations=())


def _orchestration(at: datetime, identity: str) -> SimpleNamespace:
    return SimpleNamespace(snapshot_identity=identity, evaluated_at=at)


def test_disabled_runtime_never_schedules_and_enable_does_not_replay_cached_frame() -> None:
    module = _load_module()
    runtime, hass, _, _, driver = _runtime(module)
    runtime.observe(_snapshot(NOW), None, _orchestration(NOW, "epoch-1"))

    runtime.set_enabled(True)

    assert driver.disabled_epochs == ["epoch-1"]
    assert driver.processed == []
    assert hass.tasks == []


def test_bridge_coalesces_new_truth_without_overlapping_driver_tasks() -> None:
    async def scenario() -> None:
        module = _load_module()
        runtime, hass, authority, _, driver = _runtime(module)
        runtime.set_enabled(True)
        runtime.observe(
            _snapshot(NOW),
            None,
            _orchestration(NOW, "epoch-1"),
        )
        first = hass.tasks[0]
        await driver.started.wait()
        runtime.observe(
            _snapshot(NOW + timedelta(seconds=1)),
            None,
            _orchestration(NOW + timedelta(seconds=1), "epoch-2"),
        )

        assert len(hass.tasks) == 1
        assert driver.processed == ["epoch-1"]
        assert authority.epochs == ["epoch-1", "epoch-2"]

        driver.release.set()
        await first
        assert len(hass.tasks) == 2
        await hass.tasks[1]
        assert driver.processed == ["epoch-1", "epoch-2"]

    asyncio.run(scenario())


def test_unload_invalidates_final_authority_and_waits_for_inflight_task() -> None:
    async def scenario() -> None:
        module = _load_module()
        runtime, hass, authority, _, driver = _runtime(module)
        runtime.set_enabled(True)
        runtime.observe(_snapshot(NOW), None, _orchestration(NOW, "epoch-1"))
        unload = asyncio.create_task(runtime.async_unload())
        await authority.unload_started.wait()

        assert authority.unloaded
        assert driver.unloaded
        assert not unload.done()

        driver.release.set()
        await hass.tasks[0]
        await unload
        assert runtime._task is None

    asyncio.run(scenario())
