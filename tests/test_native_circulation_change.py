from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.native_circulation_change import (
    NativeCirculationChangeTracker,
    native_circulation_snapshot_is_fresh,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)

NOW = datetime(2026, 9, 30, 6, 0, tzinfo=UTC)


def _obs(concept: str, value: object, at: datetime = NOW) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )


def _native(*, pool: bool, rpm: int, solar: bool = False) -> tuple[PoolObservation, ...]:
    return (
        _obs("pool.active", pool),
        _obs("spa.active", False),
        _obs("pump.rpm", rpm),
        _obs("pool.pump_circuit_configured_speed", rpm),
        _obs("solar.active", solar),
        _obs("heater.active", False),
        _obs("waterfall.active", False),
        _obs("jets.active", False),
        _obs("slide.active", False),
    )


def test_native_circulation_tracker_reproduces_live_manual_pool_start_chronology() -> None:
    tracker = NativeCirculationChangeTracker()

    # Post-restart native baseline: Pool OFF, pump stopped.
    assert not tracker.observe(_native(pool=False, rpm=0))

    # Manual BODY ON arrives first while IntelliCenter has not started the pump yet.
    assert tracker.observe(_native(pool=True, rpm=0))

    # Native pump consequence then arrives at the IntelliCenter configured 2900 RPM.
    assert tracker.observe(_native(pool=True, rpm=2900))

    # Keepalive equality is not another execution wake-up.
    assert not tracker.observe(_native(pool=True, rpm=2900))

    # A heat-source transition is independently execution-relevant.
    assert tracker.observe(_native(pool=True, rpm=2900, solar=True))


def test_native_circulation_snapshot_freshness_uses_existing_120_second_contract() -> None:
    assert native_circulation_snapshot_is_fresh(
        generated_at=NOW,
        evaluated_at=NOW + timedelta(seconds=120),
    )
    assert not native_circulation_snapshot_is_fresh(
        generated_at=NOW,
        evaluated_at=NOW + timedelta(seconds=121),
    )
