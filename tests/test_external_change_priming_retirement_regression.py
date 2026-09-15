from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from test_home_assistant_external_change_runtime import (
    _body_assessment,
    _load_module,
    _thermal_native,
    _thermal_runtime,
    _transport,
)


def test_retiring_accepted_priming_intent_does_not_invent_external_drift() -> None:
    """Retiring accepted priming intent must not manufacture operator takeover."""

    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)

    accepted_intent: dict[str, object] = {"pump.rpm": 3000}
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=SimpleNamespace(
                pool=_body_assessment(
                    module,
                    active=True,
                    disposition="ready",
                    selected_source="solar",
                    rpm=2900,
                ),
                hot_tub=_body_assessment(
                    module,
                    active=False,
                    disposition="already_converged",
                    selected_source="off",
                    rpm=None,
                ),
            ),
        ),
        owned_intent_provider=lambda: accepted_intent,
    )

    now = datetime(2026, 9, 15, 22, 2, 24, tzinfo=UTC)

    # Steady-state Solar planning still advertises 2900 RPM while the accepted
    # execution step temporarily owns a 3000-RPM priming transition.
    runtime.process(
        _thermal_native(now, pump_rpm=2900),
        _transport(now),
        1,
    )
    runtime.process(
        _thermal_native(now + timedelta(seconds=22), pump_rpm=3000),
        _transport(now + timedelta(seconds=22)),
        1,
    )

    assert runtime.diagnostics()["active_drift_count"] == 0

    # Reproduce the commissioning boundary: the accepted 3000-RPM priming
    # intent is retired before native truth has moved back to the steady-state
    # 2900-RPM Solar setpoint. No native transition occurs at this boundary.
    accepted_intent.clear()
    runtime.refresh_ownership()

    # A mere mismatch after accepted-intent retirement is not positive evidence
    # of manual/external takeover. PoolOS must preserve convergence authority
    # until a real contradictory native event or the bounded convergence policy
    # says otherwise.
    assert runtime.diagnostics()["active_drift_count"] == 0
    assert runtime.diagnostics()["state"] == "MONITORING"
