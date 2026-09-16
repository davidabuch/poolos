"""Behavioral tests for the HA automatic thermal lifecycle bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
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


def test_unload_preserves_commissioned_desired_thermal_gate_state() -> None:
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


def test_unrelated_manual_pump_request_cannot_yield_current_thermal_pump() -> None:
    from poolos.ownership_evidence import OwnershipAuthority, OwnershipDomain
    from test_thermal_runtime_ownership import NOW as OWNERSHIP_NOW, verified_full_manager

    module = _load_module()
    runtime, *_ = _runtime(module)
    manager = verified_full_manager()
    runtime.orchestrator = SimpleNamespace(ownership=manager)
    request = SimpleNamespace(
        operation="pump_circuit_speed", target="different-pump",
        request_id="manual-other-pump", requested_value=3200,
    )
    runtime._record_operator_request(request, OWNERSHIP_NOW)
    lease = manager.state.lease
    assert lease is not None
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.POOLOS

    request.target = "p0102"
    runtime._record_operator_request(request, OWNERSHIP_NOW)
    lease = manager.state.lease
    assert lease is not None
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.OPERATOR
    assert lease.owns_body_activation and lease.owns_heat_source


def test_manual_pump_request_uses_current_session_equipment_after_plan_converges() -> None:
    from poolos.ownership_evidence import OwnershipAuthority, OwnershipDomain
    from poolos.pump_speed_session import PumpSpeedSessionBody
    from poolos.thermal_execution_currentness import ThermalResidualPlan
    from poolos.thermal_execution_planning import ThermalPlanDisposition
    from test_thermal_runtime_ownership import NOW as OWNERSHIP_NOW, verified_full_manager

    module = _load_module()
    runtime, *_ = _runtime(module)
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None and lease.originating_currentness is not None
    converged = replace(
        lease.originating_currentness,
        residual_plan=ThermalResidualPlan(ThermalPlanDisposition.ALREADY_CONVERGED, ()),
    )
    manager._state = replace(manager.state, lease=replace(lease, originating_currentness=converged))
    runtime.orchestrator = SimpleNamespace(ownership=manager)
    runtime.pump_speed_session = SimpleNamespace(session=SimpleNamespace(snapshot=SimpleNamespace(
        active=True, body=PumpSpeedSessionBody.POOL, pump_circuit_id="p0102",
    )))

    runtime._record_operator_request(SimpleNamespace(
        operation="pump_circuit_speed", target="p0102",
        request_id="manual-current-pump", requested_value=3200,
    ), OWNERSHIP_NOW)

    current = manager.state.lease
    assert current is not None
    assert current.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.OPERATOR


def test_final_domain_gate_preserves_cancellation_scope_across_independent_window() -> None:
    from poolos.physical_command_authority import PhysicalRequestSource
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppressionSource
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipManager

    module = _load_module()
    runtime, *_ = _runtime(module)
    runtime.orchestrator = SimpleNamespace(ownership=ThermalRuntimeOwnershipManager())
    restraint = runtime.pool_automatic_control
    restraint.observe_opportunity("thermal", eligible=True, observed_at=NOW)
    restraint.observe_opportunity("filtration", eligible=False, observed_at=NOW)
    restraint.suppress(source=PoolAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_off")
    thermal = SimpleNamespace(
        source=PhysicalRequestSource.AUTOMATIC_THERMAL, operation="body_active",
        target="B1101", requested_value=True,
        automatic_thermal_context=SimpleNamespace(body="pool", purpose="normal"),
    )
    filtration = SimpleNamespace(
        source=PhysicalRequestSource.AUTOMATIC_FILTRATION, operation="body_active",
        target="B1101", requested_value=True, automatic_thermal_context=None,
    )
    assert not runtime._domain_command_permitted(thermal)
    assert not runtime._domain_command_permitted(filtration)
    restraint.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(hours=10))
    assert runtime._domain_command_permitted(filtration)
    assert not runtime._domain_command_permitted(thermal)


def test_independent_filtration_keeps_source_neutralization_after_thermal_cancellation() -> None:
    from poolos.filtration_policy import FiltrationDisposition
    from poolos.physical_command_authority import PhysicalRequestSource
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppressionSource
    from poolos.thermal_runtime_assessment import ThermalRequestedMode
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from test_thermal_automatic_execution import _frame

    module = _load_module()
    runtime, *_ = _runtime(module)
    runtime.orchestrator = ThermalRuntimeOrchestrator()
    restraint = runtime.pool_automatic_control
    restraint.observe_opportunity("thermal", eligible=True, observed_at=NOW)
    restraint.observe_opportunity("filtration", eligible=False, observed_at=NOW)
    restraint.suppress(source=PoolAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_off")
    later = NOW + timedelta(hours=10)
    restraint.observe_opportunity("filtration", eligible=True, observed_at=later)
    frame = _frame(runtime.orchestrator, at=later, pool_active=False, pump_rpm=0,
                   pool_heater="H0002", mode=ThermalRequestedMode.OFF,
                   filtration_remaining=timedelta(hours=1),
                   filtration_disposition=FiltrationDisposition.RUN_NOW)
    runtime._latest_frame = frame
    request = SimpleNamespace(
        source=PhysicalRequestSource.AUTOMATIC_THERMAL, operation="body_heat_source",
        target="B1101", requested_value="00000",
        automatic_thermal_context=SimpleNamespace(body="pool", purpose="normal"),
    )
    assert runtime._domain_command_permitted(request)
    request.requested_value = "H0002"
    assert not runtime._domain_command_permitted(request)
