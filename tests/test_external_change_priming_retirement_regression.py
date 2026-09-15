from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from poolos.external_change import ExternalChangeBatch, ExternalChangeEvent
from poolos.integration import PhysicalHeatMode
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.thermal_termination import (
    ThermalTerminationDisposition,
    ThermalTerminationPolicy,
)
from test_home_assistant_external_change_runtime import (
    _body_assessment,
    _load_module,
    _thermal_native,
    _thermal_runtime,
    _transport,
)
from test_thermal_termination import NOW as TERMINATION_NOW
from test_thermal_termination import _entitlement, _evidence


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


def test_unattributed_pre_provenance_pump_event_does_not_poison_verified_session() -> None:
    """Unattributed pre-provenance movement is not positive operator takeover proof."""

    # Reproduce the second September 15 boundary.  PoolOS has already created
    # the body session.  Native pump truth moves during that session before the
    # later pump command has independently established accepted Pump provenance.
    # The movement was not positively attributed to an operator; it was merely
    # classified as an unattributed native change and retained by concept.
    event = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type="native_value_changed",
        native_object_id="PMP01",
        previous_value=0,
        new_value=2900,
        observed_at=TERMINATION_NOW - timedelta(milliseconds=750),
        external_policy="accept",
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
        reason_code="external_unattributed_native_change",
    )

    # The same session subsequently establishes verified Pump provenance.  The
    # earlier unattributed event must not later be upgraded into proof of manual
    # takeover simply because it is retained across the lease.
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(changes=ExternalChangeBatch((event,))),
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.reason_code == "thermal_termination_owned_source_off_ready"
    assert result.operation is not None
