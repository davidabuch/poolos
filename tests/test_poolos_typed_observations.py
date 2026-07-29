"""Milestone 10.5B typed observation framework tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poolos.clock import FixedClock
from poolos.environment import ObservationSourceKind as EnvironmentSourceKind
from poolos.observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationOutOfOrderError,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    ObservationStoreError,
    ObservationTimestampConflictError,
    PoolObservation,
    TruthLevel,
)


def observation(
    observation_id: str,
    *,
    observed_at: datetime,
    source_kind: ObservationSourceKind = ObservationSourceKind.LIVE,
    source_id: str = "home_assistant",
    value: float = 86.0,
) -> PoolObservation:
    return PoolObservation(
        observation_id=observation_id,
        value=value,
        unit="degF",
        truth_level=TruthLevel.MEASURED,
        observed_at=observed_at,
        source_kind=source_kind,
        source_id=source_id,
        quality=ObservationQuality.GOOD,
        confidence=0.98,
    )


def test_environment_reexports_exact_canonical_source_kind() -> None:
    assert EnvironmentSourceKind is ObservationSourceKind


def test_canonical_and_compatibility_constructor_names_match() -> None:
    timestamp = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    current = PoolObservation(
        observation_id="actual.pool.water_temperature",
        value=86.0,
        unit="degF",
        truth_level=TruthLevel.MEASURED,
        observed_at=timestamp,
        source_id="ha:pool_temperature",
    )
    legacy = PoolObservation(
        name="actual.pool.water_temperature",
        value=86.0,
        unit="degF",
        truth_level=TruthLevel.MEASURED,
        observed_at=timestamp,
        source="ha:pool_temperature",
    )

    assert current == legacy
    assert current.name == current.observation_id
    assert current.source == current.source_id


def test_conflicting_compatibility_arguments_are_rejected() -> None:
    with pytest.raises(ValueError, match="must match"):
        PoolObservation(
            observation_id="actual.pool.water_temperature",
            name="simulated.pool.water_temperature",
        )


def test_observed_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PoolObservation(
            observation_id="actual.pool.water_temperature",
            observed_at=datetime(2026, 7, 29, 20, 0),
        )


def test_freshness_is_computed_dynamically_from_runtime_clock() -> None:
    timestamp = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    clock = FixedClock(timestamp + timedelta(seconds=29))
    item = observation("actual.pool.water_temperature", observed_at=timestamp)
    policy = FreshnessPolicy(max_age=timedelta(seconds=30))

    assert item.freshness(clock=clock, policy=policy) is ObservationFreshness.FRESH

    clock.current = timestamp + timedelta(seconds=31)
    assert item.freshness(clock=clock, policy=policy) is ObservationFreshness.STALE


def test_freshness_reports_unknown_and_future_without_mutating_observation() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    policy = FreshnessPolicy(
        max_age=timedelta(minutes=1),
        future_tolerance=timedelta(seconds=2),
    )

    untimed = PoolObservation(observation_id="actual.energy.grid_available")
    future = observation(
        "actual.pool.water_temperature",
        observed_at=now + timedelta(seconds=3),
    )

    assert untimed.freshness(clock=clock, policy=policy) is ObservationFreshness.UNKNOWN
    assert future.freshness(clock=clock, policy=policy) is ObservationFreshness.FUTURE


def test_quality_and_confidence_are_independent() -> None:
    item = PoolObservation(
        observation_id="actual.environment.roof_temperature",
        quality=ObservationQuality.SUSPECT,
        confidence=0.97,
    )

    assert item.quality is ObservationQuality.SUSPECT
    assert item.confidence == 0.97


def test_actual_and_simulated_observations_coexist() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    store = ObservationStore()
    actual = observation("actual.pool.water_temperature", observed_at=now)
    simulated = observation(
        "simulated.pool.water_temperature",
        observed_at=now,
        source_kind=ObservationSourceKind.SIMULATED,
        source_id="simulator",
        value=88.0,
    )

    store.extend((actual, simulated))

    assert store.get("actual.pool.water_temperature") is actual
    assert store.get("simulated.pool.water_temperature") is simulated
    assert len(store) == 2


def test_equal_timestamp_from_same_source_is_rejected() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    store = ObservationStore()
    store.put(observation("actual.pool.water_temperature", observed_at=now))

    with pytest.raises(ObservationTimestampConflictError, match="equal timestamps"):
        store.put(
            observation(
                "actual.pool.water_temperature",
                observed_at=now,
                value=87.0,
            )
        )


def test_equal_timestamp_from_different_sources_is_allowed() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    store = ObservationStore()
    primary = observation(
        "actual.pool.water_temperature",
        observed_at=now,
        source_id="primary_sensor",
    )
    backup = observation(
        "actual.pool.water_temperature",
        observed_at=now,
        source_id="backup_sensor",
        value=85.5,
    )

    store.extend((primary, backup))

    assert store.get_all("actual.pool.water_temperature") == (primary, backup)


def test_older_timestamp_from_same_source_is_rejected() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
    store = ObservationStore()
    store.put(observation("actual.pool.water_temperature", observed_at=now))

    with pytest.raises(ObservationOutOfOrderError, match="older timestamps"):
        store.put(
            observation(
                "actual.pool.water_temperature",
                observed_at=now - timedelta(seconds=1),
            )
        )


def test_store_requires_timestamp_but_model_retains_legacy_compatibility() -> None:
    store = ObservationStore()
    legacy = PoolObservation(name="filter_health", value=0.84)

    with pytest.raises(ObservationStoreError, match="require"):
        store.put(legacy)
