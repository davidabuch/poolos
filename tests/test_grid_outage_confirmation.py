from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from poolos.expected_outage import ExpectedOutageAcknowledgment
from poolos.grid_outage_confirmation import (
    GRID_OUTAGE_CONFIRMATION_DURATION,
    GridAvailability,
    GridOutageConfirmationTracker,
    GridOutageDisposition,
    GridOutageEvidenceStatus,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
SOURCE_ID = "home_assistant:binary_sensor.1_powerwall_grid_status"


def _grid_observation(
    outage_active: object,
    *,
    observed_at: datetime,
    quality: ObservationQuality = ObservationQuality.GOOD,
    source_id: str = SOURCE_ID,
    confidence: float = 1.0,
) -> PoolObservation:
    return PoolObservation(
        observation_id="grid.outage_active",
        value=outage_active,
        observed_at=observed_at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=source_id,
        quality=quality,
        confidence=confidence,
    )


def _evaluate(
    tracker: GridOutageConfirmationTracker,
    *,
    outage_active: object | None,
    evaluated_at: datetime,
    observed_at: datetime | None = None,
    quality: ObservationQuality = ObservationQuality.GOOD,
    source_id: str = SOURCE_ID,
    confidence: float = 1.0,
):
    observation = (
        None
        if outage_active is None
        else _grid_observation(
            outage_active,
            observed_at=observed_at or evaluated_at,
            quality=quality,
            source_id=source_id,
            confidence=confidence,
        )
    )
    return tracker.evaluate(observation, evaluated_at=evaluated_at)


def test_confirmation_duration_is_exactly_two_seconds() -> None:
    assert GRID_OUTAGE_CONFIRMATION_DURATION == timedelta(seconds=2)


def test_initial_on_grid_is_authoritative_on_grid() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=False,
        evaluated_at=NOW,
    )

    assert result.raw_availability is GridAvailability.ON_GRID
    assert result.disposition is GridOutageDisposition.ON_GRID
    assert result.evidence_status is GridOutageEvidenceStatus.USABLE
    assert result.command_delivery_enabled is False


def test_initial_off_grid_starts_pending_epoch() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=True,
        evaluated_at=NOW,
    )

    assert result.raw_availability is GridAvailability.OFF_GRID
    assert result.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert result.pending_since == NOW
    assert result.threshold_reached_at == NOW + timedelta(seconds=2)
    assert result.confirmed_at is None


def test_off_grid_before_threshold_remains_pending() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(milliseconds=1_999),
        observed_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert result.pending_since == NOW
    assert result.confirmed_at is None


def test_off_grid_at_exact_threshold_confirms() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert result.pending_since == NOW
    assert result.threshold_reached_at == NOW + timedelta(seconds=2)
    assert result.confirmed_at == NOW + timedelta(seconds=2)


def test_off_grid_after_threshold_records_late_confirmation_separately() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=30),
        observed_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert result.threshold_reached_at == NOW + timedelta(seconds=2)
    assert result.confirmed_at == NOW + timedelta(seconds=30)


def test_grid_return_before_threshold_cancels_pending_epoch() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=False,
        evaluated_at=NOW + timedelta(seconds=1),
    )

    assert result.disposition is GridOutageDisposition.ON_GRID
    assert result.pending_since is None
    assert result.confirmed_at is None


def test_confirmed_outage_persists_while_usable_off_grid_evidence_continues() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    confirmed = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(minutes=1),
        observed_at=NOW + timedelta(minutes=1),
    )

    assert result.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert result.confirmed_at == confirmed.confirmed_at
    assert result.outage_epoch_started_at == NOW


def test_authoritative_grid_return_ends_confirmed_epoch() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    result = _evaluate(
        tracker,
        outage_active=False,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    assert result.disposition is GridOutageDisposition.ON_GRID
    assert result.outage_epoch_started_at is None
    assert result.grid_returned_at == NOW + timedelta(seconds=3)


def test_second_outage_after_grid_return_requires_a_new_full_confirmation() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )
    _evaluate(
        tracker,
        outage_active=False,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    second = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=4),
    )

    assert second.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert second.pending_since == NOW + timedelta(seconds=4)


@pytest.mark.parametrize(
    ("outage_active", "quality", "expected_status"),
    [
        (None, ObservationQuality.GOOD, GridOutageEvidenceStatus.MISSING),
        ("unknown", ObservationQuality.INVALID, GridOutageEvidenceStatus.UNUSABLE),
        (True, ObservationQuality.DEGRADED, GridOutageEvidenceStatus.UNUSABLE),
        (True, ObservationQuality.SUSPECT, GridOutageEvidenceStatus.UNUSABLE),
        (True, ObservationQuality.INVALID, GridOutageEvidenceStatus.UNUSABLE),
    ],
)
def test_missing_unknown_or_bad_initial_evidence_is_unknown(
    outage_active: object | None,
    quality: ObservationQuality,
    expected_status: GridOutageEvidenceStatus,
) -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=outage_active,
        evaluated_at=NOW,
        quality=quality,
    )

    assert result.raw_availability is GridAvailability.UNKNOWN
    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is expected_status


def test_stale_evidence_is_unknown_and_cannot_start_confirmation() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=True,
        observed_at=NOW,
        evaluated_at=NOW + timedelta(minutes=5, microseconds=1),
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.STALE
    assert result.pending_since is None


def test_future_evidence_is_unknown_and_cannot_start_confirmation() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=True,
        observed_at=NOW + timedelta(microseconds=1),
        evaluated_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.FUTURE
    assert result.pending_since is None


@pytest.mark.parametrize(
    ("outage_active", "quality"),
    [
        (None, ObservationQuality.GOOD),
        ("unknown", ObservationQuality.INVALID),
        (True, ObservationQuality.DEGRADED),
    ],
)
def test_unusable_evidence_breaks_pending_continuity(
    outage_active: object | None,
    quality: ObservationQuality,
) -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    broken = _evaluate(
        tracker,
        outage_active=outage_active,
        evaluated_at=NOW + timedelta(seconds=1),
        quality=quality,
    )
    restarted = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    assert broken.disposition is GridOutageDisposition.UNKNOWN
    assert restarted.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert restarted.pending_since == NOW + timedelta(seconds=3)


def test_unknown_after_confirmation_is_not_misrepresented_as_grid_available() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    unknown = _evaluate(
        tracker,
        outage_active=None,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    assert unknown.disposition is GridOutageDisposition.UNKNOWN
    assert unknown.unresolved_confirmed_outage_since == NOW
    assert unknown.grid_returned_at is None


def test_valid_off_grid_after_unknown_preserves_unended_confirmed_epoch() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    confirmed = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )
    _evaluate(
        tracker,
        outage_active=None,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    resumed = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=4),
    )

    assert resumed.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert resumed.outage_epoch_started_at == NOW
    assert resumed.confirmed_at == confirmed.confirmed_at


def test_only_authoritative_on_grid_evidence_ends_confirmed_epoch() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )
    _evaluate(
        tracker,
        outage_active=None,
        evaluated_at=NOW + timedelta(seconds=3),
    )

    returned = _evaluate(
        tracker,
        outage_active=False,
        evaluated_at=NOW + timedelta(seconds=4),
    )

    assert returned.disposition is GridOutageDisposition.ON_GRID
    assert returned.grid_returned_at == NOW + timedelta(seconds=4)
    assert returned.unresolved_confirmed_outage_since is None


@pytest.mark.parametrize(
    ("outage_active", "quality", "expected_status"),
    [
        (None, ObservationQuality.GOOD, GridOutageEvidenceStatus.MISSING),
        (True, ObservationQuality.DEGRADED, GridOutageEvidenceStatus.UNUSABLE),
    ],
)
def test_missing_or_unusable_after_confirmation_does_not_clear_outage(
    outage_active: object | None,
    quality: ObservationQuality,
    expected_status: GridOutageEvidenceStatus,
) -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    result = _evaluate(
        tracker,
        outage_active=outage_active,
        evaluated_at=NOW + timedelta(seconds=3),
        quality=quality,
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is expected_status
    assert result.unresolved_confirmed_outage_since == NOW


def test_stale_evidence_after_confirmation_does_not_clear_outage() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    result = _evaluate(
        tracker,
        outage_active=True,
        observed_at=NOW,
        evaluated_at=NOW + timedelta(minutes=5, microseconds=1),
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.STALE
    assert result.unresolved_confirmed_outage_since == NOW


def test_restart_during_outage_does_not_backdate_confirmation() -> None:
    tracker = GridOutageConfirmationTracker()
    old_observed_at = NOW - timedelta(minutes=1)

    first = _evaluate(
        tracker,
        outage_active=True,
        observed_at=old_observed_at,
        evaluated_at=NOW,
    )
    confirmed = _evaluate(
        tracker,
        outage_active=True,
        observed_at=old_observed_at,
        evaluated_at=NOW + timedelta(seconds=2),
    )

    assert first.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert first.pending_since == NOW
    assert confirmed.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert confirmed.confirmed_at == NOW + timedelta(seconds=2)


def test_exact_duplicate_evaluation_is_idempotent() -> None:
    tracker = GridOutageConfirmationTracker()
    observation = _grid_observation(True, observed_at=NOW)

    first = tracker.evaluate(observation, evaluated_at=NOW)
    duplicate = tracker.evaluate(observation, evaluated_at=NOW)

    assert duplicate == first


def test_conflicting_duplicate_evaluation_fails_closed() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    with pytest.raises(
        ValueError,
        match="duplicate grid outage evaluation contains conflicting evidence",
    ):
        _evaluate(tracker, outage_active=False, evaluated_at=NOW)


def test_evaluation_timestamp_regression_raises() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=False, evaluated_at=NOW)

    with pytest.raises(
        ValueError,
        match="grid outage evaluations must be chronological",
    ):
        _evaluate(
            tracker,
            outage_active=False,
            evaluated_at=NOW - timedelta(microseconds=1),
        )


def test_raw_observation_timestamp_regression_fails_closed() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW, observed_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW - timedelta(microseconds=1),
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.TEMPORALLY_REGRESSIVE


def test_same_raw_timestamp_and_state_can_prove_continuity_when_still_fresh() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW, observed_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.CONFIRMED_OUTAGE


def test_same_raw_timestamp_with_changed_state_is_contradictory() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW, observed_at=NOW)

    result = _evaluate(
        tracker,
        outage_active=False,
        evaluated_at=NOW + timedelta(seconds=1),
        observed_at=NOW,
    )

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.CONTRADICTORY


def test_source_change_is_unknown_and_breaks_pending_continuity() -> None:
    tracker = GridOutageConfirmationTracker()
    _evaluate(tracker, outage_active=True, evaluated_at=NOW)

    changed = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="home_assistant:binary_sensor.some_other_grid_status",
    )

    assert changed.disposition is GridOutageDisposition.UNKNOWN
    assert changed.evidence_status is GridOutageEvidenceStatus.CONTRADICTORY


def test_wrong_observation_id_is_unusable() -> None:
    tracker = GridOutageConfirmationTracker()
    wrong = PoolObservation(
        observation_id="grid.available",
        value=False,
        observed_at=NOW,
        source_kind=ObservationSourceKind.LIVE,
        source_id=SOURCE_ID,
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )

    result = tracker.evaluate(wrong, evaluated_at=NOW)

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.UNUSABLE


def test_non_live_observation_cannot_confirm_actual_outage() -> None:
    tracker = GridOutageConfirmationTracker()
    simulated = PoolObservation(
        observation_id="grid.outage_active",
        value=True,
        observed_at=NOW,
        source_kind=ObservationSourceKind.SIMULATED,
        source_id=SOURCE_ID,
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )

    result = tracker.evaluate(simulated, evaluated_at=NOW)

    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.UNUSABLE


def test_expected_outage_acknowledgment_cannot_confirm_actual_outage() -> None:
    acknowledgment = ExpectedOutageAcknowledgment.create(
        acknowledged_at=NOW,
        source_id="operator:test",
        reason_code="planned_utility_work",
    )
    tracker = GridOutageConfirmationTracker()

    result = _evaluate(
        tracker,
        outage_active=None,
        evaluated_at=NOW,
    )

    assert acknowledgment.matching_window_start <= NOW <= acknowledgment.matching_window_end
    assert result.disposition is GridOutageDisposition.UNKNOWN


def test_expected_outage_does_not_change_on_grid_actual_truth() -> None:
    acknowledgment = ExpectedOutageAcknowledgment.create(
        acknowledged_at=NOW,
        source_id="operator:test",
    )
    tracker = GridOutageConfirmationTracker()

    result = _evaluate(tracker, outage_active=False, evaluated_at=NOW)

    assert acknowledgment.matching_window_start <= NOW <= acknowledgment.matching_window_end
    assert result.disposition is GridOutageDisposition.ON_GRID


def test_expected_outage_does_not_bypass_actual_confirmation_threshold() -> None:
    acknowledgment = ExpectedOutageAcknowledgment.create(
        acknowledged_at=NOW,
        source_id="operator:test",
    )
    tracker = GridOutageConfirmationTracker()

    pending = _evaluate(tracker, outage_active=True, evaluated_at=NOW)
    confirmed = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
    )

    assert acknowledgment.matching_window_start <= NOW <= acknowledgment.matching_window_end
    assert pending.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert confirmed.disposition is GridOutageDisposition.CONFIRMED_OUTAGE


def test_assessment_contains_bounded_reason_codes_not_commands() -> None:
    tracker = GridOutageConfirmationTracker()
    result = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW,
    )

    assert result.reason_code == "grid_outage_confirmation_pending"
    assert len(result.reason_code) < 128
    assert result.command_delivery_enabled is False
    assert not hasattr(tracker, "deliver")
    assert not hasattr(tracker, "command")

@pytest.mark.parametrize("source_id", ("", " ", "   "))
def test_blank_source_identity_is_rejected_by_observation_model(
    source_id: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="source_id must not be empty when provided",
    ):
        _grid_observation(
            True,
            observed_at=NOW,
            source_id=source_id,
        )


def test_missing_source_identity_is_unusable_for_outage_confirmation() -> None:
    observation = PoolObservation(
        observation_id="grid.outage_active",
        value=True,
        observed_at=NOW,
        source_kind=ObservationSourceKind.LIVE,
        source_id=None,
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )

    result = GridOutageConfirmationTracker().evaluate(
        observation,
        evaluated_at=NOW,
    )

    assert result.raw_availability is GridAvailability.UNKNOWN
    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.UNUSABLE
    assert result.pending_since is None


def test_low_confidence_good_live_evidence_is_unusable() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=True,
        evaluated_at=NOW,
        confidence=0.499999,
    )

    assert result.raw_availability is GridAvailability.UNKNOWN
    assert result.disposition is GridOutageDisposition.UNKNOWN
    assert result.evidence_status is GridOutageEvidenceStatus.UNUSABLE
    assert result.pending_since is None


def test_exact_minimum_confidence_is_usable() -> None:
    result = _evaluate(
        GridOutageConfirmationTracker(),
        outage_active=True,
        evaluated_at=NOW,
        confidence=0.5,
    )

    assert result.raw_availability is GridAvailability.OFF_GRID
    assert result.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert result.evidence_status is GridOutageEvidenceStatus.USABLE
    assert result.pending_since == NOW


def test_low_confidence_cannot_complete_pending_outage_confirmation() -> None:
    tracker = GridOutageConfirmationTracker()

    _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW,
        confidence=1.0,
    )

    low_confidence = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=2),
        observed_at=NOW,
        confidence=0.49,
    )

    assert low_confidence.disposition is GridOutageDisposition.UNKNOWN
    assert low_confidence.evidence_status is GridOutageEvidenceStatus.UNUSABLE

    restarted = _evaluate(
        tracker,
        outage_active=True,
        evaluated_at=NOW + timedelta(seconds=3),
        confidence=1.0,
    )

    assert restarted.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert restarted.pending_since == NOW + timedelta(seconds=3)

