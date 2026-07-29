"""In-memory storage semantics for canonical PoolOS observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .model import ObservationSourceKind, PoolObservation


class ObservationStoreError(ValueError):
    """Base exception for observation storage failures."""


class ObservationTimestampConflictError(ObservationStoreError):
    """Raised when one source repeats an already accepted timestamp."""


class ObservationOutOfOrderError(ObservationStoreError):
    """Raised when one source attempts to publish an older observation."""


@dataclass(frozen=True, slots=True)
class ObservationSourceKey:
    """Identity of one producer for one canonical observation ID."""

    observation_id: str
    source_kind: ObservationSourceKind
    source_id: str | None


@dataclass(slots=True)
class ObservationStore:
    """Retain the latest observation from each source without silent replacement."""

    _latest_by_source: dict[ObservationSourceKey, PoolObservation] = field(
        default_factory=dict
    )

    def put(self, observation: PoolObservation) -> None:
        """Accept a newer observation or reject ambiguous temporal ordering."""

        observed_at = _required_timestamp(observation)
        key = ObservationSourceKey(
            observation.observation_id,
            observation.source_kind,
            observation.source_id,
        )
        current = self._latest_by_source.get(key)
        if current is not None:
            current_at = _required_timestamp(current)
            if observed_at == current_at:
                raise ObservationTimestampConflictError(
                    "equal timestamps from the same observation source are rejected"
                )
            if observed_at < current_at:
                raise ObservationOutOfOrderError(
                    "older timestamps from the same observation source are rejected"
                )
        self._latest_by_source[key] = observation

    def get(
        self,
        observation_id: str,
        *,
        source_kind: ObservationSourceKind | None = None,
        source_id: str | None = None,
    ) -> PoolObservation | None:
        """Return the newest matching observation across admitted sources."""

        matches = self.get_all(
            observation_id,
            source_kind=source_kind,
            source_id=source_id,
        )
        return max(matches, key=_required_timestamp, default=None)

    def get_all(
        self,
        observation_id: str,
        *,
        source_kind: ObservationSourceKind | None = None,
        source_id: str | None = None,
    ) -> tuple[PoolObservation, ...]:
        """Return all latest source records for one canonical observation ID."""

        matches = [
            observation
            for key, observation in self._latest_by_source.items()
            if key.observation_id == observation_id
            and (source_kind is None or key.source_kind is source_kind)
            and (source_id is None or key.source_id == source_id)
        ]
        return tuple(sorted(matches, key=_required_timestamp, reverse=True))

    def values(self) -> tuple[PoolObservation, ...]:
        """Return all retained source records in deterministic order."""

        return tuple(
            sorted(
                self._latest_by_source.values(),
                key=lambda item: (
                    item.observation_id,
                    item.source_kind.value,
                    item.source_id or "",
                    _required_timestamp(item),
                ),
            )
        )

    def extend(self, observations: Iterable[PoolObservation]) -> None:
        for observation in observations:
            self.put(observation)

    def __len__(self) -> int:
        return len(self._latest_by_source)


def _required_timestamp(observation: PoolObservation) -> datetime:
    if observation.observed_at is None:
        raise ObservationStoreError(
            "stored observations require a timezone-aware observed_at timestamp"
        )
    return observation.observed_at


__all__ = [
    "ObservationOutOfOrderError",
    "ObservationSourceKey",
    "ObservationStore",
    "ObservationStoreError",
    "ObservationTimestampConflictError",
]
