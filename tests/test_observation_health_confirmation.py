from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.observation_health_confirmation import (
    DurableHealthConfirmationState,
    evaluate_durable_health_confirmation,
    reset_durable_health_confirmation,
)


NOW = datetime(2026, 8, 27, 23, 57, 38, tzinfo=UTC)


def evaluate(
    state: DurableHealthConfirmationState,
    *,
    healthy: bool,
    at: datetime,
    grace: bool = False,
) -> DurableHealthConfirmationState:
    return evaluate_durable_health_confirmation(
        state,
        healthy=healthy,
        snapshot_generated_at=at,
        in_startup_grace=grace,
        unavailable_entities=("binary_sensor.grid",) if not healthy else (),
        stale_entities=("B1202", "PMP01") if not healthy else (),
    )


def test_one_unhealthy_cycle_is_pending_and_recovery_clears_it() -> None:
    pending = evaluate(DurableHealthConfirmationState(), healthy=False, at=NOW)
    recovered = evaluate(
        pending,
        healthy=True,
        at=NOW + timedelta(milliseconds=63),
    )

    assert pending.pending
    assert not pending.confirmed
    assert not recovered.pending
    assert not recovered.confirmed


def test_same_unhealthy_snapshot_cannot_confirm_itself() -> None:
    pending = evaluate(DurableHealthConfirmationState(), healthy=False, at=NOW)
    repeated = evaluate(pending, healthy=False, at=NOW)

    assert repeated.pending
    assert not repeated.confirmed


def test_distinct_second_unhealthy_snapshot_confirms_first_timestamp() -> None:
    pending = evaluate(DurableHealthConfirmationState(), healthy=False, at=NOW)
    confirmed = evaluate(
        pending,
        healthy=False,
        at=NOW + timedelta(seconds=1),
    )

    assert confirmed.confirmed
    assert not confirmed.pending
    assert confirmed.confirmed_started_at == NOW
    assert confirmed.unavailable_entities == ("binary_sensor.grid",)
    assert confirmed.stale_entities == ("B1202", "PMP01")


def test_confirmed_latch_survives_recovery_and_reset_clears_all_state() -> None:
    pending = evaluate(DurableHealthConfirmationState(), healthy=False, at=NOW)
    confirmed = evaluate(
        pending,
        healthy=False,
        at=NOW + timedelta(seconds=1),
    )
    healthy = evaluate(
        confirmed,
        healthy=True,
        at=NOW + timedelta(seconds=2),
    )

    assert healthy.confirmed
    assert not healthy.pending
    assert reset_durable_health_confirmation() == DurableHealthConfirmationState()


def test_startup_grace_never_seeds_pending_confirmation() -> None:
    ignored = evaluate(
        DurableHealthConfirmationState(), healthy=False, at=NOW, grace=True
    )
    post_grace = evaluate(
        ignored,
        healthy=False,
        at=NOW + timedelta(minutes=1),
    )

    assert not ignored.pending
    assert post_grace.pending
    assert not post_grace.confirmed
