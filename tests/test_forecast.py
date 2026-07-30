from datetime import datetime, timedelta, timezone

import pytest

from poolos.forecast import (
    ForecastConfidence,
    ForecastFreshness,
    ForecastFreshnessPolicy,
    ForecastSnapshot,
)

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


def snapshot(**changes):
    values = {
        "provider": "test-provider",
        "issued_at": NOW,
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=12),
        "ambient_temperature_f": 75.0,
        "provider_confidence": 0.9,
    }
    values.update(changes)
    return ForecastSnapshot(**values)


def test_confidence_is_normalized_at_stable_thresholds():
    assert snapshot(provider_confidence=0.8).confidence is ForecastConfidence.HIGH
    assert snapshot(provider_confidence=0.5).confidence is ForecastConfidence.MEDIUM
    assert snapshot(provider_confidence=0.49).confidence is ForecastConfidence.LOW
    assert snapshot(provider_confidence=None).confidence is ForecastConfidence.UNKNOWN


def test_freshness_policy_classifies_boundary_ages():
    policy = ForecastFreshnessPolicy()
    assert snapshot().freshness(NOW + timedelta(hours=1), policy) is ForecastFreshness.FRESH
    assert snapshot().freshness(NOW + timedelta(hours=3), policy) is ForecastFreshness.AGING
    assert snapshot().freshness(NOW + timedelta(hours=6), policy) is ForecastFreshness.STALE
    assert snapshot().freshness(NOW + timedelta(hours=6, seconds=1), policy) is ForecastFreshness.EXPIRED


def test_snapshot_coverage_is_inclusive():
    value = snapshot()
    assert value.covers(NOW)
    assert value.covers(NOW + timedelta(hours=12))
    assert not value.covers(NOW + timedelta(hours=13))


def test_metadata_is_copied_immutable_and_serialized_stably():
    metadata = {"zone": "backyard", "provider_id": "abc"}
    value = snapshot(metadata=metadata)
    metadata["zone"] = "changed"
    assert value.metadata["zone"] == "backyard"
    assert list(value.to_dict()["metadata"]) == ["provider_id", "zone"]
    with pytest.raises(TypeError):
        value.metadata["zone"] = "other"


def test_snapshot_rejects_invalid_values():
    with pytest.raises(ValueError, match="provider"):
        snapshot(provider=" ")
    with pytest.raises(ValueError, match="cloud_cover"):
        snapshot(cloud_cover_percent=101)
    with pytest.raises(ValueError, match="solar_production"):
        snapshot(solar_production_kw=-1)
    with pytest.raises(ValueError, match="provider_confidence"):
        snapshot(provider_confidence=1.1)


def test_snapshot_and_policy_require_valid_times():
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot(issued_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="valid_until"):
        snapshot(valid_until=NOW)
    with pytest.raises(ValueError, match="future"):
        snapshot().freshness(NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="aging_for"):
        ForecastFreshnessPolicy(timedelta(hours=2), timedelta(hours=1))
