"""An external/native OFF must never demote a durable operator restraint."""
from datetime import UTC, datetime, timedelta
import pytest
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    SpaAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppressionSource,
    pool_suppression_is_current,
    spa_suppression_is_current,
)
from zoneinfo import ZoneInfo

@pytest.mark.parametrize("control,source,check", [
    (PoolAutomaticControlSuppression, PoolAutomaticControlSuppressionSource, pool_suppression_is_current),
    (SpaAutomaticControlSuppression, SpaAutomaticControlSuppressionSource, spa_suppression_is_current),
])
def test_native_off_cannot_demote_operator_restraint(control, source, check):
    runtime = control()
    now = datetime(2026, 10, 9, 7, 0, tzinfo=UTC)
    first = runtime.suppress(source=source.OPERATOR_RESTRAINT,
                             suppressed_at=now, reason="manual_thermostat_authority_delegated")
    second = runtime.suppress(source=source.EXTERNAL_NATIVE_OFF,
                              suppressed_at=now + timedelta(minutes=2), reason="external_authoritative_off")
    assert second is first
    assert runtime.state.source is source.OPERATOR_RESTRAINT
    assert check(runtime.state, evaluated_at=now + timedelta(days=2),
                 timezone=ZoneInfo("America/Los_Angeles"))
    assert runtime.resume(resumed_at=now + timedelta(days=2)).suppressed is False

@pytest.mark.parametrize("control,source", [
    (PoolAutomaticControlSuppression, PoolAutomaticControlSuppressionSource),
    (SpaAutomaticControlSuppression, SpaAutomaticControlSuppressionSource),
])
def test_native_off_still_latches_without_operator_restraint(control, source):
    runtime = control()
    now = datetime(2026, 10, 9, 7, 0, tzinfo=UTC)
    state = runtime.suppress(source=source.EXTERNAL_NATIVE_OFF,
                             suppressed_at=now, reason="external_off")
    assert state.suppressed
    assert state.source is source.EXTERNAL_NATIVE_OFF
