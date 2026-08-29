from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Mapping
from zoneinfo import ZoneInfo

import pytest

from poolos.filtration_policy import FiltrationDisposition
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


def item(
    concept: str,
    value: object,
    at: datetime,
    *,
    quality: ObservationQuality = ObservationQuality.GOOD,
) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=quality,
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
    outage_active: bool = False,
    healthy: bool = True,
    omitted: tuple[str, ...] = (),
    qualities: Mapping[str, ObservationQuality] | None = None,
    evidence_at: datetime | None = None,
) -> object:
    values = (
        ("pool.active", pool_active),
        ("spa.active", spa_active),
        ("pump.rpm", rpm),
        ("pool.temperature", temperature),
        ("solar.active", solar_active),
        ("heater.active", heater_active),
        ("grid.outage_active", outage_active),
    )
    quality_by_concept = qualities or {}
    observations = tuple(
        item(
            concept,
            value,
            evidence_at or at,
            quality=quality_by_concept.get(concept, ObservationQuality.GOOD),
        )
        for concept, value in values
        if concept not in omitted
    )
    return SimpleNamespace(
        generated_at=at,
        observations=observations,
        stale_entities=stale,
        healthy=healthy,
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


def recorded(
    at: datetime,
    *,
    pool_active: bool,
    spa_active: bool = False,
    rpm: int | None = None,
    global_healthy: bool = True,
    stale: tuple[str, ...] = (),
    omitted: tuple[str, ...] = (),
    qualities: Mapping[str, ObservationQuality] | None = None,
    evidence_at: datetime | None = None,
) -> RecordedObservationEvent:
    observations = snapshot(
        at,
        pool_active=pool_active,
        spa_active=spa_active,
        rpm=(2600 if pool_active else 0) if rpm is None else rpm,
        healthy=global_healthy,
        stale=stale,
        omitted=omitted,
        qualities=qualities,
        evidence_at=evidence_at,
    ).observations
    observations = tuple(
        {
            "observation_id": observation.observation_id,
            "value": observation.value,
            "observed_at": observation.observed_at.isoformat(),
            "quality": observation.quality.value,
            "source_id": observation.source_id,
        }
        for observation in observations
    )
    return RecordedObservationEvent(
        event_id=f"event-{at.isoformat()}",
        recorded_at=at,
        kind="checkpoint",
        changed_observation_ids=(),
        observations=observations,
        health={"healthy": global_healthy, "stale_entities": list(stale)},
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


def test_unrelated_global_health_failure_does_not_break_filtration_credit() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, pool_active=True, healthy=False))
    runtime.refresh(
        snapshot(start + timedelta(hours=1), pool_active=True, healthy=False)
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "crediting"
    assert diagnostics["currently_earning_credit"] is True
    assert diagnostics["required_runtime_seconds"] == 10 * 60 * 60
    assert diagnostics["credited_runtime_seconds"] == 60 * 60
    assert diagnostics["remaining_runtime_seconds"] == 9 * 60 * 60


def test_unusable_pool_temperature_cannot_create_daily_requirement() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    at = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)

    runtime.refresh(
        snapshot(
            at,
            pool_active=True,
            stale=("native:pool.temperature",),
        )
    )

    diagnostics = runtime.diagnostics()
    assert diagnostics["disposition"] == "evidence_unavailable"
    assert diagnostics["reason_code"] == "daily_requirement_temperature_unavailable"
    assert diagnostics["required_runtime_seconds"] == 0


@pytest.mark.parametrize(
    "snapshot_kwargs",
    (
        {"pool_active": True, "stale": ("native:pump.rpm",)},
        {"pool_active": True, "stale": ("native:pool.active",)},
        {"pool_active": True, "stale": ("native:spa.active",)},
        {"pool_active": True, "omitted": ("pump.rpm",)},
        {
            "pool_active": True,
            "qualities": {"pump.rpm": ObservationQuality.DEGRADED},
        },
        {"pool_active": False, "rpm": 2600},
        {"pool_active": True, "spa_active": True, "rpm": 2600},
        {"pool_active": True, "rpm": 0},
    ),
    ids=(
        "stale-pump",
        "stale-pool-activity",
        "stale-spa-activity",
        "missing-pump",
        "bad-pump-quality",
        "pool-inactive",
        "spa-active",
        "zero-rpm",
    ),
)
def test_filtration_critical_uncertainty_or_inactivity_earns_no_credit(
    snapshot_kwargs: dict[str, object],
) -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    runtime.refresh(snapshot(start, **snapshot_kwargs))
    runtime.refresh(snapshot(start + timedelta(hours=1), **snapshot_kwargs))

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(0)
    assert runtime.assessment.currently_earning_credit is False


def test_live_credit_remains_monotonic_through_unrelated_health_failures() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    samples = (
        snapshot(start, pool_active=False, rpm=0),
        snapshot(
            start + timedelta(seconds=30),
            pool_active=True,
            rpm=3000,
            healthy=False,
        ),
        snapshot(start + timedelta(minutes=1), pool_active=True, rpm=2600),
        snapshot(
            start + timedelta(minutes=1, seconds=30),
            pool_active=True,
            rpm=2600,
            healthy=False,
        ),
        snapshot(start + timedelta(minutes=2), pool_active=True, rpm=2600),
        snapshot(
            start + timedelta(minutes=2, seconds=30),
            pool_active=True,
            rpm=2600,
            healthy=False,
        ),
        snapshot(start + timedelta(minutes=3), pool_active=True, rpm=2600),
    )

    credited: list[float] = []
    dispositions: list[str] = []
    for sample in samples:
        runtime.refresh(sample)
        diagnostics = runtime.diagnostics()
        credited.append(float(diagnostics["credited_runtime_seconds"]))
        dispositions.append(str(diagnostics["disposition"]))

    assert credited == [0, 0, 30, 60, 90, 120, 150]
    assert credited == sorted(credited)
    assert dispositions[1:] == ["crediting"] * 6


def test_long_replay_credits_all_provable_intervals_despite_global_health() -> None:
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    events = tuple(
        recorded(
            start + timedelta(hours=offset),
            pool_active=True,
            global_healthy=(offset % 2 == 0),
        )
        for offset in range(9)
    )
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))

    asyncio.run(
        runtime.async_restore(restored_at=start + timedelta(hours=8, minutes=1))
    )

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(hours=8)
    assert runtime.assessment.remaining_runtime == timedelta(hours=2)
    assert runtime.assessment.currently_earning_credit is True


def test_replay_breaks_only_intervals_affected_by_critical_staleness() -> None:
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    events = (
        recorded(start, pool_active=True),
        recorded(start + timedelta(hours=1), pool_active=True),
        recorded(
            start + timedelta(hours=2),
            pool_active=True,
            stale=("native:pump.rpm",),
        ),
        recorded(start + timedelta(hours=3), pool_active=True),
        recorded(start + timedelta(hours=4), pool_active=True),
    )
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))

    asyncio.run(
        runtime.async_restore(restored_at=start + timedelta(hours=4, minutes=1))
    )

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(hours=2)
    assert runtime.assessment.remaining_runtime == timedelta(hours=8)


def test_live_and_replay_use_equivalent_filtration_evidence_qualification() -> None:
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    logical = (
        (start, False, 0, True),
        (start + timedelta(hours=1), True, 3000, True),
        (start + timedelta(hours=2), True, 2600, False),
        (start + timedelta(hours=3), False, 0, False),
    )
    live = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    for at, pool_active, rpm, healthy in logical:
        live.refresh(
            snapshot(at, pool_active=pool_active, rpm=rpm, healthy=healthy)
        )

    events = tuple(
        recorded(
            at,
            pool_active=pool_active,
            rpm=rpm,
            global_healthy=healthy,
        )
        for at, pool_active, rpm, healthy in logical
    )
    replay = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))
    asyncio.run(
        replay.async_restore(restored_at=start + timedelta(hours=3, minutes=1))
    )

    assert live.assessment is not None
    assert replay.assessment is not None
    assert (
        replay.assessment.required_runtime,
        replay.assessment.credited_runtime,
        replay.assessment.remaining_runtime,
        replay.assessment.total_remaining_runtime,
        replay.assessment.disposition,
        replay.assessment.currently_earning_credit,
    ) == (
        live.assessment.required_runtime,
        live.assessment.credited_runtime,
        live.assessment.remaining_runtime,
        live.assessment.total_remaining_runtime,
        live.assessment.disposition,
        live.assessment.currently_earning_credit,
    )


def test_live_and_replay_use_aggregate_sample_time_not_source_observation_time() -> None:
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    evidence_start = start - timedelta(seconds=3)
    evidence_end = start + timedelta(minutes=59, seconds=57)
    live = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    live.refresh(
        snapshot(start, evidence_at=evidence_start, pool_active=True)
    )
    live.refresh(
        snapshot(
            start + timedelta(hours=1),
            evidence_at=evidence_end,
            pool_active=True,
        )
    )

    events = (
        recorded(start, evidence_at=evidence_start, pool_active=True),
        recorded(
            start + timedelta(hours=1),
            evidence_at=evidence_end,
            pool_active=True,
        ),
    )
    replay = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))
    asyncio.run(
        replay.async_restore(restored_at=start + timedelta(hours=1, seconds=1))
    )

    assert live.assessment is not None
    assert replay.assessment is not None
    assert live.assessment.credited_runtime == timedelta(hours=1)
    assert replay.assessment.credited_runtime == timedelta(hours=1)
    assert replay.assessment.evaluated_at == start + timedelta(hours=1)


def test_runtime_restore_live_overlap_matches_continuous_provable_timeline() -> None:
    high_water = datetime(2026, 8, 29, 14, 47, 40, tzinfo=LOCAL)
    events = (
        recorded(high_water - timedelta(hours=1), pool_active=True),
        recorded(high_water, pool_active=True),
    )
    handoff = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))
    asyncio.run(
        handoff.async_restore(restored_at=high_water + timedelta(seconds=1))
    )
    handoff.refresh(
        snapshot(high_water - timedelta(seconds=5), pool_active=True)
    )
    handoff.refresh(
        snapshot(high_water + timedelta(seconds=25), pool_active=True)
    )

    live = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    for at in (
        high_water - timedelta(hours=1),
        high_water,
        high_water + timedelta(seconds=25),
    ):
        live.refresh(snapshot(at, pool_active=True))

    replay_events = (
        *events,
        recorded(high_water + timedelta(seconds=25), pool_active=True),
    )
    replay = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(replay_events)))
    asyncio.run(
        replay.async_restore(restored_at=high_water + timedelta(seconds=26))
    )

    assert handoff.assessment is not None
    assert live.assessment is not None
    assert replay.assessment is not None
    assert handoff.assessment.credited_runtime == timedelta(hours=1, seconds=25)
    assert (
        handoff.assessment.required_runtime,
        handoff.assessment.credited_runtime,
        handoff.assessment.remaining_runtime,
        handoff.assessment.carried_prior_day_debt,
        handoff.assessment.total_remaining_runtime,
        handoff.assessment.obligation_day,
        handoff.assessment.disposition,
        handoff.assessment.temporal_regressions_ignored,
    ) == (
        live.assessment.required_runtime,
        live.assessment.credited_runtime,
        live.assessment.remaining_runtime,
        live.assessment.carried_prior_day_debt,
        live.assessment.total_remaining_runtime,
        live.assessment.obligation_day,
        live.assessment.disposition,
        live.assessment.temporal_regressions_ignored,
    ) == (
        replay.assessment.required_runtime,
        replay.assessment.credited_runtime,
        replay.assessment.remaining_runtime,
        replay.assessment.carried_prior_day_debt,
        replay.assessment.total_remaining_runtime,
        replay.assessment.obligation_day,
        replay.assessment.disposition,
        replay.assessment.temporal_regressions_ignored,
    )


def test_obligation_day_uses_aggregate_time_across_midnight() -> None:
    aggregate_at = datetime(2026, 8, 30, 0, 0, 1, tzinfo=LOCAL)
    evidence_at = aggregate_at - timedelta(seconds=2)
    event = recorded(
        aggregate_at,
        evidence_at=evidence_at,
        pool_active=False,
    )
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder((event,))))

    asyncio.run(
        runtime.async_restore(restored_at=aggregate_at + timedelta(seconds=1))
    )

    assert runtime.assessment is not None
    assert runtime.assessment.obligation_day.isoformat() == "2026-08-30"


def test_long_lifecycle_preserves_credit_through_restart_and_midnight() -> None:
    start = datetime(2026, 8, 29, 22, 0, tzinfo=LOCAL)
    logical = (
        (start, False, False, 0, True, (), False),
        (start + timedelta(minutes=5), True, False, 3000, True, (), False),
        (start + timedelta(minutes=6), True, False, 2600, True, (), False),
        (
            start + timedelta(minutes=60),
            True,
            False,
            2900,
            False,
            ("native:pool_light.active",),
            True,
        ),
        (start + timedelta(minutes=90), True, False, 2600, True, (), False),
        (start + timedelta(minutes=105), False, True, 3015, True, (), False),
        (start + timedelta(minutes=135), False, True, 3015, True, (), False),
        (start + timedelta(minutes=150), True, False, 2600, True, (), False),
        (start + timedelta(minutes=210), True, False, 2600, True, (), False),
        (
            start + timedelta(minutes=225),
            True,
            False,
            2600,
            True,
            ("native:pump.rpm",),
            False,
        ),
        (start + timedelta(minutes=240), True, False, 2600, True, (), False),
        (start + timedelta(minutes=270), True, False, 2600, True, (), False),
    )
    live = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    total_credited: list[timedelta] = []
    spa_disposition = None
    stale_disposition = None
    for at, pool_active, spa_active, rpm, healthy, stale, solar_active in logical:
        live.refresh(
            snapshot(
                at,
                pool_active=pool_active,
                spa_active=spa_active,
                rpm=rpm,
                healthy=healthy,
                stale=stale,
                solar_active=solar_active,
            )
        )
        total_credited.append(
            sum(
                (item.credited_runtime for item in live.tracker.ledger.debts),
                timedelta(0),
            )
        )
        if spa_active:
            spa_disposition = live.assessment.disposition
        if stale == ("native:pump.rpm",):
            stale_disposition = live.assessment.disposition

    assert total_credited == sorted(total_credited)
    assert total_credited[-1] == timedelta(hours=3, minutes=10)
    assert total_credited[3] - total_credited[2] == timedelta(minutes=54)
    assert total_credited[4] - total_credited[3] == timedelta(minutes=30)
    assert total_credited[6] == total_credited[5]
    assert total_credited[9] == total_credited[8]
    assert total_credited[10] == total_credited[9]
    assert spa_disposition is FiltrationDisposition.DEFERRED_HIGHER_PRIORITY
    assert stale_disposition is FiltrationDisposition.RUN_NOW
    assert live.assessment is not None
    assert live.assessment.obligation_day.isoformat() == "2026-08-30"
    assert live.assessment.disposition is FiltrationDisposition.CREDITING
    assert live.assessment.authority == "none"
    assert live.assessment.command_delivery_enabled is False

    events = tuple(
        recorded(
            at,
            pool_active=pool_active,
            spa_active=spa_active,
            rpm=rpm,
            global_healthy=healthy,
            stale=stale,
        )
        for at, pool_active, spa_active, rpm, healthy, stale, _ in logical
    )
    restarted = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder(events)))
    high_water = logical[-1][0]
    asyncio.run(
        restarted.async_restore(restored_at=high_water + timedelta(seconds=1))
    )
    assert restarted.assessment is not None
    assert restarted.assessment.total_remaining_runtime == (
        live.assessment.total_remaining_runtime
    )

    restarted.refresh(
        snapshot(high_water - timedelta(seconds=5), pool_active=True, rpm=2600)
    )
    restarted.refresh(
        snapshot(high_water + timedelta(minutes=30), pool_active=True, rpm=2600)
    )
    after_handoff = restarted.assessment
    assert after_handoff is not None
    assert sum(
        (item.credited_runtime for item in restarted.tracker.ledger.debts),
        timedelta(0),
    ) == timedelta(hours=3, minutes=40)
    restarted.refresh(
        snapshot(high_water + timedelta(minutes=30), pool_active=True, rpm=2600)
    )
    assert restarted.assessment == after_handoff

    restarted.refresh(
        snapshot(high_water + timedelta(minutes=29), pool_active=True, rpm=2600)
    )
    assert restarted.assessment is not None
    assert restarted.assessment.temporal_regressions_ignored == 1


def test_stale_confirmed_outage_evidence_does_not_reduce_credit() -> None:
    runtime = PoolOSFiltrationRuntime(FakeCoordinator(FakeRecorder()))
    start = datetime(2026, 8, 29, 8, 0, tzinfo=LOCAL)
    stale_outage = ("native:grid.outage_active",)
    runtime.refresh(
        snapshot(
            start,
            pool_active=True,
            outage_active=True,
            stale=stale_outage,
        )
    )
    runtime.refresh(
        snapshot(
            start + timedelta(hours=1),
            pool_active=True,
            outage_active=True,
            stale=stale_outage,
        )
    )

    assert runtime.assessment is not None
    assert runtime.assessment.credited_runtime == timedelta(hours=1)


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
