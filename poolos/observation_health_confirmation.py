"""Deterministic confirmation for durable observation-health diagnostics.

Immediate runtime health never passes through this boundary.  It only decides
whether unhealthy evidence is sufficiently distinct to promote a durable
operator-facing incident latch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DurableHealthConfirmationState:
    """Immutable durable-latch and pending-candidate evidence."""

    confirmed: bool = False
    confirmed_started_at: datetime | None = None
    pending_snapshot_generated_at: datetime | None = None
    pending_started_at: datetime | None = None
    missing_required: tuple[str, ...] = ()
    unavailable_entities: tuple[str, ...] = ()
    stale_entities: tuple[str, ...] = ()

    @property
    def pending(self) -> bool:
        return self.pending_snapshot_generated_at is not None


def evaluate_durable_health_confirmation(
    state: DurableHealthConfirmationState,
    *,
    healthy: bool,
    snapshot_generated_at: datetime,
    in_startup_grace: bool,
    missing_required: tuple[str, ...] = (),
    unavailable_entities: tuple[str, ...] = (),
    stale_entities: tuple[str, ...] = (),
) -> DurableHealthConfirmationState:
    """Advance durable confirmation without changing immediate runtime health."""

    _require_aware(snapshot_generated_at)
    if in_startup_grace:
        return _clear_pending(state)
    if healthy:
        return _clear_pending(state)

    missing = _union(state.missing_required, missing_required)
    unavailable = _union(state.unavailable_entities, unavailable_entities)
    stale = _union(state.stale_entities, stale_entities)
    if state.confirmed:
        return DurableHealthConfirmationState(
            confirmed=True,
            confirmed_started_at=state.confirmed_started_at,
            missing_required=missing,
            unavailable_entities=unavailable,
            stale_entities=stale,
        )
    if state.pending_snapshot_generated_at is None:
        return DurableHealthConfirmationState(
            pending_snapshot_generated_at=snapshot_generated_at,
            pending_started_at=snapshot_generated_at,
            missing_required=tuple(sorted(set(missing_required))),
            unavailable_entities=tuple(sorted(set(unavailable_entities))),
            stale_entities=tuple(sorted(set(stale_entities))),
        )
    if state.pending_snapshot_generated_at == snapshot_generated_at:
        return DurableHealthConfirmationState(
            pending_snapshot_generated_at=state.pending_snapshot_generated_at,
            pending_started_at=state.pending_started_at,
            missing_required=missing,
            unavailable_entities=unavailable,
            stale_entities=stale,
        )
    return DurableHealthConfirmationState(
        confirmed=True,
        confirmed_started_at=state.pending_started_at,
        missing_required=missing,
        unavailable_entities=unavailable,
        stale_entities=stale,
    )


def reset_durable_health_confirmation() -> DurableHealthConfirmationState:
    """Return the empty state used by an explicit non-actuating reset."""

    return DurableHealthConfirmationState()


def _clear_pending(
    state: DurableHealthConfirmationState,
) -> DurableHealthConfirmationState:
    if state.confirmed:
        return DurableHealthConfirmationState(
            confirmed=True,
            confirmed_started_at=state.confirmed_started_at,
            missing_required=state.missing_required,
            unavailable_entities=state.unavailable_entities,
            stale_entities=state.stale_entities,
        )
    return DurableHealthConfirmationState()


def _union(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(left) | set(right)))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot_generated_at must be timezone-aware")


__all__ = [
    "DurableHealthConfirmationState",
    "evaluate_durable_health_confirmation",
    "reset_durable_health_confirmation",
]
