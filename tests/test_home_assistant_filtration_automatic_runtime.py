"""Behavioral tests for the HA automatic filtration lifecycle bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from poolos.external_change import ExternalChangeBatch
from poolos.grid_outage_confirmation import GridOutageDisposition
from poolos.physical_command_authority import PhysicalAuthorityReason
from poolos.thermal_runtime_orchestration import ThermalOrchestrationLifecycle


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "filtration_automatic_runtime.py"
PACKAGE_NAME = "poolos_filtration_automatic_runtime_behavior_test"
NOW = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)


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
        ("filtration_runtime", "PoolOSFiltrationRuntime"),
        ("manual_intellicenter", "ManualIntelliCenterControl"),
        ("observation", "ObservationSnapshot"),
        ("thermal_runtime", "PoolOSThermalRuntime"),
    ):
        stub = ModuleType(f"{PACKAGE_NAME}.{name}")
        setattr(stub, symbol, object)
        sys.modules[stub.__name__] = stub
    delivery = ModuleType(f"{PACKAGE_NAME}.filtration_live_delivery")
    delivery.ManualIntelliCenterFiltrationDelivery = object
    sys.modules[delivery.__name__] = delivery

    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.filtration_automatic_runtime",
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
    failed: list[str] = field(default_factory=list)
    unloaded: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    def set_enabled(self, enabled: bool, **_: object) -> None:
        self.requested_enabled = enabled

    def process_disabled_epoch(self, frame: object) -> None:
        self.last_epoch_identity = frame.epoch_identity
        self.disabled_epochs.append(frame.epoch_identity)

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
    configurations: list[bool] = field(default_factory=list)
    unloaded: bool = False

    def configure_automatic_filtration(self, *, enabled: bool) -> None:
        self.configurations.append(enabled)

    def begin_automatic_filtration_epoch(self, identity: str) -> None:
        self.epochs.append(identity)

    def unload_automatic_filtration_driver(self) -> None:
        self.unloaded = True


@dataclass
class FakeHass:
    tasks: list[asyncio.Task[object]] = field(default_factory=list)

    def async_create_task(
        self,
        coroutine: object,
        name: str,
    ) -> asyncio.Task[object]:
        assert name == "PoolOS automatic filtration execution epoch"
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
    runtime = module.PoolOSFiltrationAutomaticRuntime(
        hass=hass,
        coordinator=coordinator,
        filtration_runtime=SimpleNamespace(assessment=object()),
        thermal_runtime=SimpleNamespace(
            assessment=SimpleNamespace(pool_pump_circuit_id="p0102")
        ),
        ownership=SimpleNamespace(
            owner=SimpleNamespace(value="none"),
            filtration_lease=None,
            thermal_reserved_for=lambda _identity: False,
        ),
        authority=authority,
        manual=object(),
    )
    driver = FakeDriver()
    runtime.driver = driver
    return runtime, hass, authority, coordinator, driver


def _snapshot(at: datetime) -> SimpleNamespace:
    return SimpleNamespace(generated_at=at, observations=())


def _orchestration(identity: str, *, pool_candidate: bool = False) -> SimpleNamespace:
    from poolos.integration import ThermalBody

    return SimpleNamespace(
        snapshot_identity=identity,
        outage=SimpleNamespace(disposition=GridOutageDisposition.ON_GRID),
        candidate_body=ThermalBody.POOL if pool_candidate else None,
        lifecycle=(
            ThermalOrchestrationLifecycle.CANDIDATE_READY
            if pool_candidate
            else ThermalOrchestrationLifecycle.BLOCKED
        ),
    )


def test_disabled_runtime_never_schedules_and_enable_does_not_replay_cached_frame() -> None:
    module = _load_module()
    runtime, hass, _, _, driver = _runtime(module)
    runtime.observe(_snapshot(NOW), _orchestration("epoch-1"), external_changes=ExternalChangeBatch(()))
    runtime.set_enabled(True)

    assert driver.disabled_epochs == ["epoch-1"]
    assert driver.processed == []
    assert hass.tasks == []


def test_bridge_coalesces_new_truth_without_overlapping_tasks() -> None:
    async def scenario() -> None:
        module = _load_module()
        runtime, hass, authority, _, driver = _runtime(module)
        runtime.set_enabled(True)
        runtime.observe(_snapshot(NOW), _orchestration("epoch-1"), external_changes=ExternalChangeBatch(()))
        first = hass.tasks[0]
        await driver.started.wait()
        runtime.observe(
            _snapshot(NOW + timedelta(seconds=1)),
            _orchestration("epoch-2"),
            external_changes=ExternalChangeBatch(()),
        )

        assert driver.processed == ["epoch-1"]
        assert len(hass.tasks) == 1
        assert authority.epochs == ["epoch-1", "epoch-2"]

        driver.release.set()
        await first
        assert len(hass.tasks) == 2
        await hass.tasks[1]
        assert driver.processed == ["epoch-1", "epoch-2"]

    asyncio.run(scenario())


def test_orchestration_failure_invalidates_stale_filtration_execution_truth() -> None:
    module = _load_module()
    runtime, _, authority, coordinator, driver = _runtime(module)
    runtime.orchestration_failed(_snapshot(NOW), ValueError("test"))

    assert driver.failed == ["automatic_filtration_orchestration_failed:ValueError"]
    assert authority.epochs == [f"filtration-orchestration-failed:{NOW.isoformat()}"]
    assert coordinator.listener_updates == 1


def test_policy_candidate_without_automatic_thermal_reservation_does_not_preempt_filtration() -> None:
    module = _load_module()
    runtime, _, _, _, _ = _runtime(module)
    runtime.observe(
        _snapshot(NOW),
        _orchestration("epoch-1", pool_candidate=True),
        external_changes=ExternalChangeBatch(()),
    )
    assert runtime._latest_frame is not None
    assert runtime._latest_frame.thermal_candidate_ready is False


def test_unload_invalidates_authority_and_reconstructs_no_task_or_owner() -> None:
    async def scenario() -> None:
        module = _load_module()
        runtime, hass, authority, _, driver = _runtime(module)
        runtime.set_enabled(True)
        runtime.observe(_snapshot(NOW), _orchestration("epoch-1"), external_changes=ExternalChangeBatch(()))
        unload = asyncio.create_task(runtime.async_unload())
        await driver.started.wait()
        assert authority.unloaded
        assert driver.unloaded
        driver.release.set()
        await hass.tasks[0]
        await unload
        assert runtime._task is None

    asyncio.run(scenario())


def test_unload_preserves_commissioned_desired_filtration_gate_state() -> None:
    async def scenario() -> None:
        module = _load_module()
        runtime, _, _, _, driver = _runtime(module)

        runtime.set_enabled(True)

        assert runtime.enabled is True
        assert driver.requested_enabled is True

        await runtime.async_unload()

        assert driver.requested_enabled is False
        assert runtime.enabled is True

    asyncio.run(scenario())
