from datetime import UTC, datetime

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


def sanitation_request(authority: PoolOSPhysicalCommandAuthority, *, operation: str, target: str, value: bool | int | str):
    context = authority.bind_sanitation_dispatch(
        session_id="sanitation-session",
        body="hot_tub",
        operation=operation,
        target=target,
        requested_value=value,
        pump_circuit_id="p0103",
        sanitation_rpm=3200,
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
