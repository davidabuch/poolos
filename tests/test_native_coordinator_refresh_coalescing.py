"""Executable regressions for lossless native snapshot propagation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import random
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from poolos.intellicenter_readonly import (
    NativeBodyKind,
    NativeBodyState,
    NativeIntelliCenterReadAdapter,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationObservation,
)
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def _load_coordinator_module() -> ModuleType:
    """Load the production coordinator with narrow Home Assistant stubs."""

    package_name = "_poolos_native_coordinator_coalescing_test"
    module_name = f"{package_name}.coordinator"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    package = ModuleType(package_name)
    package.__path__ = [str(COMPONENT)]
    sys.modules[package_name] = package

    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    sys.modules["homeassistant"] = homeassistant

    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    sys.modules["homeassistant.config_entries"] = config_entries

    core = ModuleType("homeassistant.core")
    core.Event = type("Event", (), {})
    core.HomeAssistant = type("HomeAssistant", (), {})
    sys.modules["homeassistant.core"] = core

    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules["homeassistant.helpers"] = helpers

    event = ModuleType("homeassistant.helpers.event")
    event.async_track_state_change_event = lambda *args, **kwargs: None
    sys.modules["homeassistant.helpers.event"] = event

    update_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, item: object) -> type[DataUpdateCoordinator]:
            del item
            return cls

        def async_set_updated_data(self, data: object) -> None:
            self.data = data

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    authoritative = ModuleType(f"{package_name}.authoritative")
    authoritative.build_authoritative_snapshot = lambda **kwargs: kwargs
    sys.modules[authoritative.__name__] = authoritative

    const = ModuleType(f"{package_name}.const")
    for name, value in {
        "CONF_INTELLICENTER_HOST": "intellicenter_host",
        "CONF_INTELLICENTER_TRANSPORT": "intellicenter_transport",
        "DEFAULT_INTELLICENTER_TRANSPORT": "tcp",
        "DOMAIN": "poolos",
        "INTEGRATION_VERSION": "test",
        "MULTIDAY_COMMISSIONING_WINDOW_DAYS": 7,
        "OBSERVATION_UPDATE_INTERVAL": None,
        "STARTUP_HEALTH_GRACE": None,
    }.items():
        setattr(const, name, value)
    sys.modules[const.__name__] = const

    observation = ModuleType(f"{package_name}.observation")
    observation.ObservationSnapshot = object
    observation.build_snapshot = lambda **kwargs: kwargs
    observation.configured_entity_ids = lambda configured: ()
    observation.configured_entity_mapping = lambda configured: {}
    sys.modules[observation.__name__] = observation

    independent = ModuleType(f"{package_name}.independent_intellicenter")
    independent.IndependentIntelliCenterReadOnlyTransport = type(
        "IndependentIntelliCenterReadOnlyTransport", (), {}
    )
    independent.IndependentIntelliCenterTransportState = type(
        "IndependentIntelliCenterTransportState",
        (),
        {
            name: name
            for name in (
                "INITIALIZING",
                "CONNECTING",
                "DISCOVERING",
                "RECONNECTING",
            )
        },
    )
    sys.modules[independent.__name__] = independent

    shadow = ModuleType(f"{package_name}.shadow")
    shadow.HomeAssistantShadowRuntime = type("HomeAssistantShadowRuntime", (), {})
    sys.modules[shadow.__name__] = shadow

    spec = importlib.util.spec_from_file_location(
        module_name,
        COMPONENT / "coordinator.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _native_spa_climate(coordinator: object) -> object:
    """Build the real PoolOS climate entity over the coordinator under test."""

    harness_path = ROOT / "tests" / "test_home_assistant_native_climate.py"
    spec = importlib.util.spec_from_file_location(
        "poolos_coalescing_climate_harness",
        harness_path,
    )
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    climate = harness._load_executable_climate_module()
    description = next(
        item for item in climate.CLIMATE_DESCRIPTIONS if item.key == "spa"
    )
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            manual_intellicenter=SimpleNamespace(available=True)
        ),
        entry_id="native_coalescing",
    )
    return climate.PoolOSNativeClimate(coordinator, entry, description)


class _FakeHass:
    def async_create_task(
        self,
        coroutine: Any,
        name: str | None = None,
    ) -> asyncio.Task[None]:
        del name
        return asyncio.create_task(coroutine)


def _transport_snapshot(target: float) -> NativeIntelliCenterTransportSnapshot:
    now = datetime.now(UTC)
    return NativeIntelliCenterTransportSnapshot(
        source_id="poolos.independent_intellicenter",
        observed_at=now,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                native_id="B1202",
                name="Spa",
                kind=NativeBodyKind.SPA,
                active=False,
                heating_active=False,
                current_temperature=100,
                target_temperature=target,
            ),
        ),
    )


def _canonical_target(snapshot: object) -> float | None:
    for observation in snapshot.observations:
        if observation.observation_id == "spa.target_temperature":
            value = observation.value
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _harness() -> Any:
    module = _load_coordinator_module()

    class Harness(module.PoolOSCoordinator):
        def __init__(self) -> None:
            self.hass = _FakeHass()
            self._unloading = False
            self._post_start_active = True
            self._native_intellicenter_refresh_task = None
            self._native_intellicenter_refresh_dirty = False
            self._independent_intellicenter_start_task = None
            self.independent_intellicenter_transport = None
            self._observation_lock = asyncio.Lock()
            self._event_refresh_count = 0
            self.transport_snapshot = _transport_snapshot(97)
            self.native_intellicenter_snapshot = None
            self.native_intellicenter_adapter = NativeIntelliCenterReadAdapter()
            self.listener_targets: list[float | None] = []
            self.pass_started = [asyncio.Event() for _ in range(5)]
            self.pass_release = [asyncio.Event() for _ in range(5)]
            self.published_targets: list[float | None] = []
            self.observe_calls = 0
            self.active_observations = 0
            self.max_active_observations = 0
            self.cancelled_observations = 0

        async def _async_observe(self, *, observed_at: datetime, trigger: str) -> object:
            del trigger
            index = self.observe_calls
            self.observe_calls += 1
            self.active_observations += 1
            self.max_active_observations = max(
                self.max_active_observations,
                self.active_observations,
            )
            canonical = NativeIntelliCenterReadAdapter().map_snapshot(
                self.transport_snapshot,
                generated_at=observed_at,
            )
            self.native_intellicenter_snapshot = canonical
            self.pass_started[index].set()
            try:
                await self.pass_release[index].wait()
            except asyncio.CancelledError:
                self.cancelled_observations += 1
                raise
            finally:
                self.active_observations -= 1
            return canonical

        def async_set_updated_data(self, snapshot: object) -> None:
            self.published_targets.append(_canonical_target(snapshot))

        def async_update_listeners(self) -> None:
            self.listener_targets.append(
                _canonical_target(self.native_intellicenter_snapshot)
            )

    return Harness()


class _ControlledCoordinatorDateTime(datetime):
    current = datetime(2026, 8, 29, 22, 50, tzinfo=UTC)

    @classmethod
    def now(cls, tz: object = None) -> datetime:
        value = cls.current
        return value if tz is not None else value.replace(tzinfo=None)


def _filtration_observation(
    at: datetime,
    *,
    pool_active: bool,
    spa_active: bool,
    rpm: int,
    circulation_usable: bool = True,
) -> FiltrationObservation:
    return FiltrationObservation(
        observed_at=at,
        pool_active=pool_active,
        spa_active=spa_active,
        pump_rpm=rpm,
        water_temperature_f=86.0,
        circulation_evidence_usable=circulation_usable,
        temperature_evidence_usable=True,
    )


def _filtration_ordering_harness() -> tuple[ModuleType, Any]:
    module = _load_coordinator_module()

    class Harness(module.PoolOSCoordinator):
        def __init__(self) -> None:
            self._unloading = False
            self._observation_lock = asyncio.Lock()
            self._native_intellicenter_refresh_dirty = False
            self._native_intellicenter_refresh_task = None
            self._event_refresh_count = 0
            self._reconciliation_refresh_count = 0
            self.data = None
            self.calls: list[tuple[str, datetime]] = []
            self.publications: list[datetime] = []
            self.pool_active = False
            self.spa_active = True
            self.rpm = 3015
            self.circulation_usable = True
            self.tracker = FiltrationAccountingTracker(
                tou_profile=LADWP_INITIAL_PROFILE
            )

        def restore_through(self, high_water: datetime) -> None:
            self.tracker.restore(
                (
                    _filtration_observation(
                        high_water - timedelta(minutes=2),
                        pool_active=self.pool_active,
                        spa_active=self.spa_active,
                        rpm=self.rpm,
                    ),
                    _filtration_observation(
                        high_water,
                        pool_active=self.pool_active,
                        spa_active=self.spa_active,
                        rpm=self.rpm,
                    ),
                )
            )

        async def _async_observe(
            self,
            *,
            observed_at: datetime,
            trigger: str,
        ) -> object:
            self.calls.append((trigger, observed_at))
            self.tracker.observe(
                _filtration_observation(
                    observed_at,
                    pool_active=self.pool_active,
                    spa_active=self.spa_active,
                    rpm=self.rpm,
                    circulation_usable=self.circulation_usable,
                ),
                higher_priority_requirement=self.spa_active,
            )
            return SimpleNamespace(generated_at=observed_at)

        def async_set_updated_data(self, snapshot: object) -> None:
            self.data = snapshot
            self.publications.append(snapshot.generated_at)

    return module, Harness()


def _attach_transport(harness: Any, target: float) -> SimpleNamespace:
    harness.transport_snapshot = _transport_snapshot(target)
    transport = SimpleNamespace(latest_snapshot=harness.transport_snapshot)
    harness.independent_intellicenter_transport = transport
    return transport


def _set_last_known_native_target(harness: Any, target: float) -> None:
    snapshot = _transport_snapshot(target)
    harness.native_intellicenter_snapshot = (
        NativeIntelliCenterReadAdapter().map_snapshot(
            snapshot,
            generated_at=snapshot.observed_at,
        )
    )


async def _finish_worker(harness: Any) -> None:
    task = harness._native_intellicenter_refresh_task
    assert task is not None
    await task
    assert harness._native_intellicenter_refresh_task is None
    assert harness.max_active_observations == 1


def test_fast_native_publication_precedes_blocked_durable_observation() -> None:
    async def exercise() -> None:
        harness = _harness()
        _set_last_known_native_target(harness, 97)
        _attach_transport(harness, 98)
        climate = _native_spa_climate(harness)

        harness._async_schedule_native_intellicenter_refresh()

        assert climate.target_temperature == 98
        assert harness.listener_targets == [98]
        assert harness.observe_calls == 0

        await harness.pass_started[0].wait()
        assert harness.published_targets == []
        assert climate.target_temperature == 98
        harness.pass_release[0].set()
        await _finish_worker(harness)

        assert harness.published_targets == [98]

    asyncio.run(exercise())


def test_fast_publication_does_not_parallelize_durable_observations() -> None:
    async def exercise() -> None:
        harness = _harness()
        transport = _attach_transport(harness, 97)
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        for target in (98, 99, 100):
            harness.transport_snapshot = _transport_snapshot(target)
            transport.latest_snapshot = harness.transport_snapshot
            harness._async_schedule_native_intellicenter_refresh()

        assert harness.active_observations == 1
        assert harness.max_active_observations == 1
        harness.pass_release[0].set()
        await harness.pass_started[1].wait()
        assert harness.active_observations == 1
        assert harness.max_active_observations == 1
        harness.pass_release[1].set()
        await _finish_worker(harness)

    asyncio.run(exercise())


def test_rapid_callbacks_publish_every_latest_native_target_immediately() -> None:
    async def exercise() -> None:
        harness = _harness()
        _set_last_known_native_target(harness, 97)
        transport = _attach_transport(harness, 97)
        climate = _native_spa_climate(harness)
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        for target in (98, 99, 100):
            harness.transport_snapshot = _transport_snapshot(target)
            transport.latest_snapshot = harness.transport_snapshot
            harness._async_schedule_native_intellicenter_refresh()
            assert climate.target_temperature == target

        assert harness.listener_targets == [97, 98, 99, 100]
        assert harness.published_targets == []
        harness.pass_release[0].set()
        await harness.pass_started[1].wait()
        harness.pass_release[1].set()
        await _finish_worker(harness)

        assert harness.published_targets == [97, 100]

    asyncio.run(exercise())


def test_fast_mapping_failure_preserves_last_good_and_durable_recovery() -> None:
    async def exercise() -> None:
        harness = _harness()
        _set_last_known_native_target(harness, 97)
        climate = _native_spa_climate(harness)

        harness.independent_intellicenter_transport = SimpleNamespace(
            latest_snapshot=None
        )
        harness._publish_latest_native_intellicenter_snapshot()
        assert climate.target_temperature == 97
        assert harness.listener_targets == []

        class RejectingAdapter:
            def map_snapshot(self, snapshot: object, *, generated_at: datetime) -> object:
                del snapshot, generated_at
                raise ValueError("invalid transport snapshot")

        _attach_transport(harness, 98)
        harness.native_intellicenter_adapter = RejectingAdapter()
        harness._async_schedule_native_intellicenter_refresh()

        assert climate.target_temperature == 97
        assert harness.listener_targets == []
        await harness.pass_started[0].wait()
        harness.pass_release[0].set()
        await _finish_worker(harness)

        assert harness.published_targets == [98]
        assert harness._event_refresh_count == 1

    asyncio.run(exercise())


def test_callback_after_unload_has_no_fast_publication_or_orphan_task() -> None:
    async def exercise() -> None:
        harness = _harness()
        _set_last_known_native_target(harness, 97)
        _attach_transport(harness, 98)
        harness._unloading = True

        harness._async_schedule_native_intellicenter_refresh()

        assert _canonical_target(harness.native_intellicenter_snapshot) == 97
        assert harness.listener_targets == []
        assert harness._native_intellicenter_refresh_task is None
        assert harness._native_intellicenter_refresh_dirty is False

    asyncio.run(exercise())


def test_live_equivalent_fast_target_does_not_wait_for_durable_event() -> None:
    async def exercise() -> None:
        harness = _harness()
        _set_last_known_native_target(harness, 97)
        _attach_transport(harness, 98)
        climate = _native_spa_climate(harness)

        harness._async_schedule_native_intellicenter_refresh()
        assert climate.target_temperature == 98
        assert harness.listener_targets == [98]
        assert harness.published_targets == []

        await harness.pass_started[0].wait()
        assert harness.published_targets == []
        harness.pass_release[0].set()
        await _finish_worker(harness)

        assert harness.published_targets == [98]

    asyncio.run(exercise())


def test_callback_during_in_flight_propagation_reruns_latest_snapshot() -> None:
    async def exercise() -> None:
        harness = _harness()
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        harness.transport_snapshot = _transport_snapshot(95)
        harness._async_schedule_native_intellicenter_refresh()
        harness.pass_release[0].set()

        await harness.pass_started[1].wait()
        harness.pass_release[1].set()
        await _finish_worker(harness)

        assert harness.published_targets == [97, 95]
        assert harness._event_refresh_count == 2

    asyncio.run(exercise())


def test_rapid_callbacks_coalesce_to_one_latest_snapshot_rerun() -> None:
    async def exercise() -> None:
        harness = _harness()
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        for target in (96, 94, 95):
            harness.transport_snapshot = _transport_snapshot(target)
            harness._async_schedule_native_intellicenter_refresh()

        harness.pass_release[0].set()
        await harness.pass_started[1].wait()
        harness.pass_release[1].set()
        await _finish_worker(harness)

        assert harness.published_targets == [97, 95]
        assert harness.observe_calls == 2

    asyncio.run(exercise())


def test_callback_during_rerun_cannot_be_stranded() -> None:
    async def exercise() -> None:
        harness = _harness()
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        harness.transport_snapshot = _transport_snapshot(96)
        harness._async_schedule_native_intellicenter_refresh()
        harness.pass_release[0].set()
        await harness.pass_started[1].wait()

        harness.transport_snapshot = _transport_snapshot(95)
        harness._async_schedule_native_intellicenter_refresh()
        harness.pass_release[1].set()
        await harness.pass_started[2].wait()
        harness.pass_release[2].set()
        await _finish_worker(harness)

        assert harness.published_targets == [97, 96, 95]
        assert harness.observe_calls == 3

    asyncio.run(exercise())


def test_single_callback_does_not_cause_unnecessary_rerun() -> None:
    async def exercise() -> None:
        harness = _harness()
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()
        harness.pass_release[0].set()
        await _finish_worker(harness)

        assert harness.published_targets == [97]
        assert harness.observe_calls == 1
        assert harness._native_intellicenter_refresh_dirty is False

    asyncio.run(exercise())


def test_unload_cancels_worker_and_clears_pending_refresh() -> None:
    async def exercise() -> None:
        harness = _harness()
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()
        harness._async_schedule_native_intellicenter_refresh()

        harness._unloading = True
        await harness.async_stop_independent_intellicenter()

        assert harness.cancelled_observations == 1
        assert harness._native_intellicenter_refresh_task is None
        assert harness._native_intellicenter_refresh_dirty is False
        assert harness.published_targets == []

        harness._async_schedule_native_intellicenter_refresh()
        await asyncio.sleep(0)
        assert harness._native_intellicenter_refresh_task is None

    asyncio.run(exercise())


def test_live_equivalent_target_transition_needs_no_periodic_reconciliation() -> None:
    async def exercise() -> None:
        harness = _harness()
        climate = _native_spa_climate(harness)
        harness._async_schedule_native_intellicenter_refresh()
        await harness.pass_started[0].wait()

        # This is the live failure shape: the first pass has captured 97 while
        # the independent transport publishes prompt canonical LOTMP=95.
        harness.transport_snapshot = _transport_snapshot(95)
        harness._async_schedule_native_intellicenter_refresh()
        harness.pass_release[0].set()
        await harness.pass_started[1].wait()
        harness.pass_release[1].set()
        await _finish_worker(harness)

        assert _canonical_target(harness.native_intellicenter_snapshot) == 95
        assert harness.published_targets[-1] == 95
        assert climate.target_temperature == 95
        assert harness._event_refresh_count == 2
        assert not hasattr(harness, "_reconciliation_refresh_count")

    asyncio.run(exercise())


def test_native_then_delayed_mapped_events_do_not_regress_filtration_time() -> None:
    """Normal coordinator caller ordering must not feed historical trigger time."""

    async def exercise() -> None:
        module, harness = _filtration_ordering_harness()
        restored_at = _ControlledCoordinatorDateTime.current - timedelta(minutes=2)
        harness.restore_through(restored_at)
        harness.tracker.observe(
            _filtration_observation(
                restored_at,
                pool_active=False,
                spa_active=True,
                rpm=3015,
            )
        )
        harness.tracker.observe(
            _filtration_observation(
                restored_at + timedelta(seconds=1),
                pool_active=False,
                spa_active=True,
                rpm=3015,
            )
        )
        real_datetime = module.datetime
        module.datetime = _ControlledCoordinatorDateTime
        delayed_event_times = (
            datetime(2026, 8, 29, 22, 49, 56, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 1, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 12, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 23, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 34, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 45, tzinfo=UTC),
            datetime(2026, 8, 29, 22, 50, 56, tzinfo=UTC),
        )
        try:
            for delayed_event_at in delayed_event_times:
                _ControlledCoordinatorDateTime.current = (
                    delayed_event_at + timedelta(seconds=10)
                )
                harness._native_intellicenter_refresh_dirty = True
                await harness._async_native_intellicenter_snapshot_updated()
                await harness._async_mapped_state_changed(
                    SimpleNamespace(time_fired=delayed_event_at)
                )
        finally:
            module.datetime = real_datetime

        assert [trigger for trigger, _ in harness.calls] == [
            item
            for _ in delayed_event_times
            for item in ("native_intellicenter_update", "state_change_event")
        ]
        assert harness.tracker.current is not None
        assert harness.tracker.current.temporal_regressions_ignored == 0

    asyncio.run(exercise())


def test_periodic_native_and_mapped_refreshes_share_monotonic_sampling_time() -> None:
    async def exercise() -> None:
        module, harness = _filtration_ordering_harness()
        harness.pool_active = True
        harness.spa_active = False
        harness.rpm = 2600
        start = datetime(2026, 8, 29, 23, 0, tzinfo=UTC)
        real_datetime = module.datetime
        module.datetime = _ControlledCoordinatorDateTime
        try:
            _ControlledCoordinatorDateTime.current = start
            await harness._async_update_data()

            _ControlledCoordinatorDateTime.current = start + timedelta(minutes=2)
            harness._native_intellicenter_refresh_dirty = True
            await harness._async_native_intellicenter_snapshot_updated()

            _ControlledCoordinatorDateTime.current = start + timedelta(
                minutes=2, seconds=1
            )
            await harness._async_mapped_state_changed(
                SimpleNamespace(time_fired=start + timedelta(minutes=1))
            )

            calls_before_stale_publication = len(harness.calls)
            harness.async_set_updated_data(
                SimpleNamespace(generated_at=start + timedelta(minutes=1))
            )
            assert len(harness.calls) == calls_before_stale_publication

            _ControlledCoordinatorDateTime.current = start + timedelta(minutes=3)
            await harness._async_update_data()
        finally:
            module.datetime = real_datetime

        assert [trigger for trigger, _ in harness.calls] == [
            "periodic_reconciliation",
            "native_intellicenter_update",
            "state_change_event",
            "periodic_reconciliation",
        ]
        assert [at for _, at in harness.calls] == sorted(
            at for _, at in harness.calls
        )
        assert harness.tracker.current is not None
        assert harness.tracker.current.credited_runtime == timedelta(minutes=3)
        assert harness.tracker.current.temporal_regressions_ignored == 0

    asyncio.run(exercise())


def test_restore_mixed_refresh_handoff_suppresses_only_stale_publication() -> None:
    async def exercise() -> None:
        module, harness = _filtration_ordering_harness()
        harness.pool_active = True
        harness.spa_active = False
        harness.rpm = 2600
        high_water = datetime(2026, 8, 29, 23, 30, tzinfo=UTC)
        harness.restore_through(high_water)
        restored_credit = harness.tracker.current.credited_runtime
        real_datetime = module.datetime
        module.datetime = _ControlledCoordinatorDateTime
        try:
            _ControlledCoordinatorDateTime.current = high_water - timedelta(seconds=5)
            await harness._async_mapped_state_changed(
                SimpleNamespace(time_fired=high_water - timedelta(seconds=15))
            )

            _ControlledCoordinatorDateTime.current = high_water + timedelta(seconds=25)
            harness._native_intellicenter_refresh_dirty = True
            await harness._async_native_intellicenter_snapshot_updated()

            calls_before_stale_publication = len(harness.calls)
            harness.async_set_updated_data(
                SimpleNamespace(generated_at=high_water - timedelta(seconds=10))
            )
            assert len(harness.calls) == calls_before_stale_publication

            _ControlledCoordinatorDateTime.current = high_water + timedelta(seconds=55)
            await harness._async_update_data()
        finally:
            module.datetime = real_datetime

        assert restored_credit is not None
        assert harness.tracker.current is not None
        assert harness.tracker.current.credited_runtime == (
            restored_credit + timedelta(seconds=55)
        )
        assert harness.tracker.current.temporal_regressions_ignored == 0

        regression = harness.tracker.observe(
            _filtration_observation(
                high_water + timedelta(seconds=40),
                pool_active=True,
                spa_active=False,
                rpm=2600,
            )
        )
        assert regression is not None
        assert regression.temporal_regressions_ignored == 1

    asyncio.run(exercise())


def test_seeded_internal_refresh_interleavings_preserve_ledger_monotonicity() -> None:
    async def exercise() -> None:
        module, harness = _filtration_ordering_harness()
        harness.pool_active = True
        harness.spa_active = False
        harness.rpm = 2600
        start = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
        harness.tracker.observe(
            _filtration_observation(
                start - timedelta(minutes=2),
                pool_active=True,
                spa_active=False,
                rpm=2600,
            )
        )
        generator = random.Random(105)
        credited: list[timedelta] = []
        real_datetime = module.datetime
        module.datetime = _ControlledCoordinatorDateTime
        try:
            for index in range(200):
                current = start + timedelta(seconds=index // 2)
                _ControlledCoordinatorDateTime.current = current
                choice = generator.randrange(3)
                if choice == 0:
                    await harness._async_update_data()
                elif choice == 1:
                    harness._native_intellicenter_refresh_dirty = True
                    await harness._async_native_intellicenter_snapshot_updated()
                else:
                    await harness._async_mapped_state_changed(
                        SimpleNamespace(
                            time_fired=current
                            - timedelta(seconds=generator.randrange(1, 31))
                        )
                    )
                if index % 7 == 0:
                    harness.async_set_updated_data(
                        SimpleNamespace(
                            generated_at=current - timedelta(seconds=30)
                        )
                    )
                assert harness.tracker.current is not None
                credited.append(harness.tracker.current.credited_runtime)
        finally:
            module.datetime = real_datetime

        assert credited == sorted(credited)
        assert credited[-1] == timedelta(minutes=2, seconds=99)
        assert harness.tracker.current is not None
        assert harness.tracker.current.remaining_runtime >= timedelta(0)
        assert harness.tracker.current.temporal_regressions_ignored == 0

    asyncio.run(exercise())
