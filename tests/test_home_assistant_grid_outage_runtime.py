"""Behavioral tests for the HA confirmed-outage lifecycle bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.grid_outage_physical_safety import GridOutageSafetyLifecycle
from poolos.physical_command_authority import PhysicalAuthorityReason


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "grid_outage_runtime.py"
PACKAGE_NAME = "poolos_grid_outage_runtime_behavior_test"
NOW = datetime(2026, 9, 6, 18, 0, tzinfo=UTC)


class FakeDelivery:
    release = asyncio.Event()
    started = asyncio.Event()
    calls: list[object] = []
    error: Exception | None = None

    def __init__(self, manual: object, context: object) -> None:
        del manual, context

    async def deliver(self, candidate: object) -> None:
        self.calls.append(candidate)
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error


def load_module() -> ModuleType:
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
        if name == "manual_intellicenter":
            class ManualIntelliCenterCommandNotDispatchedError(RuntimeError):
                pass

            stub.ManualIntelliCenterCommandNotDispatchedError = (
                ManualIntelliCenterCommandNotDispatchedError
            )
        sys.modules[stub.__name__] = stub
    delivery = ModuleType(f"{PACKAGE_NAME}.grid_outage_delivery")
    delivery.ManualIntelliCenterGridOutageDelivery = FakeDelivery
    sys.modules[delivery.__name__] = delivery
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.grid_outage_runtime", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeEngine:
    gate_requested: bool = False
    gate_generation: int = 0
    assessment: object | None = None
    candidate: object | None = None
    accepted: list[object] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    frames: list[str] = field(default_factory=list)
    external_reasons: list[str | None] = field(default_factory=list)

    def set_enabled(self, enabled: bool, **_: object) -> None:
        self.gate_requested = enabled
        self.gate_generation += 1

    def evaluate(self, frame: object) -> object:
        self.frames.append(frame.frame_identity)
        self.external_reasons.append(frame.external_preemption_reason)
        lifecycle = (
            GridOutageSafetyLifecycle.CANDIDATE_READY
            if self.candidate is not None
            else GridOutageSafetyLifecycle.GATE_DISABLED
        )
        self.assessment = SimpleNamespace(
            lifecycle=lifecycle,
            outage_epoch_id="outage" if self.candidate is not None else None,
            candidate=self.candidate,
        )
        return self.assessment

    def record_accepted_delivery(self, candidate: object, **_: object) -> None:
        self.accepted.append(candidate)

    def record_delivery_failure(self, *, reason: str, **_: object) -> None:
        self.failures.append(reason)

    def record_pre_dispatch_rejection(
        self, candidate: object, *, reason: str, **_: object
    ) -> None:
        del candidate
        self.rejections.append(reason)

    def fail_closed(self, *, reason: str, **_: object) -> None:
        self.failures.append(reason)

    def unload(self, **_: object) -> None:
        self.gate_requested = False


@dataclass
class FakeAuthority:
    base_authority_reason: PhysicalAuthorityReason = PhysicalAuthorityReason.ALLOWED
    enabled: list[bool] = field(default_factory=list)
    frames: list[tuple[str | None, str]] = field(default_factory=list)
    unloaded: bool = False

    def configure_grid_outage_safety(self, *, enabled: bool) -> None:
        self.enabled.append(enabled)

    def begin_grid_outage_frame(self, *, outage_epoch_id: str | None, frame_identity: str) -> None:
        self.frames.append((outage_epoch_id, frame_identity))

    def register_grid_outage_candidate(self, **kwargs: object) -> object:
        return SimpleNamespace(**kwargs)

    def bind_grid_outage_dispatch(self, authority: object) -> object:
        return authority

    def unload_grid_outage_safety(self) -> None:
        self.unloaded = True


@dataclass
class FakeHass:
    tasks: list[asyncio.Task[object]] = field(default_factory=list)

    def async_create_task(self, coroutine: object, name: str) -> asyncio.Task[object]:
        assert name == "PoolOS confirmed grid outage physical safety"
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task


def runtime(module: ModuleType, engine: FakeEngine):
    hass = FakeHass()
    authority = FakeAuthority()
    coordinator = SimpleNamespace(async_update_listeners=lambda: None)
    thermal = SimpleNamespace(
        filtration_runtime=SimpleNamespace(assessment=None),
    )
    value = module.PoolOSGridOutageSafetyRuntime(
        hass=hass,
        coordinator=coordinator,
        thermal_runtime=thermal,
        authority=authority,
        manual=SimpleNamespace(available=True),
        engine=engine,
    )
    return value, hass, authority


def snapshot(at: datetime, identity: str) -> tuple[object, object]:
    return (
        SimpleNamespace(generated_at=at, observations=()),
        SimpleNamespace(
            snapshot_identity=identity,
            outage=SimpleNamespace(confirmed_at=NOW),
        ),
    )


def candidate(identity: str = "candidate") -> object:
    return SimpleNamespace(
        candidate_id=identity,
        outage_epoch_id="outage",
        frame_identity="frame-1",
        kind=SimpleNamespace(value="pool_source_off"),
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )


def test_default_off_and_enable_never_process_cached_frame() -> None:
    module = load_module()
    engine = FakeEngine()
    value, hass, authority = runtime(module, engine)
    value.observe(*snapshot(NOW, "frame-0"))
    value.set_enabled(True)
    assert hass.tasks == []
    assert authority.enabled == [True]


def test_synchronous_observation_relies_on_owning_refresh_publication() -> None:
    module = load_module()
    engine = FakeEngine()
    listener_updates = 0

    def update_listeners() -> None:
        nonlocal listener_updates
        listener_updates += 1

    value = module.PoolOSGridOutageSafetyRuntime(
        hass=FakeHass(),
        coordinator=SimpleNamespace(async_update_listeners=update_listeners),
        thermal_runtime=SimpleNamespace(
            filtration_runtime=SimpleNamespace(assessment=None)
        ),
        authority=FakeAuthority(),
        manual=SimpleNamespace(available=True),
        engine=engine,
    )
    value.observe(*snapshot(NOW, "frame-0"))
    assert listener_updates == 0


def test_new_frame_invalidates_queued_context_and_coalesces_one_pending_frame() -> None:
    async def scenario() -> None:
        FakeDelivery.release = asyncio.Event()
        FakeDelivery.started = asyncio.Event()
        FakeDelivery.calls = []
        FakeDelivery.error = None
        module = load_module()
        engine = FakeEngine(candidate=candidate())
        value, hass, authority = runtime(module, engine)
        value.observe(*snapshot(NOW, "frame-1"))
        await FakeDelivery.started.wait()
        value.observe(*snapshot(NOW + timedelta(seconds=1), "frame-2"))
        value.observe(*snapshot(NOW + timedelta(seconds=2), "frame-3"))
        assert len(hass.tasks) == 1
        assert authority.frames[-1] == (None, "frame-3")

        engine.candidate = None
        FakeDelivery.release.set()
        await hass.tasks[0]
        assert engine.accepted
        assert engine.frames == ["frame-1", "frame-3"]

    asyncio.run(scenario())


def test_failure_and_unload_invalidate_authority_without_dispatch() -> None:
    async def scenario() -> None:
        module = load_module()
        engine = FakeEngine()
        value, hass, authority = runtime(module, engine)
        snap, _ = snapshot(NOW, "failed")
        value.orchestration_failed(snap, ValueError("boom"))
        assert engine.failures == ["ValueError"]
        assert hass.tasks == []
        await value.async_unload()
        assert authority.unloaded
        assert not engine.gate_requested

    asyncio.run(scenario())


def test_unload_waits_for_inflight_delivery_without_post_unload_listener_churn() -> None:
    async def scenario() -> None:
        FakeDelivery.release = asyncio.Event()
        FakeDelivery.started = asyncio.Event()
        FakeDelivery.calls = []
        FakeDelivery.error = None
        module = load_module()
        engine = FakeEngine(candidate=candidate())
        hass = FakeHass()
        authority = FakeAuthority()
        listener_updates = 0

        def update_listeners() -> None:
            nonlocal listener_updates
            listener_updates += 1

        value = module.PoolOSGridOutageSafetyRuntime(
            hass=hass,
            coordinator=SimpleNamespace(async_update_listeners=update_listeners),
            thermal_runtime=SimpleNamespace(
                filtration_runtime=SimpleNamespace(assessment=None)
            ),
            authority=authority,
            manual=SimpleNamespace(available=True),
            engine=engine,
        )
        value.observe(*snapshot(NOW, "frame-1"))
        await FakeDelivery.started.wait()
        unload = asyncio.create_task(value.async_unload())
        await asyncio.sleep(0)
        assert not unload.done()

        FakeDelivery.release.set()
        await unload
        await asyncio.sleep(0)
        assert authority.unloaded
        assert listener_updates == 0
        assert value._task is None

    asyncio.run(scenario())


def test_same_frame_external_change_is_part_of_current_authoritative_reality() -> None:
    module = load_module()
    engine = FakeEngine()
    value, _, _ = runtime(module, engine)
    event = ExternalChangeEvent(
        concept="spa.active",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="B1202",
        previous_value=False,
        new_value=True,
        observed_at=NOW,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )

    value.observe(
        *snapshot(NOW, "external-frame"),
        ExternalChangeBatch((event,)),
    )

    assert engine.frames == ["external-frame"]
    assert engine.external_reasons == [None]
    assert engine.assessment is not None


def test_external_change_after_prior_candidate_formation_reaches_outage_engine() -> None:
    module = load_module()
    engine = FakeEngine()
    engine.assessment = SimpleNamespace(
        attempt=SimpleNamespace(
            candidate=SimpleNamespace(
                formed_at=NOW,
            )
        )
    )
    value, _, _ = runtime(module, engine)

    event_at = NOW + timedelta(seconds=1)
    event = ExternalChangeEvent(
        concept="spa.active",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="B1202",
        previous_value=False,
        new_value=True,
        observed_at=event_at,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )

    value.observe(
        *snapshot(NOW + timedelta(seconds=2), "external-after-candidate"),
        ExternalChangeBatch((event,)),
    )

    assert engine.frames == ["external-after-candidate"]
    assert engine.external_reasons == [
        "grid_outage_external_takeover:spa.active"
    ]
    assert engine.assessment is not None


def test_proven_pretransport_rejection_allows_only_pending_fresh_frame() -> None:
    async def scenario() -> None:
        FakeDelivery.release = asyncio.Event()
        FakeDelivery.started = asyncio.Event()
        FakeDelivery.calls = []
        module = load_module()
        rejected_type = sys.modules[
            f"{PACKAGE_NAME}.manual_intellicenter"
        ].ManualIntelliCenterCommandNotDispatchedError
        FakeDelivery.error = rejected_type("physical command denied:grid_outage_context_stale")
        engine = FakeEngine(candidate=candidate())
        value, hass, _ = runtime(module, engine)

        value.observe(*snapshot(NOW, "frame-1"))
        await FakeDelivery.started.wait()
        value.observe(*snapshot(NOW + timedelta(seconds=1), "frame-2"))
        engine.candidate = None
        FakeDelivery.release.set()
        await hass.tasks[0]
        await asyncio.sleep(0)

        assert len(FakeDelivery.calls) == 1
        assert engine.failures == []
        assert engine.rejections == [
            "physical command denied:grid_outage_context_stale"
        ]
        assert engine.frames == ["frame-1", "frame-2"]

    asyncio.run(scenario())


def test_ambiguous_delivery_failure_blocks_without_blind_resend() -> None:
    async def scenario() -> None:
        FakeDelivery.release = asyncio.Event()
        FakeDelivery.release.set()
        FakeDelivery.started = asyncio.Event()
        FakeDelivery.calls = []
        FakeDelivery.error = RuntimeError("ambiguous transport outcome")
        module = load_module()
        engine = FakeEngine(candidate=candidate())
        value, hass, _ = runtime(module, engine)

        value.observe(*snapshot(NOW, "frame-1"))
        await hass.tasks[0]
        await asyncio.sleep(0)

        assert len(FakeDelivery.calls) == 1
        assert engine.rejections == []
        assert engine.failures == ["RuntimeError"]
        assert len(hass.tasks) == 1

    asyncio.run(scenario())
