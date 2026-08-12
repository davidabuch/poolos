"""Deterministic native-versus-HA parity tests for milestone 12.0A."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.observation_parity import (
    ObservationParityEngine,
    ObservationParityStatus,
    PARITY_TOLERANCES,
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
    assert PARITY_TOLERANCES["pool.temperature"] == 0.5
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
