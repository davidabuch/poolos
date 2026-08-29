from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
    RecordedObservationEvent,
)


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ZoneInfo("America/Los_Angeles")


def _load_runtime_class():
    package_name = "_poolos_filtration_runtime_test"
    module_name = f"{package_name}.filtration_runtime"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing.PoolOSFiltrationRuntime
    package = ModuleType(package_name)
    package.__path__ = []
    observation_module = ModuleType(f"{package_name}.observation")
    observation_module.ObservationSnapshot = object
    sys.modules[package_name] = package
    sys.modules[observation_module.__name__] = observation_module
    path = ROOT / "custom_components" / "poolos" / "filtration_runtime.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.PoolOSFiltrationRuntime


PoolOSFiltrationRuntime = _load_runtime_class()


def item(concept: str, value: object, at: datetime) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=ObservationQuality.GOOD,
    )


def snapshot(
    at: datetime,
    *,
    pool_active: bool,
    spa_active: bool = False,
    rpm: int = 2600,
    temperature: float = 88.0,
    stale: tuple[str, ...] = (),
    solar_active: bool = False,
    heater_active: bool = False,
) -> object:
    observations = (
        item("pool.active", pool_active, at),
        item("spa.active", spa_active, at),
        item("pump.rpm", rpm, at),
        item("pool.temperature", temperature, at),
        item("solar.active", solar_active, at),
        item("heater.active", heater_active, at),
        item("grid.outage_active", False, at),
    )
    return SimpleNamespace(
        generated_at=at,
        observations=observations,
        stale_entities=stale,
        healthy=True,
    )


@dataclass
class FakeRecorder:
    events: tuple[RecordedObservationEvent, ...] = ()

    def query(self, *, start: datetime, end: datetime):
        return tuple(
            event for event in self.events if start <= event.recorded_at < end
        )


class UnreadableRecorder(FakeRecorder):
    def query(self, *, start: datetime, end: datetime):
        raise OSError("simulated unreadable observation history")


class FakeHass:
    async def async_add_executor_job(self, function):
        return function()


@dataclass
class FakeCoordinator:
    observation_recorder: FakeRecorder
    hass: FakeHass = FakeHass()
    local_timezone: ZoneInfo = LOCAL


def recorded(at: datetime, *, pool_active: bool) -> RecordedObservationEvent:
    values = {
        "pool.active": pool_active,
        "spa.active": False,
        "pump.rpm": 2600 if pool_active else 0,
        "pool.temperature": 88.0,
        "solar.active": False,
        "heater.active": False,
        "grid.outage_active": False,
    }
    observations = tuple(
        {
            "observation_id": concept,
            "value": value,
            "quality": "good",
            "source_id": f"native:{concept}",
        }
        for concept, value in sorted(values.items())
    )
    return RecordedObservationEvent(
        event_id=f"event-{at.isoformat()}",
        recorded_at=at,
        kind="checkpoint",
        changed_observation_ids=(),
        observations=observations,
        health={"healthy": True, "stale_entities": []},
    )


def test_live_snapshot_exposes_bounded_authoritative_filtration_diagnostics() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True))
    runtime.refresh(
        snapshot(start + timedelta(hours=8, minutes=11), pool_active=False, rpm=0)
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["required_runtime_seconds"] == 10 * 60 * 60
    assert diagnostics["credited_runtime_seconds"] == (8 * 60 + 11) * 60
    assert diagnostics["remaining_runtime_seconds"] == (1 * 60 + 49) * 60
    assert diagnostics["ordinary_filtration_rpm"] == 2600
    assert diagnostics["persistence_source"] == "authoritative_observation_history"
    assert diagnostics["authority"] == "none"
    assert diagnostics["command_delivery_enabled"] is False
    assert len(json.dumps(diagnostics, sort_keys=True).encode()) < 8192


def test_restore_replays_persistent_observation_history_without_gap_credit() -> None:
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    recorder = FakeRecorder(
        (
            recorded(start, pool_active=True),
            recorded(start + timedelta(hours=1), pool_active=True),
        )
    )
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(recorder))

    asyncio.run(runtime.async_restore(restored_at=start + timedelta(hours=2)))
    runtime.refresh(snapshot(start + timedelta(hours=3), pool_active=True))

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(hours=1)
    assert runtime.assessment.restored_from_history


def test_stale_relevant_snapshot_cannot_credit_filtration() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True))
    runtime.refresh(
        snapshot(
            start + timedelta(hours=1),
            pool_active=True,
            stale=("native:pump.rpm",),
        )
    )

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(0)


def test_restore_failure_is_isolated_and_live_accounting_can_recover() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(UnreadableRecorder()))
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)

    asyncio.run(runtime.async_restore(restored_at=start))

    assert runtime.assessment is None
    assert runtime.diagnostics()["reason_code"] == "filtration_history_restore_failed"

    runtime.refresh(snapshot(start + timedelta(minutes=1), pool_active=True))

    assert runtime.assessment is not None
    assert runtime.diagnostics()["persistence_source"] == (
        "authoritative_observation_history"
    )


def test_pool_solar_circulation_is_crediting_not_deferred() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 11, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True, solar_active=True))
    runtime.refresh(
        snapshot(
            start + timedelta(hours=1),
            pool_active=True,
            solar_active=True,
        )
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "crediting"
    assert diagnostics["currently_earning_credit"] is True
    assert diagnostics["credited_runtime_seconds"] == 60 * 60
    assert diagnostics["reason_code"] == (
        "filtration_crediting_during_other_operation"
    )


def test_pool_gas_circulation_is_crediting_not_deferred() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 11, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True, heater_active=True))
    runtime.refresh(
        snapshot(
            start + timedelta(minutes=45),
            pool_active=True,
            heater_active=True,
        )
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "crediting"
    assert diagnostics["currently_earning_credit"] is True
    assert diagnostics["credited_runtime_seconds"] == 45 * 60


def test_spa_mode_genuinely_defers_pool_filtration_credit() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 11, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=False, spa_active=True, rpm=3000))
    runtime.refresh(
        snapshot(
            start + timedelta(hours=1),
            pool_active=False,
            spa_active=True,
            rpm=3000,
        )
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "deferred_higher_priority"
    assert diagnostics["currently_earning_credit"] is False
    assert diagnostics["credited_runtime_seconds"] == 0


def test_high_peak_without_pool_circulation_is_true_tou_deferral() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    high_peak = datetime(2026, 8, 28, 14, 0, tzinfo=LOCAL)

    runtime.refresh(snapshot(high_peak, pool_active=False, rpm=0))

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "deferred_tou"
    assert diagnostics["currently_earning_credit"] is False


def test_completed_obligation_is_satisfied_even_if_pool_remains_active() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 28, 8, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True))
    runtime.refresh(snapshot(start + timedelta(hours=10), pool_active=True))

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "satisfied"
    assert diagnostics["currently_earning_credit"] is False
    assert diagnostics["remaining_runtime_seconds"] == 0


def test_ha_surface_is_one_diagnostic_view_not_a_command_or_second_ledger() -> None:
    sensor_source = (ROOT / "custom_components" / "poolos" / "sensor.py").read_text()
    runtime_source = (
        ROOT / "custom_components" / "poolos" / "filtration_runtime.py"
    ).read_text()

    assert '"filtration_obligation"' in sensor_source
    assert '"Filtration Obligation"' in sensor_source
    for prohibited in (
        "hass.services",
        "ManualIntelliCenterControl",
        "SetPumpSpeed",
        "deliver_current_step",
        "asyncio.sleep",
    ):
        assert prohibited not in runtime_source
