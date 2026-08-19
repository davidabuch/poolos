"""Deterministic native-versus-HA parity tests for milestone 12.0A."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.observation_parity import (
    ObservationParityEngine,
    ObservationParityStatus,
    PARITY_TOLERANCES,
    TEMPERATURE_TRANSITION_PARITY_CONCEPTS,
    TemperatureParityEligibilityTracker,
)
from poolos.intellicenter_readonly import INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def observation(
    concept: str,
    value: object,
    *,
    source: str,
    observed_at: datetime = NOW,
) -> PoolObservation:
    return PoolObservation(
        observation_id=concept,
        value=value,
        observed_at=observed_at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=source,
        quality=ObservationQuality.GOOD,
    )


def compare(ha, native):
    return ObservationParityEngine().compare(
        ha,
        native,
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
    )


def test_exact_and_tolerance_matches_are_explicit() -> None:
    report = compare(
        (
            observation("pool.active", True, source="home_assistant:pool"),
            observation("pool.temperature", 82.0, source="home_assistant:pool"),
            observation("pump.rpm", 2200, source="home_assistant:rpm"),
        ),
        (
            observation("pool.active", True, source="intellicenter_native:pool"),
            observation("pool.temperature", 82.4, source="intellicenter_native:pool"),
            observation("pump.rpm", 2225.0, source="intellicenter_native:pump"),
        ),
    )
    assert report.match_count == 3
    assert report.mismatch_count == 0
    assert report.parity_ratio == 1.0
    assert PARITY_TOLERANCES["pool.temperature"] == 1.0
    assert PARITY_TOLERANCES["spa.temperature"] == 1.0
    assert PARITY_TOLERANCES["water.temperature"] == 1.0
    assert PARITY_TOLERANCES["air.temperature"] == 0.5
    assert PARITY_TOLERANCES["solar.temperature"] == 0.5
    assert PARITY_TOLERANCES["pump.rpm"] == 25.0


def test_value_and_type_mismatches_are_distinct() -> None:
    report = compare(
        (
            observation("pump.gpm", 40.0, source="ha:gpm"),
            observation("pool.active", True, source="ha:pool"),
        ),
        (
            observation("pump.gpm", 42.0, source="native:gpm"),
            observation("pool.active", "on", source="native:pool"),
        ),
    )
    statuses = {item.concept: item.status for item in report.details}
    assert statuses == {
        "pool.active": ObservationParityStatus.TYPE_MISMATCH,
        "pump.gpm": ObservationParityStatus.VALUE_MISMATCH,
    }
    assert report.mismatch_count == 2


def test_missing_and_stale_sources_are_counted_independently() -> None:
    report = compare(
        (
            observation("pool.active", True, source="ha:pool"),
            observation(
                "spa.active",
                False,
                source="ha:spa",
                observed_at=NOW - timedelta(minutes=6),
            ),
        ),
        (
            observation("spa.active", False, source="native:spa"),
            observation(
                "pump.rpm",
                2200,
                source="native:pump",
                observed_at=NOW - timedelta(minutes=6),
            ),
        ),
    )
    statuses = {item.concept: item.status for item in report.details}
    assert statuses["pool.active"] is ObservationParityStatus.MISSING_NATIVE
    assert statuses["pump.rpm"] is ObservationParityStatus.MISSING_HA
    assert statuses["spa.active"] is ObservationParityStatus.STALE_HA
    assert report.missing_native_count == 1
    assert report.missing_ha_count == 1
    assert report.stale_native_count == 1
    assert report.stale_ha_count == 1


def test_native_staleness_has_explicit_status() -> None:
    report = compare(
        (observation("pool.active", True, source="ha:pool"),),
        (
            observation(
                "pool.active",
                True,
                source="native:pool",
                observed_at=NOW - timedelta(minutes=6),
            ),
        ),
    )
    assert report.details[0].status is ObservationParityStatus.STALE_NATIVE


def test_available_native_source_can_have_zero_parity_without_source_failure() -> None:
    concepts = tuple(f"diagnostic.concept.{index:02d}" for index in range(35))
    report = compare(
        tuple(observation(concept, True, source=f"ha:{concept}") for concept in concepts),
        tuple(
            observation(concept, False, source=f"native:{concept}")
            for concept in reversed(concepts)
        ),
    )

    assert report.native_source_available is True
    assert report.compared_concept_count == 35
    assert report.match_count == 0
    assert report.mismatch_count == 35
    assert report.parity_ratio == 0.0
    assert {
        item.status for item in report.details
    } == {ObservationParityStatus.VALUE_MISMATCH}


def test_input_order_and_replay_are_deterministic() -> None:
    ha = (
        observation("pump.power", 1000.0, source="ha:power"),
        observation("pool.active", True, source="ha:pool"),
    )
    native = (
        observation("pool.active", True, source="native:pool"),
        observation("pump.power", 1020.0, source="native:power"),
    )
    forward = compare(ha, native)
    reverse = compare(tuple(reversed(ha)), tuple(reversed(native)))
    assert forward == reverse
    assert forward.to_dict() == reverse.to_dict()
    assert tuple(item.concept for item in forward.details) == (
        "pool.active",
        "pump.power",
    )


def test_current_ha_sample_is_fresh_without_overwriting_source_timestamp() -> None:
    source_time = NOW - timedelta(hours=2)
    report = ObservationParityEngine().compare(
        (observation("pool.temperature", 99.0, source="ha:pool", observed_at=source_time),),
        (observation("pool.temperature", 99.0, source="native:pool"),),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
        ha_sampled_at_by_concept={"pool.temperature": NOW},
    )

    detail = report.details[0]
    assert detail.status is ObservationParityStatus.MATCH
    assert detail.ha_observed_at == source_time
    assert detail.ha_sampled_at == NOW
    assert detail.to_dict()["ha_observed_at"] == source_time.isoformat()
    assert detail.to_dict()["ha_sampled_at"] == NOW.isoformat()


def test_unsampled_old_ha_and_old_native_evidence_remain_stale() -> None:
    old = NOW - timedelta(minutes=6)
    stale_ha = ObservationParityEngine().compare(
        (observation("pool.active", True, source="ha:pool", observed_at=old),),
        (observation("pool.active", True, source="native:pool"),),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
    )
    stale_native = ObservationParityEngine().compare(
        (observation("pool.active", True, source="ha:pool", observed_at=old),),
        (observation("pool.active", True, source="native:pool", observed_at=old),),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
        ha_sampled_at_by_concept={"pool.active": NOW},
    )

    assert stale_ha.details[0].status is ObservationParityStatus.STALE_HA
    assert stale_native.details[0].status is ObservationParityStatus.STALE_NATIVE


def test_intellicenter_eligibility_excludes_grid_without_hiding_native_gaps() -> None:
    report = ObservationParityEngine().compare(
        (
            observation("grid.available", True, source="ha:grid"),
            observation("grid.outage_active", False, source="ha:grid"),
            observation("pool.active", True, source="ha:pool"),
            observation("pump.rpm", 0, source="ha:pump"),
        ),
        (observation("pool.active", True, source="native:pool"),),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
        ha_sampled_at_by_concept={
            "grid.available": NOW,
            "grid.outage_active": NOW,
            "pool.active": NOW,
            "pump.rpm": NOW,
        },
        eligible_concepts=INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS,
    )

    assert report.compared_concept_count == 2
    assert report.match_count == 1
    assert report.missing_native_count == 1
    assert report.excluded_concepts == ("grid.available", "grid.outage_active")
    assert {item.concept for item in report.details} == {"pool.active", "pump.rpm"}


def test_body_and_water_temperature_one_degree_difference_matches() -> None:
    for concept in (
        "pool.temperature",
        "spa.temperature",
        "water.temperature",
    ):
        report = compare(
            (observation(concept, 86.0, source=f"ha:{concept}"),),
            (observation(concept, 87.0, source=f"native:{concept}"),),
        )

        assert report.match_count == 1
        assert report.mismatch_count == 0
        assert report.details[0].status is ObservationParityStatus.MATCH
        assert report.details[0].tolerance == 1.0


def test_body_and_water_temperature_more_than_one_degree_mismatches() -> None:
    for concept in (
        "pool.temperature",
        "spa.temperature",
        "water.temperature",
    ):
        report = compare(
            (observation(concept, 86.0, source=f"ha:{concept}"),),
            (observation(concept, 87.1, source=f"native:{concept}"),),
        )

        assert report.match_count == 0
        assert report.mismatch_count == 1
        assert (
            report.details[0].status
            is ObservationParityStatus.VALUE_MISMATCH
        )
        assert report.details[0].tolerance == 1.0


def test_two_degree_temperature_difference_mismatches() -> None:
    for concept in (
        "pool.temperature",
        "spa.temperature",
        "water.temperature",
    ):
        report = compare(
            (observation(concept, 86.0, source=f"ha:{concept}"),),
            (observation(concept, 88.0, source=f"native:{concept}"),),
        )

        assert report.match_count == 0
        assert report.mismatch_count == 1
        assert (
            report.details[0].status
            is ObservationParityStatus.VALUE_MISMATCH
        )


def _transition_state(
    *,
    observed_at: datetime,
    pool_active: bool,
    spa_active: bool,
    pump_rpm: int,
) -> tuple[PoolObservation, ...]:
    return (
        observation(
            "pool.active",
            pool_active,
            source="ha:pool",
            observed_at=observed_at,
        ),
        observation(
            "spa.active",
            spa_active,
            source="ha:spa",
            observed_at=observed_at,
        ),
        observation(
            "pump.rpm",
            pump_rpm,
            source="ha:pump",
            observed_at=observed_at,
        ),
    )


def test_temperature_parity_is_excluded_while_circulation_is_off() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "air.temperature",
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    first = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
        ),
        observed_at=NOW,
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(first)
    assert {
        "air.temperature",
        "pool.active",
        "spa.active",
        "pump.rpm",
    }.issubset(first)

    hours_later = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW + timedelta(hours=6),
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
        ),
        observed_at=NOW + timedelta(hours=6),
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(hours_later)


def test_temperature_parity_first_running_snapshot_establishes_baseline() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    result = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=NOW,
    )

    assert result == eligible


def test_circulation_start_creates_45_second_temperature_grace() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "air.temperature",
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pump.gpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
        ),
        observed_at=NOW,
    )

    start_at = NOW + timedelta(seconds=10)

    during_grace = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=start_at,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=start_at,
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        during_grace
    )

    assert {
        "air.temperature",
        "pool.active",
        "spa.active",
        "pump.rpm",
        "pump.gpm",
    }.issubset(during_grace)

    before_expiry = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=start_at + timedelta(seconds=44),
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=start_at + timedelta(seconds=44),
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        before_expiry
    )

    at_expiry = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=start_at + timedelta(seconds=45),
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=start_at + timedelta(seconds=45),
    )

    assert at_expiry == eligible


def test_pool_to_spa_transition_restarts_temperature_grace() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=NOW,
    )

    spa_at = NOW + timedelta(seconds=60)

    during_grace = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=spa_at,
            pool_active=False,
            spa_active=True,
            pump_rpm=3000,
        ),
        observed_at=spa_at,
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        during_grace
    )

    resumed = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=spa_at + timedelta(seconds=45),
            pool_active=False,
            spa_active=True,
            pump_rpm=3000,
        ),
        observed_at=spa_at + timedelta(seconds=45),
    )

    assert resumed == eligible


def test_second_body_transition_restarts_existing_grace() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=NOW,
    )

    spa_at = NOW + timedelta(seconds=60)

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=spa_at,
            pool_active=False,
            spa_active=True,
            pump_rpm=3000,
        ),
        observed_at=spa_at,
    )

    pool_again_at = spa_at + timedelta(seconds=30)

    restarted = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=pool_again_at,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=pool_again_at,
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        restarted
    )

    still_grace = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=pool_again_at + timedelta(seconds=44),
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=pool_again_at + timedelta(seconds=44),
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        still_grace
    )

    resumed = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=pool_again_at + timedelta(seconds=45),
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=pool_again_at + timedelta(seconds=45),
    )

    assert resumed == eligible


def test_rpm_speed_change_while_running_does_not_create_grace() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=NOW,
    )

    changed = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW + timedelta(seconds=10),
            pool_active=True,
            spa_active=False,
            pump_rpm=3000,
        ),
        observed_at=NOW + timedelta(seconds=10),
    )

    assert changed == eligible


def test_circulation_stop_excludes_temperatures_beyond_grace_period() -> None:
    tracker = TemperatureParityEligibilityTracker()

    eligible = frozenset(
        {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.temperature",
            "spa.temperature",
            "water.temperature",
        }
    )

    tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=NOW,
            pool_active=True,
            spa_active=False,
            pump_rpm=2600,
        ),
        observed_at=NOW,
    )

    stop_at = NOW + timedelta(seconds=60)

    stopped = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=stop_at,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
        ),
        observed_at=stop_at,
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(stopped)

    much_later = tracker.eligible_concepts(
        eligible,
        _transition_state(
            observed_at=stop_at + timedelta(hours=2),
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
        ),
        observed_at=stop_at + timedelta(hours=2),
    )

    assert TEMPERATURE_TRANSITION_PARITY_CONCEPTS.isdisjoint(
        much_later
    )


def test_temperature_transition_requires_timezone_aware_time() -> None:
    tracker = TemperatureParityEligibilityTracker()

    try:
        tracker.eligible_concepts(
            frozenset({"water.temperature"}),
            (),
            observed_at=datetime(2026, 8, 19, 12, 0),
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError(
            "naive transition timestamp should have been rejected"
        )
