from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppression,
    SpaAutomaticControlSuppressionSource,
    pool_suppression_is_current,
    spa_suppression_is_current,
)


NOW = datetime(2026, 9, 8, 18, 0, tzinfo=UTC)


def test_baseline_off_state_is_unsuppressed_and_owns_nothing() -> None:
    restraint = PoolAutomaticControlSuppression()

    assert restraint.state.suppressed is False
    assert restraint.state.source is None
    assert restraint.diagnostics()["authority"] == "none"


def test_positive_human_off_latches_until_explicit_command_free_resume() -> None:
    restraint = PoolAutomaticControlSuppression()
    seen = []
    restraint.add_listener(seen.append)

    restraint.suppress(
        source=PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
        suppressed_at=NOW,
        reason="external_authoritative_pool_on_to_off",
    )
    assert restraint.state.suppressed
    assert restraint.state.suppressed_at == NOW

    # Hardware changes and elapsed time are not inputs and cannot clear it.
    assert restraint.state.suppressed
    restraint.resume(resumed_at=NOW + timedelta(hours=8))

    assert restraint.state.suppressed is False
    assert restraint.state.source is None
    assert restraint.diagnostics()["command_delivery_performed"] is False
    assert len(seen) == 2


def test_duplicate_external_event_is_idempotent() -> None:
    restraint = PoolAutomaticControlSuppression()
    for _ in range(2):
        restraint.suppress(
            source=PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
            suppressed_at=NOW,
            reason="external_authoritative_pool_on_to_off",
        )

    assert restraint.state.generation == 1


def test_pool_and_spa_restraints_are_independent() -> None:
    pool = PoolAutomaticControlSuppression()
    spa = SpaAutomaticControlSuppression()

    pool.suppress(
        source=PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
        suppressed_at=NOW,
        reason="pool_off",
    )
    assert pool.state.suppressed
    assert not spa.state.suppressed

    spa.suppress(
        source=SpaAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
        suppressed_at=NOW,
        reason="spa_off",
    )
    pool.resume(resumed_at=NOW + timedelta(seconds=1))

    assert not pool.state.suppressed
    assert spa.state.suppressed
    assert spa.diagnostics()["spa_manual_off_resume_required"] is True

LOCAL = ZoneInfo("America/Los_Angeles")


def test_pool_manual_off_restraint_is_current_until_next_operational_day() -> None:
    restraint = PoolAutomaticControlSuppression()
    state = restraint.suppress(
        source=PoolAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="manual_poolos_off_request",
    )

    assert pool_suppression_is_current(
        state,
        evaluated_at=datetime(2026, 9, 11, 7, 59, tzinfo=LOCAL),
        timezone=LOCAL,
    )

    assert not pool_suppression_is_current(
        state,
        evaluated_at=datetime(2026, 9, 11, 8, 0, tzinfo=LOCAL),
        timezone=LOCAL,
    )


def test_pool_external_native_off_expires_next_operational_day() -> None:
    restraint = PoolAutomaticControlSuppression()
    state = restraint.suppress(
        source=PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="external_authoritative_pool_on_to_off",
    )

    assert not pool_suppression_is_current(
        state,
        evaluated_at=datetime(2026, 9, 11, 8, 0, tzinfo=LOCAL),
        timezone=LOCAL,
    )


def test_pool_operator_restraint_does_not_expire_with_operational_day() -> None:
    restraint = PoolAutomaticControlSuppression()
    state = restraint.suppress(
        source=PoolAutomaticControlSuppressionSource.OPERATOR_RESTRAINT,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="operator_disabled_autonomous_pool_control",
    )

    assert pool_suppression_is_current(
        state,
        evaluated_at=datetime(2026, 9, 12, 8, 0, tzinfo=LOCAL),
        timezone=LOCAL,
    )


def test_pool_restored_unknown_restraint_remains_conservative() -> None:
    restraint = PoolAutomaticControlSuppression()
    state = restraint.suppress(
        source=PoolAutomaticControlSuppressionSource.RESTORED,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="restored_unknown_restraint",
    )

    assert pool_suppression_is_current(
        state,
        evaluated_at=datetime(2026, 9, 12, 8, 0, tzinfo=LOCAL),
        timezone=LOCAL,
    )


def test_spa_transient_expiry_is_independent_from_pool_operator_restraint() -> None:
    pool = PoolAutomaticControlSuppression()
    spa = SpaAutomaticControlSuppression()

    pool_state = pool.suppress(
        source=PoolAutomaticControlSuppressionSource.OPERATOR_RESTRAINT,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="operator_disabled_autonomous_pool_control",
    )
    spa_state = spa.suppress(
        source=SpaAutomaticControlSuppressionSource.MANUAL_POOLOS_OFF_REQUEST,
        suppressed_at=datetime(2026, 9, 10, 18, 0, tzinfo=LOCAL),
        reason="manual_poolos_spa_off_request",
    )

    evaluated_at = datetime(2026, 9, 11, 8, 0, tzinfo=LOCAL)

    assert pool_suppression_is_current(
        pool_state,
        evaluated_at=evaluated_at,
        timezone=LOCAL,
    )
    assert not spa_suppression_is_current(
        spa_state,
        evaluated_at=evaluated_at,
        timezone=LOCAL,
    )
