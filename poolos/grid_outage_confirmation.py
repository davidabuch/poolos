"""Canonical command-free confirmation of authoritative grid-outage evidence.

The configured Home Assistant grid-status entity is a stateful external source.
Its raw observation says whether the site is currently off grid; this tracker
adds PoolOS's required continuous two-second confirmation without timers,
persistence, or command authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from .clock import FixedClock
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)

GRID_OUTAGE_OBSERVATION_ID: Final = "grid.outage_active"
GRID_OUTAGE_CONFIRMATION_DURATION: Final = timedelta(seconds=2)
GRID_OUTAGE_MAX_OBSERVATION_AGE: Final = timedelta(minutes=5)
GRID_OUTAGE_MINIMUM_CONFIDENCE: Final = 0.5


class GridAvailability(str, Enum):
    """Normalized raw state of the authoritative external grid source."""

    ON_GRID = "ON_GRID"
    OFF_GRID = "OFF_GRID"
    UNKNOWN = "UNKNOWN"


class GridOutageDisposition(str, Enum):
    """Confirmed PoolOS interpretation of current grid evidence."""

    ON_GRID = "ON_GRID"
    OFF_GRID_PENDING = "OFF_GRID_PENDING"
    CONFIRMED_OUTAGE = "CONFIRMED_OUTAGE"
    UNKNOWN = "UNKNOWN"


class GridOutageEvidenceStatus(str, Enum):
    """Why raw grid evidence is or is not usable for confirmation."""

    USABLE = "USABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    FUTURE = "FUTURE"
    UNUSABLE = "UNUSABLE"
    TEMPORALLY_REGRESSIVE = "TEMPORALLY_REGRESSIVE"
    CONTRADICTORY = "CONTRADICTORY"


class GridOutageReasonCode(str, Enum):
    """Stable bounded reasons for the current canonical disposition."""

    GRID_AVAILABLE_AUTHORITATIVE = "grid_available_authoritative"
    CONFIRMATION_PENDING = "grid_outage_confirmation_pending"
    OUTAGE_CONFIRMED = "grid_outage_confirmed"
    EVIDENCE_MISSING = "grid_outage_evidence_missing"
    EVIDENCE_STALE = "grid_outage_evidence_stale"
    EVIDENCE_FUTURE = "grid_outage_evidence_future"
    EVIDENCE_UNUSABLE = "grid_outage_evidence_unusable"
    EVIDENCE_TEMPORALLY_REGRESSIVE = (
        "grid_outage_evidence_temporally_regressive"
    )
    EVIDENCE_CONTRADICTORY = "grid_outage_evidence_contradictory"


@dataclass(frozen=True, slots=True)
class GridOutageConfirmationPolicy:
    """Bounded temporal policy for the canonical confirmation boundary."""

    confirmation_duration: timedelta = GRID_OUTAGE_CONFIRMATION_DURATION
    freshness_policy: FreshnessPolicy = FreshnessPolicy(
        max_age=GRID_OUTAGE_MAX_OBSERVATION_AGE
    )

    def __post_init__(self) -> None:
        if self.confirmation_duration != GRID_OUTAGE_CONFIRMATION_DURATION:
            raise ValueError("grid outage confirmation duration must be exactly 2 seconds")


@dataclass(frozen=True, slots=True)
class GridOutageAssessment:
    """Immutable command-free result for one grid-evidence evaluation."""

    raw_availability: GridAvailability
    disposition: GridOutageDisposition
    evidence_status: GridOutageEvidenceStatus
    evaluated_at: datetime
    observed_at: datetime | None
    source_id: str | None
    pending_since: datetime | None
    threshold_reached_at: datetime | None
    outage_epoch_started_at: datetime | None
    confirmed_at: datetime | None
    unresolved_confirmed_outage_since: datetime | None
    grid_returned_at: datetime | None
    reason_code: GridOutageReasonCode
    command_delivery_enabled: bool = field(default=False, init=False)


class GridOutageConfirmationTracker:
    """Track one in-memory, chronological grid-outage confirmation epoch."""

    def __init__(
        self,
        *,
        policy: GridOutageConfirmationPolicy = GridOutageConfirmationPolicy(),
    ) -> None:
        self._policy = policy
        self._source_id: str | None = None
        self._last_evaluated_at: datetime | None = None
        self._last_input_fingerprint: tuple[object, ...] | None = None
        self._last_assessment: GridOutageAssessment | None = None
        self._last_raw_observed_at: datetime | None = None
        self._last_raw_availability: GridAvailability | None = None
        self._pending_since: datetime | None = None
        self._outage_epoch_started_at: datetime | None = None
        self._confirmed_at: datetime | None = None
        self._grid_returned_at: datetime | None = None

    def evaluate(
        self,
        observation: PoolObservation | None,
        *,
        evaluated_at: datetime,
    ) -> GridOutageAssessment:
        """Evaluate raw current evidence without producing operational authority."""

        _require_aware(evaluated_at, "evaluated_at")
        fingerprint = _input_fingerprint(observation)
        if self._last_evaluated_at is not None:
            if evaluated_at < self._last_evaluated_at:
                raise ValueError("grid outage evaluations must be chronological")
            if evaluated_at == self._last_evaluated_at:
                if fingerprint != self._last_input_fingerprint:
                    raise ValueError(
                        "duplicate grid outage evaluation contains conflicting evidence"
                    )
                assert self._last_assessment is not None
                return self._last_assessment

        availability, status = self._classify(observation, evaluated_at=evaluated_at)
        if status is GridOutageEvidenceStatus.USABLE:
            availability, status = self._validate_raw_chronology(
                observation,
                availability=availability,
            )

        if status is not GridOutageEvidenceStatus.USABLE:
            if self._confirmed_at is None:
                self._pending_since = None
                self._outage_epoch_started_at = None
            assessment = self._unknown_assessment(
                observation,
                evaluated_at=evaluated_at,
                status=status,
            )
        elif availability is GridAvailability.ON_GRID:
            assessment = self._accept_grid_return(
                observation,
                evaluated_at=evaluated_at,
            )
        else:
            assessment = self._accept_off_grid(
                observation,
                evaluated_at=evaluated_at,
            )

        self._last_evaluated_at = evaluated_at
        self._last_input_fingerprint = fingerprint
        self._last_assessment = assessment
        return assessment

    def _classify(
        self,
        observation: PoolObservation | None,
        *,
        evaluated_at: datetime,
    ) -> tuple[GridAvailability, GridOutageEvidenceStatus]:
        if observation is None:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.MISSING
        if observation.observation_id != GRID_OUTAGE_OBSERVATION_ID:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.UNUSABLE
        if observation.quality is not ObservationQuality.GOOD:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.UNUSABLE
        if observation.source_kind is not ObservationSourceKind.LIVE:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.UNUSABLE
        if (
            observation.source_id is None
            or not observation.source_id.strip()
            or type(observation.value) is not bool
            or observation.confidence < GRID_OUTAGE_MINIMUM_CONFIDENCE
        ):
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.UNUSABLE

        freshness = observation.freshness(
            clock=FixedClock(evaluated_at),
            policy=self._policy.freshness_policy,
        )
        if freshness is ObservationFreshness.UNKNOWN:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.MISSING
        if freshness is ObservationFreshness.STALE:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.STALE
        if freshness is ObservationFreshness.FUTURE:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.FUTURE
        return (
            GridAvailability.OFF_GRID
            if observation.value
            else GridAvailability.ON_GRID,
            GridOutageEvidenceStatus.USABLE,
        )

    def _validate_raw_chronology(
        self,
        observation: PoolObservation | None,
        *,
        availability: GridAvailability,
    ) -> tuple[GridAvailability, GridOutageEvidenceStatus]:
        assert observation is not None
        assert observation.observed_at is not None
        assert observation.source_id is not None
        if self._source_id is None:
            self._source_id = observation.source_id
        elif observation.source_id != self._source_id:
            return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.CONTRADICTORY

        if self._last_raw_observed_at is not None:
            if observation.observed_at < self._last_raw_observed_at:
                return (
                    GridAvailability.UNKNOWN,
                    GridOutageEvidenceStatus.TEMPORALLY_REGRESSIVE,
                )
            if (
                observation.observed_at == self._last_raw_observed_at
                and self._last_raw_availability is not availability
            ):
                return GridAvailability.UNKNOWN, GridOutageEvidenceStatus.CONTRADICTORY

        self._last_raw_observed_at = observation.observed_at
        self._last_raw_availability = availability
        return availability, GridOutageEvidenceStatus.USABLE

    def _unknown_assessment(
        self,
        observation: PoolObservation | None,
        *,
        evaluated_at: datetime,
        status: GridOutageEvidenceStatus,
    ) -> GridOutageAssessment:
        unresolved = (
            self._outage_epoch_started_at if self._confirmed_at is not None else None
        )
        return GridOutageAssessment(
            raw_availability=GridAvailability.UNKNOWN,
            disposition=GridOutageDisposition.UNKNOWN,
            evidence_status=status,
            evaluated_at=evaluated_at,
            observed_at=observation.observed_at if observation is not None else None,
            source_id=observation.source_id if observation is not None else None,
            pending_since=None,
            threshold_reached_at=None,
            outage_epoch_started_at=None,
            confirmed_at=None,
            unresolved_confirmed_outage_since=unresolved,
            grid_returned_at=None,
            reason_code=_unknown_reason(status),
        )

    def _accept_grid_return(
        self,
        observation: PoolObservation | None,
        *,
        evaluated_at: datetime,
    ) -> GridOutageAssessment:
        assert observation is not None
        had_outage_evidence = (
            self._pending_since is not None or self._outage_epoch_started_at is not None
        )
        self._pending_since = None
        self._outage_epoch_started_at = None
        self._confirmed_at = None
        self._grid_returned_at = evaluated_at if had_outage_evidence else None
        return GridOutageAssessment(
            raw_availability=GridAvailability.ON_GRID,
            disposition=GridOutageDisposition.ON_GRID,
            evidence_status=GridOutageEvidenceStatus.USABLE,
            evaluated_at=evaluated_at,
            observed_at=observation.observed_at,
            source_id=observation.source_id,
            pending_since=None,
            threshold_reached_at=None,
            outage_epoch_started_at=None,
            confirmed_at=None,
            unresolved_confirmed_outage_since=None,
            grid_returned_at=self._grid_returned_at,
            reason_code=GridOutageReasonCode.GRID_AVAILABLE_AUTHORITATIVE,
        )

    def _accept_off_grid(
        self,
        observation: PoolObservation | None,
        *,
        evaluated_at: datetime,
    ) -> GridOutageAssessment:
        assert observation is not None
        self._grid_returned_at = None
        if self._confirmed_at is not None:
            return self._confirmed_assessment(observation, evaluated_at=evaluated_at)

        if self._pending_since is None:
            self._pending_since = evaluated_at
            self._outage_epoch_started_at = evaluated_at
        threshold = self._pending_since + self._policy.confirmation_duration
        if evaluated_at >= threshold:
            self._confirmed_at = evaluated_at
            return self._confirmed_assessment(observation, evaluated_at=evaluated_at)

        return GridOutageAssessment(
            raw_availability=GridAvailability.OFF_GRID,
            disposition=GridOutageDisposition.OFF_GRID_PENDING,
            evidence_status=GridOutageEvidenceStatus.USABLE,
            evaluated_at=evaluated_at,
            observed_at=observation.observed_at,
            source_id=observation.source_id,
            pending_since=self._pending_since,
            threshold_reached_at=threshold,
            outage_epoch_started_at=self._outage_epoch_started_at,
            confirmed_at=None,
            unresolved_confirmed_outage_since=None,
            grid_returned_at=None,
            reason_code=GridOutageReasonCode.CONFIRMATION_PENDING,
        )

    def _confirmed_assessment(
        self,
        observation: PoolObservation,
        *,
        evaluated_at: datetime,
    ) -> GridOutageAssessment:
        assert self._pending_since is not None
        assert self._outage_epoch_started_at is not None
        assert self._confirmed_at is not None
        return GridOutageAssessment(
            raw_availability=GridAvailability.OFF_GRID,
            disposition=GridOutageDisposition.CONFIRMED_OUTAGE,
            evidence_status=GridOutageEvidenceStatus.USABLE,
            evaluated_at=evaluated_at,
            observed_at=observation.observed_at,
            source_id=observation.source_id,
            pending_since=self._pending_since,
            threshold_reached_at=(
                self._pending_since + self._policy.confirmation_duration
            ),
            outage_epoch_started_at=self._outage_epoch_started_at,
            confirmed_at=self._confirmed_at,
            unresolved_confirmed_outage_since=None,
            grid_returned_at=None,
            reason_code=GridOutageReasonCode.OUTAGE_CONFIRMED,
        )


def _input_fingerprint(observation: PoolObservation | None) -> tuple[object, ...]:
    if observation is None:
        return (None,)
    return (
        observation.observation_id,
        observation.value,
        observation.observed_at,
        observation.source_kind,
        observation.source_id,
        observation.quality,
        observation.confidence,
    )


def _unknown_reason(status: GridOutageEvidenceStatus) -> GridOutageReasonCode:
    return {
        GridOutageEvidenceStatus.MISSING: GridOutageReasonCode.EVIDENCE_MISSING,
        GridOutageEvidenceStatus.STALE: GridOutageReasonCode.EVIDENCE_STALE,
        GridOutageEvidenceStatus.FUTURE: GridOutageReasonCode.EVIDENCE_FUTURE,
        GridOutageEvidenceStatus.UNUSABLE: GridOutageReasonCode.EVIDENCE_UNUSABLE,
        GridOutageEvidenceStatus.TEMPORALLY_REGRESSIVE: (
            GridOutageReasonCode.EVIDENCE_TEMPORALLY_REGRESSIVE
        ),
        GridOutageEvidenceStatus.CONTRADICTORY: (
            GridOutageReasonCode.EVIDENCE_CONTRADICTORY
        ),
        GridOutageEvidenceStatus.USABLE: GridOutageReasonCode.EVIDENCE_UNUSABLE,
    }[status]


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = [
    "GRID_OUTAGE_CONFIRMATION_DURATION",
    "GRID_OUTAGE_MAX_OBSERVATION_AGE",
    "GRID_OUTAGE_MINIMUM_CONFIDENCE",
    "GRID_OUTAGE_OBSERVATION_ID",
    "GridAvailability",
    "GridOutageAssessment",
    "GridOutageConfirmationPolicy",
    "GridOutageConfirmationTracker",
    "GridOutageDisposition",
    "GridOutageEvidenceStatus",
    "GridOutageReasonCode",
]
