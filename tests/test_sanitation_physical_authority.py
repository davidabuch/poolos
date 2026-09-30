from datetime import UTC, datetime

import pytest

from poolos.pump_operating_target import PumpOperatingTarget, PumpTargetUnit
from poolos.physical_command_authority import (
    PhysicalAuthorityReason,
    PhysicalCommandRequest,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)


def ready() -> PoolOSPhysicalCommandAuthority:
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    return authority


def sanitation_request(
    authority: PoolOSPhysicalCommandAuthority,
    *,
    operation: str,
    target: str,
    value: bool | int | str,
    sanitation_target: PumpOperatingTarget | None = None,
):
    context = authority.bind_sanitation_dispatch(
        session_id="sanitation-session",
        body="hot_tub",
        operation=operation,
        target=target,
        requested_value=value,
        pump_circuit_id="p0103",
        sanitation_rpm=3200,
        sanitation_target=sanitation_target,
    )
    return PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.SANITATION,
        requested_value=value,
        sanitation_context=context,
    )


def test_sanitation_exact_no_heat_body_and_rpm_envelope_is_allowed() -> None:
    authority = ready()
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )

    assert authority.assess(
        sanitation_request(
            authority,
            operation="body_heat_source",
            target="B1202",
            value="00000",
        )
    ).allowed
    assert authority.assess(
        sanitation_request(
            authority,
            operation="body_active",
            target="B1202",
            value=True,
        )
    ).allowed
    assert authority.assess(
        sanitation_request(
            authority,
            operation="pump_circuit_speed",
            target="p0103",
            value=3200,
        )
    ).allowed


def test_sanitation_fences_normal_automatic_work_and_manual_heat() -> None:
    authority = ready()
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )

    automatic = authority.assess(
        PhysicalCommandRequest(
            operation="body_heat_source",
            target="B1202",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value="H0002",
        )
    )
    assert automatic.reason is PhysicalAuthorityReason.SANITATION_ACTIVE

    manual_gas = authority.assess(
        PhysicalCommandRequest(
            operation="body_heat_source",
            target="B1202",
            source=PhysicalRequestSource.MANUAL,
            requested_value="H0001",
        )
    )
    assert manual_gas.reason is PhysicalAuthorityReason.SANITATION_ACTIVE

    manual_solar = authority.assess(
        PhysicalCommandRequest(
            operation="body_heat_source",
            target="B1202",
            source=PhysicalRequestSource.MANUAL,
            requested_value="H0002",
        )
    )
    assert manual_solar.reason is PhysicalAuthorityReason.SANITATION_ACTIVE


def test_manual_pump_change_is_not_blocked_by_sanitation_authority() -> None:
    authority = ready()
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )

    decision = authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0103",
            source=PhysicalRequestSource.MANUAL,
            requested_value=2800,
        )
    )
    assert decision.allowed


def test_grid_outage_preempts_sanitation_dispatch() -> None:
    authority = ready()
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )
    request = sanitation_request(
        authority,
        operation="pump_circuit_speed",
        target="p0103",
        value=3200,
    )
    authority.set_grid_outage_domain_state(
        active=True,
        outage_epoch_id="outage-1",
    )
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-1",
        frame_identity="frame-1",
    )

    decision = authority.assess(request)
    assert decision.reason is PhysicalAuthorityReason.SANITATION_PAUSED_OUTAGE


def test_ending_sanitation_invalidates_old_context() -> None:
    authority = ready()
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )
    request = sanitation_request(
        authority,
        operation="pump_circuit_speed",
        target="p0103",
        value=3200,
    )
    authority.end_sanitation_session(session_id="sanitation-session")

    decision = authority.assess(request)
    assert decision.reason is PhysicalAuthorityReason.SANITATION_INACTIVE


def test_rejected_heat_and_cancel_body_off_do_not_leak_operator_ownership_intent() -> None:
    authority = ready()
    seen = []
    authority.operator_request_listener = lambda request, at: seen.append((request, at))
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
    )

    authority.note_operator_request(
        PhysicalCommandRequest(
            operation="body_heat_source",
            target="B1202",
            source=PhysicalRequestSource.MANUAL,
            requested_value="H0001",
        ),
        at=datetime(2026, 9, 27, tzinfo=UTC),
    )
    authority.note_operator_request(
        PhysicalCommandRequest(
            operation="body_active",
            target="B1202",
            source=PhysicalRequestSource.MANUAL,
            requested_value=False,
        ),
        at=datetime(2026, 9, 27, tzinfo=UTC),
    )
    authority.note_operator_request(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0103",
            source=PhysicalRequestSource.MANUAL,
            requested_value=2800,
        ),
        at=datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert len(seen) == 1
    assert seen[0][0].operation == "pump_circuit_speed"


def test_sanitation_exact_gpm_envelope_is_allowed_and_unit_bound() -> None:
    authority = ready()
    target = PumpOperatingTarget(PumpTargetUnit.GPM, 42)
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
        sanitation_target=target,
    )

    allowed = sanitation_request(
        authority,
        operation="pump_circuit_flow",
        target="p0103",
        value=42,
        sanitation_target=target,
    )
    assert authority.assess(allowed).allowed

    with pytest.raises(ValueError, match="exact sanitation envelope"):
        sanitation_request(
            authority,
            operation="pump_circuit_flow",
            target="p0103",
            value=43,
            sanitation_target=target,
        )

    with pytest.raises(ValueError, match="exact sanitation envelope"):
        sanitation_request(
            authority,
            operation="pump_circuit_speed",
            target="p0103",
            value=42,
            sanitation_target=target,
        )


def test_grid_outage_preempts_gpm_sanitation_dispatch() -> None:
    authority = ready()
    target = PumpOperatingTarget(PumpTargetUnit.GPM, 42)
    authority.begin_sanitation_session(
        body="hot_tub",
        session_id="sanitation-session",
        sanitation_rpm=3200,
        sanitation_target=target,
    )
    request = sanitation_request(
        authority,
        operation="pump_circuit_flow",
        target="p0103",
        value=42,
        sanitation_target=target,
    )
    authority.set_grid_outage_domain_state(
        active=True,
        outage_epoch_id="outage-gpm",
    )
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-gpm",
        frame_identity="frame-gpm",
    )
    assert (
        authority.assess(request).reason
        is PhysicalAuthorityReason.SANITATION_PAUSED_OUTAGE
    )
