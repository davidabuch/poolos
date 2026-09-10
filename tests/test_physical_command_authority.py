from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from poolos.physical_command_authority import (
    AutomaticFiltrationDispatchPurpose,
    AutomaticThermalDispatchContext,
    AutomaticThermalDispatchPurpose,
    ExpectedNativeConsequence,
    GridOutageDispatchPurpose,
    PhysicalAuthorityReason,
    PhysicalCommandDeniedError,
    PhysicalCommandRequest,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def request(
    source: PhysicalRequestSource = PhysicalRequestSource.MANUAL,
) -> PhysicalCommandRequest:
    return PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=source,
        requested_value=True,
    )


def consequence(
    value: bool | int | float | str = True,
) -> ExpectedNativeConsequence:
    return ExpectedNativeConsequence("pool.active", "B1101", value)


def ready() -> PoolOSPhysicalCommandAuthority:
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    return authority


def test_startup_and_maintenance_fail_closed_for_every_request_source() -> None:
    authority = PoolOSPhysicalCommandAuthority()
    for source in PhysicalRequestSource:
        decision = authority.assess(request(source))
        assert not decision.allowed
        assert decision.reason is PhysicalAuthorityReason.AUTHORITY_UNRESOLVED

    authority.resolve_maintenance(True)
    authority.set_controller_mode("auto")
    for source in PhysicalRequestSource:
        decision = authority.assess(request(source))
        assert not decision.allowed
        assert decision.reason is PhysicalAuthorityReason.MAINTENANCE_MODE


@pytest.mark.parametrize(
    ("mode", "reason"),
    (
        (None, PhysicalAuthorityReason.CONTROLLER_MODE_UNRESOLVED),
        ("service", PhysicalAuthorityReason.CONTROLLER_SERVICE_MODE),
        ("timeout", PhysicalAuthorityReason.CONTROLLER_TIMEOUT_MODE),
    ),
)
def test_native_service_and_timeout_modes_remain_command_prohibitions(
    mode: str | None, reason: PhysicalAuthorityReason
) -> None:
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode(mode)
    assert authority.assess(request()).reason is reason


def test_automatic_filtration_authority_is_default_off_exact_and_epoch_bound() -> None:
    authority = ready()
    authority.begin_automatic_filtration_epoch("epoch-1")
    context = authority.bind_automatic_filtration_dispatch(
        epoch_identity="epoch-1",
        session_identity="filtration-session",
        operation_identity="operation-1",
        operation="pump_circuit_speed",
        target="p0102",
        requested_value=2600,
        pump_circuit_id="p0102",
    )
    filtration = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
        requested_value=2600,
        automatic_filtration_context=context,
    )
    assert authority.assess(filtration).reason is PhysicalAuthorityReason.AUTOMATIC_FILTRATION_GATE_DISABLED

    authority.configure_automatic_filtration(enabled=True)
    authority.begin_automatic_filtration_epoch("epoch-2")
    context = authority.bind_automatic_filtration_dispatch(
        epoch_identity="epoch-2",
        session_identity="filtration-session",
        operation_identity="operation-2",
        operation="pump_circuit_speed",
        target="p0102",
        requested_value=2600,
        pump_circuit_id="p0102",
    )
    filtration = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
        requested_value=2600,
        automatic_filtration_context=context,
    )
    assert authority.assess(filtration).allowed
    wrong = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
        requested_value=2900,
        automatic_filtration_context=context,
    )
    assert authority.assess(wrong).reason is PhysicalAuthorityReason.AUTOMATIC_FILTRATION_OPERATION_UNAUTHORIZED

    authority.begin_automatic_filtration_epoch("epoch-3")
    assert authority.assess(filtration).reason is PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_STALE


def test_disabled_filtration_gate_allows_only_bound_owned_body_cleanup() -> None:
    authority = ready()
    authority.begin_automatic_filtration_epoch("epoch-1")
    with pytest.raises(
        ValueError,
        match="filtration cleanup requires exact body ownership provenance",
    ):
        authority.bind_automatic_filtration_dispatch(
            epoch_identity="epoch-1",
            session_identity="filtration-session",
            operation_identity="unproven-body-off",
            operation="body_active",
            target="B1101",
            requested_value=False,
            pump_circuit_id="p0102",
            cleanup=True,
        )
    context = authority.bind_automatic_filtration_dispatch(
        epoch_identity="epoch-1",
        session_identity="filtration-session",
        operation_identity="body-off",
        operation="body_active",
        target="B1101",
        requested_value=False,
        pump_circuit_id="p0102",
        cleanup=True,
        ownership_lease_id="filtration-lease",
        body_activation_receipt_id="body-activation-receipt",
    )
    assert context.purpose is AutomaticFiltrationDispatchPurpose.OWNED_BODY_CLEANUP
    cleanup = PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
        requested_value=False,
        automatic_filtration_context=context,
    )
    assert authority.assess(cleanup).allowed


def test_expectation_lifecycle_is_pre_dispatch_bounded_and_value_specific() -> None:
    authority = ready()
    expectation = authority.reserve(request(), consequence(), now=NOW)
    assert authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=True,
        observed_at=NOW,
    ) is None

    authority.mark_dispatch_started(expectation)
    assert authority.correlate(
        concept="spa.active",
        native_object_id="B1202",
        value=True,
        observed_at=NOW,
    ) is None
    assert authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=False,
        observed_at=NOW,
    ) is None
    attribution = authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=True,
        observed_at=NOW,
    )
    assert attribution is not None
    assert attribution.request_source is PhysicalRequestSource.MANUAL
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0


def test_denied_failed_expired_and_restart_expectations_cannot_hide_changes() -> None:
    authority = ready()
    expectation = authority.reserve(request(), consequence(), now=NOW)
    authority.resolve_maintenance(True)
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0
    assert not authority.cancel(expectation)
    with pytest.raises(PhysicalCommandDeniedError):
        authority.reserve(request(), consequence(), now=NOW)

    authority.resolve_maintenance(False)
    expiring = authority.reserve(request(), consequence(), now=NOW)
    authority.mark_dispatch_started(expiring)
    assert authority.expire(now=NOW + timedelta(seconds=46)) == 1
    assert authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=True,
        observed_at=NOW + timedelta(seconds=46),
    ) is None

    restarted = PoolOSPhysicalCommandAuthority()
    assert restarted.diagnostics(now=NOW)["pending_expectation_count"] == 0
    assert not restarted.maintenance_resolved


def test_expectation_expires_at_boundary_and_requires_exact_native_object() -> None:
    authority = ready()
    expectation = authority.reserve(request(), consequence(), now=NOW)
    authority.mark_dispatch_started(expectation)
    assert authority.correlate(
        concept="pool.active",
        native_object_id=None,
        value=True,
        observed_at=NOW + timedelta(seconds=1),
    ) is None
    assert authority.expire(now=NOW + timedelta(seconds=45)) == 1


def test_expectation_capacity_fails_closed_without_unbounded_growth() -> None:
    authority = PoolOSPhysicalCommandAuthority(expectation_limit=2)
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.reserve(request(), consequence(), now=NOW)
    authority.reserve(request(), consequence(False), now=NOW)
    with pytest.raises(RuntimeError, match="capacity"):
        authority.reserve(request(), consequence(), now=NOW)
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 2


def test_native_no_op_does_not_reserve_a_stale_transition_expectation() -> None:
    authority = ready()
    authority.replace_native_truth({("pool.active", "B1101"): True})

    assert authority.reserve(request(), consequence(), now=NOW) is None
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0
    assert authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=True,
        observed_at=NOW + timedelta(seconds=2),
    ) is None


def test_grid_outage_authority_is_default_off_exact_and_independent() -> None:
    authority = ready()
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-1", frame_identity="frame-1"
    )
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage-1",
        frame_identity="frame-1",
        candidate_id="candidate-1",
        purpose=GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
        operation="pump_circuit_speed",
        target="p0199",
        requested_value=1500,
    )
    context = authority.bind_grid_outage_dispatch(registered)
    exact = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value=1500,
        grid_outage_context=context,
    )
    assert authority.assess(exact).reason is PhysicalAuthorityReason.GRID_OUTAGE_GATE_DISABLED

    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-1", frame_identity="frame-2"
    )
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage-1",
        frame_identity="frame-2",
        candidate_id="candidate-2",
        purpose=GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
        operation="pump_circuit_speed",
        target="p0199",
        requested_value=1500,
    )
    context = authority.bind_grid_outage_dispatch(registered)
    exact = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value=1500,
        grid_outage_context=context,
    )
    assert authority.assess(exact).allowed

    wrong = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value=1800,
        grid_outage_context=context,
    )
    assert authority.assess(wrong).reason is PhysicalAuthorityReason.GRID_OUTAGE_OPERATION_UNAUTHORIZED


def test_grid_outage_context_is_invalidated_by_new_frame_gate_or_unload() -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="one")
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage",
        frame_identity="one",
        candidate_id="candidate",
        purpose=GridOutageDispatchPurpose.POOL_SOURCE_OFF,
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )
    context = authority.bind_grid_outage_dispatch(registered)
    request = PhysicalCommandRequest(
        operation="body_heat_source",
        target="B1101",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value="00000",
        grid_outage_context=context,
    )
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="two")
    assert authority.assess(request).reason is PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_STALE
    authority.configure_grid_outage_safety(enabled=False)
    assert authority.assess(request).reason is PhysicalAuthorityReason.GRID_OUTAGE_GATE_DISABLED
    authority.unload_grid_outage_safety()
    authority.configure_grid_outage_safety(enabled=True)
    assert authority.assess(request).reason is PhysicalAuthorityReason.GRID_OUTAGE_DRIVER_UNLOADED


def test_outage_invalidation_preserves_only_dispatched_attribution() -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="one")
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage",
        frame_identity="one",
        candidate_id="candidate",
        purpose=GridOutageDispatchPurpose.POOL_SOURCE_OFF,
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )
    context = authority.bind_grid_outage_dispatch(registered)
    request = PhysicalCommandRequest(
        operation="body_heat_source",
        target="B1101",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value="00000",
        grid_outage_context=context,
    )
    pending = authority.reserve(
        request,
        ExpectedNativeConsequence("pool.raw_heater_id", "B1101", "00000"),
        now=NOW,
    )
    assert pending is not None
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="two")
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0

    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="three")
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage",
        frame_identity="three",
        candidate_id="accepted",
        purpose=GridOutageDispatchPurpose.POOL_SOURCE_OFF,
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )
    context = authority.bind_grid_outage_dispatch(registered)
    accepted_request = PhysicalCommandRequest(
        operation="body_heat_source",
        target="B1101",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value="00000",
        grid_outage_context=context,
    )
    dispatched = authority.reserve(
        accepted_request,
        ExpectedNativeConsequence("pool.raw_heater_id", "B1101", "00000"),
        now=NOW,
    )
    assert dispatched is not None
    authority.mark_dispatch_started(dispatched)
    authority.begin_grid_outage_frame(outage_epoch_id=None, frame_identity="grid-return")
    attribution = authority.correlate(
        concept="pool.raw_heater_id",
        native_object_id="B1101",
        value="00000",
        observed_at=NOW + timedelta(seconds=1),
    )
    assert attribution is not None
    assert attribution.request_source is PhysicalRequestSource.GRID_OUTAGE_SAFETY


def test_normal_thermal_epoch_change_cannot_erase_dispatched_outage_attribution() -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage",
        frame_identity="outage-frame",
    )
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage",
        frame_identity="outage-frame",
        candidate_id="outage-source-off",
        purpose=GridOutageDispatchPurpose.POOL_SOURCE_OFF,
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )
    context = authority.bind_grid_outage_dispatch(registered)
    outage_request = PhysicalCommandRequest(
        operation="body_heat_source",
        target="B1101",
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value="00000",
        grid_outage_context=context,
    )
    expectation = authority.reserve(
        outage_request,
        ExpectedNativeConsequence("pool.raw_heater_id", "B1101", "00000"),
        now=NOW,
    )
    assert expectation is not None
    authority.mark_dispatch_started(expectation)

    authority.begin_automatic_thermal_epoch("new-normal-thermal-frame")

    attribution = authority.correlate(
        concept="pool.raw_heater_id",
        native_object_id="B1101",
        value="00000",
        observed_at=NOW + timedelta(seconds=1),
    )
    assert attribution is not None
    assert attribution.request_source is PhysicalRequestSource.GRID_OUTAGE_SAFETY


@pytest.mark.parametrize(
    ("purpose", "operation", "target", "value"),
    (
        (GridOutageDispatchPurpose.SPA_SOURCE_OFF, "body_heat_source", "B1202", "00000"),
        (GridOutageDispatchPurpose.POOL_SOURCE_OFF, "body_heat_source", "B1101", "00000"),
        (GridOutageDispatchPurpose.POOL_LIGHT_OFF, "circuit_active", "C0002", False),
        (GridOutageDispatchPurpose.JETS_OFF, "circuit_active", "C0003", False),
        (GridOutageDispatchPurpose.SLIDE_OFF, "circuit_active", "C0004", False),
        (GridOutageDispatchPurpose.WATERFALL_OFF, "circuit_active", "FTR01", False),
        (GridOutageDispatchPurpose.SPA_BODY_OFF, "body_active", "B1202", False),
        (GridOutageDispatchPurpose.POOL_PUMP_REDUCTION, "pump_circuit_speed", "p0102", 1500),
    ),
)
def test_grid_outage_exact_envelope_allowlist(
    purpose: GridOutageDispatchPurpose,
    operation: str,
    target: str,
    value: bool | int | str,
) -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="frame")
    registered = authority.register_grid_outage_candidate(
        outage_epoch_id="outage",
        frame_identity="frame",
        candidate_id=purpose.value,
        purpose=purpose,
        operation=operation,
        target=target,
        requested_value=value,
    )
    context = authority.bind_grid_outage_dispatch(registered)
    request = PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        requested_value=value,
        grid_outage_context=context,
    )
    assert authority.assess(request).allowed


def test_grid_outage_envelopes_reject_bool_int_equivalence() -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(outage_epoch_id="outage", frame_identity="frame")
    with pytest.raises(ValueError, match="exact reduction envelope"):
        authority.register_grid_outage_candidate(
            outage_epoch_id="outage",
            frame_identity="frame",
            candidate_id="wrong-type",
            purpose=GridOutageDispatchPurpose.POOL_LIGHT_OFF,
            operation="circuit_active",
            target="C0002",
            requested_value=0,
        )


@pytest.mark.parametrize(
    ("purpose", "operation", "target", "value"),
    (
        (GridOutageDispatchPurpose.SPA_BODY_OFF, "body_active", "B1101", False),
        (GridOutageDispatchPurpose.SPA_BODY_OFF, "body_active", "B1202", True),
        (
            GridOutageDispatchPurpose.POOL_SOURCE_OFF,
            "body_heat_source",
            "B1101",
            "H0001",
        ),
        (GridOutageDispatchPurpose.POOL_LIGHT_OFF, "circuit_active", "C0002", True),
        (GridOutageDispatchPurpose.POOL_LIGHT_OFF, "circuit_active", "C9999", False),
        (
            GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
            "pump_circuit_speed",
            "p0102",
            2600,
        ),
        (
            GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
            "pump_circuit_speed",
            "p9999",
            1500,
        ),
    ),
)
def test_grid_outage_registration_rejects_every_broader_physical_shape(
    purpose: GridOutageDispatchPurpose,
    operation: str,
    target: str,
    value: bool | int | str,
) -> None:
    authority = ready()
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage",
        frame_identity="frame",
    )
    with pytest.raises(ValueError, match="exact reduction envelope"):
        authority.register_grid_outage_candidate(
            outage_epoch_id="outage",
            frame_identity="frame",
            candidate_id="broader-shape",
            purpose=purpose,
            operation=operation,
            target=target,
            requested_value=value,
        )


def test_real_transition_still_correlates_after_native_truth_sync() -> None:
    authority = ready()
    authority.replace_native_truth({("pool.active", "B1101"): False})
    expectation = authority.reserve(request(), consequence(), now=NOW)
    assert expectation is not None
    authority.mark_dispatch_started(expectation)

    assert authority.correlate(
        concept="pool.active",
        native_object_id="B1101",
        value=True,
        observed_at=NOW + timedelta(seconds=1),
    ) is not None


def test_service_timeout_denial_does_not_replay_after_fresh_auto_recovery() -> None:
    authority = ready()
    stale = authority.reserve(request(), consequence(), now=NOW)
    assert stale is not None
    authority.mark_dispatch_started(stale)
    authority.set_controller_mode("service")
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0
    with pytest.raises(PhysicalCommandDeniedError):
        authority.reserve(request(), consequence(), now=NOW)
    assert authority.diagnostics(now=NOW)["pending_expectation_count"] == 0

    authority.set_controller_mode("auto")
    expectation = authority.reserve(
        request(), consequence(), now=NOW + timedelta(seconds=1)
    )
    assert expectation is not None
    assert authority.diagnostics(
        now=NOW + timedelta(seconds=1)
    )["pending_expectation_count"] == 1


def automatic_request(
    context: AutomaticThermalDispatchContext | None,
) -> PhysicalCommandRequest:
    return PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=True,
        automatic_thermal_context=context,
    )


def test_automatic_thermal_final_gateway_requires_both_independent_gates() -> None:
    authority = ready()
    authority.begin_automatic_thermal_epoch("epoch-1")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-1",
        session_identity="session-1",
        body="pool",
        pump_circuit_id="p0102",
    )

    assert authority.assess(automatic_request(context)).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_GATE_DISABLED
    )

    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=False,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-2")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-2",
        session_identity="session-2",
        body="pool",
    )
    assert authority.assess(automatic_request(context)).reason is (
        PhysicalAuthorityReason.THERMAL_LIVE_GATE_DISABLED
    )

    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-3")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-3",
        session_identity="session-3",
        body="pool",
    )
    assert authority.assess(automatic_request(context)).allowed


def test_automatic_thermal_context_is_invalidated_by_epoch_or_gate_loss() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-1")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-1",
        session_identity="session-1",
        body="pool",
    )
    request_one = automatic_request(context)
    assert authority.assess(request_one).allowed

    authority.begin_automatic_thermal_epoch("epoch-2")
    assert authority.assess(request_one).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
    )

    context_two = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-2",
        session_identity="session-1",
        body="pool",
    )
    request_two = automatic_request(context_two)
    assert authority.assess(request_two).allowed
    authority.configure_automatic_thermal(
        driver_enabled=False,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    assert authority.assess(request_two).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_GATE_DISABLED
    )


def test_automatic_thermal_scope_and_unload_fail_closed() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("epoch-1")
    pool_context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-1",
        session_identity="session-1",
        body="pool",
    )
    assert authority.assess(automatic_request(pool_context)).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_SCOPE_MISMATCH
    )

    authority.unload_automatic_thermal_driver()
    assert authority.assess(automatic_request(pool_context)).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_DRIVER_UNLOADED
    )


@pytest.mark.parametrize(
    ("operation", "target", "value"),
    (
        ("body_active", "B1202", True),
        ("body_active", "B1101", False),
        ("body_heat_source", "B1202", "H0002"),
        ("body_heat_source", "B1101", "HXSLR"),
        ("pump_circuit_speed", "p9999", 2900),
        ("pump_circuit_speed", "p0102", 1500),
        ("pump_circuit_speed", "p0102", 2600),
        ("circuit_active", "C0002", True),
    ),
)
def test_automatic_thermal_final_gateway_rejects_operation_scope_mismatch(
    operation: str,
    target: str,
    value: bool | int | str,
) -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-1")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-1",
        session_identity="session-1",
        body="pool",
    )
    proposed = PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=value,
        automatic_thermal_context=context,
    )

    assert authority.assess(proposed).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )


@pytest.mark.parametrize(
    ("operation", "target", "value"),
    (
        ("body_active", "B1101", True),
        ("body_heat_source", "B1101", "00000"),
        ("body_heat_source", "B1101", "H0001"),
        ("body_heat_source", "B1101", "H0002"),
        ("pump_circuit_speed", "p0102", 2900),
        ("pump_circuit_speed", "p0102", 3000),
    ),
)
def test_automatic_thermal_final_gateway_allows_only_commissioned_envelope(
    operation: str,
    target: str,
    value: bool | int | str,
) -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-1")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-1",
        session_identity="session-1",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose=(
            "solar_heating"
            if operation == "pump_circuit_speed" and value == 2900
            else "gas_heating"
            if operation == "pump_circuit_speed"
            else None
        ),
    )

    assert authority.assess(
        PhysicalCommandRequest(
            operation=operation,
            target=target,
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=value,
            automatic_thermal_context=context,
        )
    ).allowed


def test_manual_pool_off_suppression_blocks_automatic_pool_but_not_manual() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-suppressed")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-suppressed",
        session_identity="session-suppressed",
        body="pool",
        pump_circuit_id="p0199",
        operating_purpose="solar_heating",
    )
    automatic = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2900,
        automatic_thermal_context=context,
    )
    manual = PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.MANUAL,
        requested_value=True,
    )

    authority.set_pool_automatic_control_suppressed(True)

    assert authority.assess(automatic).reason is (
        PhysicalAuthorityReason.POOL_AUTOMATIC_CONTROL_SUPPRESSED
    )
    assert authority.assess(manual).allowed

    authority.set_pool_automatic_control_suppressed(False)
    assert authority.assess(automatic).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
    )


def test_manual_pool_off_suppression_is_a_final_pool_only_automatic_gate() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("thermal-epoch")
    thermal = authority.bind_automatic_thermal_dispatch(
        epoch_identity="thermal-epoch",
        session_identity="thermal-session",
        body="pool",
        pump_circuit_id="p0199",
    )
    authority.configure_automatic_filtration(enabled=True)
    authority.begin_automatic_filtration_epoch("filtration-epoch")
    filtration = authority.bind_automatic_filtration_dispatch(
        epoch_identity="filtration-epoch",
        session_identity="filtration-session",
        operation_identity="filtration-operation",
        operation="pump_circuit_speed",
        target="p0199",
        requested_value=2600,
        pump_circuit_id="p0199",
    )
    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-epoch",
        frame_identity="outage-frame",
    )
    outage_authority = authority.register_grid_outage_candidate(
        outage_epoch_id="outage-epoch",
        frame_identity="outage-frame",
        candidate_id="outage-pump",
        purpose=GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
        operation="pump_circuit_speed",
        target="p0199",
        requested_value=1500,
    )
    outage = authority.bind_grid_outage_dispatch(outage_authority)
    authority.set_pool_automatic_control_suppressed(True)

    requests = (
        PhysicalCommandRequest(
            operation="body_active",
            target="B1101",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=True,
            automatic_thermal_context=thermal,
        ),
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0199",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=2900,
            automatic_thermal_context=thermal,
        ),
        PhysicalCommandRequest(
            operation="body_heat_source",
            target="B1101",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value="H0002",
            automatic_thermal_context=thermal,
        ),
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0199",
            source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
            requested_value=2600,
            automatic_filtration_context=filtration,
        ),
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0199",
            source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
            requested_value=1500,
            grid_outage_context=outage,
        ),
    )

    assert all(
        authority.assess(item).reason
        is PhysicalAuthorityReason.POOL_AUTOMATIC_CONTROL_SUPPRESSED
        for item in requests
    )

    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("hot-tub-epoch")
    hot_tub = authority.bind_automatic_thermal_dispatch(
        epoch_identity="hot-tub-epoch",
        session_identity="hot-tub-session",
        body="hot_tub",
        pump_circuit_id="p0188",
    )
    hot_tub_request = PhysicalCommandRequest(
        operation="body_heat_source",
        target="B1202",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value="00000",
        automatic_thermal_context=hot_tub,
    )

    assert authority.assess(hot_tub_request).allowed


def test_manual_spa_off_suppression_is_a_final_spa_only_automatic_gate() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("spa-epoch")
    spa_context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="spa-epoch",
        session_identity="spa-session",
        body="hot_tub",
        pump_circuit_id="p0188",
    )
    spa_request = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0188",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2600,
        automatic_thermal_context=spa_context,
    )
    authority.set_spa_automatic_control_suppressed(True)

    assert authority.assess(spa_request).reason is (
        PhysicalAuthorityReason.SPA_AUTOMATIC_CONTROL_SUPPRESSED
    )

    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("pool-after-spa-off")
    pool_context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="pool-after-spa-off",
        session_identity="pool-session",
        body="pool",
        pump_circuit_id="p0199",
        operating_purpose="solar_heating",
    )
    pool_request = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2900,
        automatic_thermal_context=pool_context,
    )

    assert authority.assess(pool_request).allowed


def test_automatic_thermal_authority_binds_exact_recycled_pool_pmpcirc() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-dynamic-pump")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-dynamic-pump",
        session_identity="session-dynamic-pump",
        body="pool",
        pump_circuit_id="p0199",
        operating_purpose="solar_heating",
    )

    exact = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2900,
        automatic_thermal_context=context,
    )
    stale = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2900,
        automatic_thermal_context=context,
    )

    assert authority.assess(exact).allowed
    assert authority.assess(stale).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )

    with pytest.raises(ValueError, match="concrete p01xx"):
        authority.bind_automatic_thermal_dispatch(
            epoch_identity="epoch-dynamic-pump",
            session_identity="session-invalid-pump",
            body="pool",
            pump_circuit_id="other-pump",
        )


def test_pool_ordinary_circulation_authority_is_exact_purpose_and_target_bound() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("pool-ordinary-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="pool-ordinary-epoch",
        session_identity="pool-ordinary-session",
        body="pool",
        pump_circuit_id="p0199",
        operating_purpose="ordinary_circulation",
    )

    def decision(target: str, rpm: int):
        return authority.assess(
            PhysicalCommandRequest(
                operation="pump_circuit_speed",
                target=target,
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=rpm,
                automatic_thermal_context=context,
            )
        )

    assert decision("p0199", 2600).allowed
    assert not decision("p0198", 2600).allowed
    assert not decision("p0199", 1500).allowed
    assert not decision("p0199", 2900).allowed
    assert not decision("p0199", 3000).allowed


def test_startup_restraint_barrier_requires_both_restores_and_a_fresh_epoch() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.require_automatic_restraint_restoration()

    def bound_request(epoch: str) -> PhysicalCommandRequest:
        authority.begin_automatic_thermal_epoch(epoch)
        context = authority.bind_automatic_thermal_dispatch(
            epoch_identity=epoch,
            session_identity=f"session:{epoch}",
            body="pool",
            pump_circuit_id="p0199",
            operating_purpose="ordinary_circulation",
        )
        return PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0199",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=2600,
            automatic_thermal_context=context,
        )

    before_restore = bound_request("before-restore")
    assert authority.assess(before_restore).reason is (
        PhysicalAuthorityReason.AUTOMATIC_RESTRAINT_RESTORATION_PENDING
    )

    authority.resolve_pool_automatic_control_suppressed(False)
    pool_only = bound_request("pool-restored")
    assert authority.assess(pool_only).reason is (
        PhysicalAuthorityReason.AUTOMATIC_RESTRAINT_RESTORATION_PENDING
    )

    authority.resolve_spa_automatic_control_suppressed(False)
    assert authority.assess(pool_only).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
    )
    fresh = bound_request("post-restore-fresh")
    assert authority.assess(fresh).allowed


@pytest.mark.parametrize(
    ("rpm", "purpose"),
    (
        (1500, "temperature_acquisition"),
        (2600, "ordinary_circulation"),
        (2900, "solar_heating"),
        (3000, "gas_heating"),
    ),
)
def test_hot_tub_automatic_authority_is_dynamic_default_off_and_purpose_bounded(
    rpm: int,
    purpose: str,
) -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("hot-tub-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="hot-tub-epoch",
        session_identity="hot-tub-session",
        body="hot_tub",
        pump_circuit_id="p0198",
        operating_purpose=purpose,
    )

    assert authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0198",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=rpm,
            automatic_thermal_context=context,
        )
    ).allowed
    for target, value in (("p0102", rpm), ("p0198", 2816)):
        assert not authority.assess(
            PhysicalCommandRequest(
                operation="pump_circuit_speed",
                target=target,
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=value,
                automatic_thermal_context=context,
            )
        ).allowed


def test_hot_tub_normal_authority_is_disabled_without_exact_commissioning_scope() -> None:
    authority = ready()
    authority.begin_automatic_thermal_epoch("hot-tub-disabled")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="hot-tub-disabled",
        session_identity="hot-tub-session",
        body="hot_tub",
        pump_circuit_id="p0198",
        operating_purpose="ordinary_circulation",
    )

    decision = authority.assess(
        PhysicalCommandRequest(
            operation="body_active",
            target="B1202",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=True,
            automatic_thermal_context=context,
        )
    )

    assert not decision.allowed


@pytest.mark.parametrize(
    ("operation", "target", "value", "allowed"),
    (
        ("body_heat_source", "B1101", "00000", True),
        ("body_heat_source", "B1101", "H0001", False),
        ("body_heat_source", "B1101", "H0002", False),
        ("body_active", "B1101", False, False),
        ("body_active", "B1101", True, False),
        ("pump_circuit_speed", "p0102", 2900, False),
        ("pump_circuit_speed", "p0102", 2600, False),
        ("body_heat_source", "B1202", "00000", False),
    ),
)
def test_termination_context_is_final_gateway_bounded_to_pool_source_off(
    operation: str,
    target: str,
    value: bool | int | str,
    allowed: bool,
) -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("epoch-termination")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="epoch-termination",
        session_identity="termination:entitlement-1",
        body="pool",
        purpose=AutomaticThermalDispatchPurpose.TERMINATION,
    )
    decision = authority.assess(
        PhysicalCommandRequest(
            operation=operation,
            target=target,
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=value,
            automatic_thermal_context=context,
        )
    )

    assert decision.allowed is allowed


def test_hot_tub_termination_context_allows_only_exact_source_off() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("hot-tub-termination")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="hot-tub-termination",
        session_identity="termination:spa-entitlement",
        body="hot_tub",
        purpose=AutomaticThermalDispatchPurpose.TERMINATION,
    )

    def allowed(operation: str, target: str, value: object) -> bool:
        return authority.assess(
            PhysicalCommandRequest(
                operation=operation,
                target=target,
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=value,
                automatic_thermal_context=context,
            )
        ).allowed

    assert allowed("body_heat_source", "B1202", "00000")
    assert not allowed("body_heat_source", "B1202", "H0001")
    assert not allowed("body_active", "B1202", False)
    assert not allowed("body_heat_source", "B1101", "00000")


def test_hot_tub_cleanup_authority_requires_exact_registered_owned_body_off() -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="hot_tub",
    )
    authority.begin_automatic_thermal_epoch("spa-cleanup")
    authority.register_automatic_thermal_cleanup(
        epoch_identity="spa-cleanup",
        candidate_identity="spa-owned-release",
        body="hot_tub",
        purpose=AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        operation="body_active",
        target="B1202",
        requested_value=False,
    )
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="spa-cleanup",
        session_identity="cleanup:spa-provenance",
        body="hot_tub",
        purpose=AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        cleanup_candidate_identity="spa-owned-release",
    )

    exact = PhysicalCommandRequest(
        operation="body_active",
        target="B1202",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=False,
        automatic_thermal_context=context,
    )
    assert authority.assess(exact).allowed
    assert not authority.assess(
        replace(exact, target="B1101")
    ).allowed


def _cleanup_context(
    authority: PoolOSPhysicalCommandAuthority,
    *,
    purpose: AutomaticThermalDispatchPurpose,
    operation: str,
    target: str,
    value: bool | int,
) -> AutomaticThermalDispatchContext:
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("cleanup-epoch")
    candidate = f"candidate:{purpose.value}"
    authority.register_automatic_thermal_cleanup(
        epoch_identity="cleanup-epoch",
        candidate_identity=candidate,
        body="pool",
        purpose=purpose,
        operation=operation,
        target=target,
        requested_value=value,
    )
    return authority.bind_automatic_thermal_dispatch(
        epoch_identity="cleanup-epoch",
        session_identity="cleanup:provenance",
        body="pool",
        purpose=purpose,
        cleanup_candidate_identity=candidate,
    )


def _probe_context(
    authority: PoolOSPhysicalCommandAuthority,
    *,
    operation: str = "body_active",
    target: str = "B1101",
    value: bool | int | str = True,
) -> AutomaticThermalDispatchContext:
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("probe-epoch")
    authority.register_automatic_thermal_probe(
        epoch_identity="probe-epoch",
        operation_id="probe-operation",
        operation=operation,
        target=target,
        requested_value=value,
    )
    return authority.bind_automatic_thermal_dispatch(
        epoch_identity="probe-epoch",
        session_identity="probe-session",
        body="pool",
        purpose=AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE,
        probe_operation_id="probe-operation",
    )


def test_probe_authority_allows_only_exact_pool_probe_operation() -> None:
    authority = ready()
    context = _probe_context(authority)

    exact = PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=True,
        automatic_thermal_context=context,
    )
    assert authority.assess(exact).allowed

    for operation, target, value in (
        ("pump_circuit_speed", "p0102", 1501),
        ("pump_circuit_speed", "p0102", 3000),
        ("pump_circuit_speed", "p9999", 1500),
        ("pump_circuit_speed", "p0102", True),
        ("body_active", "B1101", False),
        ("body_heat_source", "B1101", "00000"),
        ("body_active", "B1202", True),
    ):
        request = PhysicalCommandRequest(
            operation=operation,
            target=target,
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=value,
            automatic_thermal_context=context,
        )
        assert authority.assess(request).reason is (
            PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
        )


@pytest.mark.parametrize(
    ("operation", "target", "value"),
    (
        ("body_active", "B1101", True),
        ("body_heat_source", "B1101", "00000"),
    ),
)
def test_probe_authority_binds_every_exact_canonical_probe_step(
    operation: str,
    target: str,
    value: bool | int | str,
) -> None:
    authority = ready()
    context = _probe_context(
        authority,
        operation=operation,
        target=target,
        value=value,
    )
    exact = PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=value,
        automatic_thermal_context=context,
    )

    assert authority.assess(exact).allowed
    assert authority.assess(replace(exact, target="B1202")).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )


def test_probe_authority_admits_only_exact_temperature_probe_pump_registration() -> None:
    authority = ready()

    context = _probe_context(
        authority,
        operation="pump_circuit_speed",
        target="p0102",
        value=1500,
    )
    exact = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=1500,
        automatic_thermal_context=context,
    )

    assert authority.assess(exact).allowed

    for value in (1499, 1501, 2600, 2900, 3000):
        with pytest.raises(
            ValueError,
            match="unsupported Pool temperature-probe operation",
        ):
            _probe_context(
                authority,
                operation="pump_circuit_speed",
                target="p0102",
                value=value,
            )

    with pytest.raises(
        ValueError,
        match="unsupported Pool temperature-probe operation",
    ):
        _probe_context(
            authority,
            operation="pump_circuit_speed",
            target="not-a-pmpcirc",
            value=1500,
        )


def test_probe_authority_rejects_retargeted_body_operation() -> None:
    authority = ready()

    with pytest.raises(ValueError, match="unsupported Pool temperature-probe operation"):
        _probe_context(authority, target="B1202")


def test_probe_authority_is_invalidated_by_new_epoch() -> None:
    authority = ready()
    context = _probe_context(authority)
    request = PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=True,
        automatic_thermal_context=context,
    )

    authority.begin_automatic_thermal_epoch("probe-newer")

    assert authority.assess(request).reason is PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE


def test_probe_authority_is_invalidated_by_new_candidate_in_same_epoch() -> None:
    authority = ready()
    context = _probe_context(authority)
    request = PhysicalCommandRequest(
        operation="body_active",
        target="B1101",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=True,
        automatic_thermal_context=context,
    )
    authority.register_automatic_thermal_probe(
        epoch_identity="probe-epoch",
        operation_id="new-probe-operation",
        operation="body_heat_source",
        target="B1101",
        requested_value="00000",
    )

    assert authority.assess(request).reason is PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE


@pytest.mark.parametrize(
    ("purpose", "operation", "target", "value"),
    (
        (
            AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
            "body_active",
            "B1101",
            False,
        ),
        (
            AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
            "pump_circuit_speed",
            "p0102",
            2475,
        ),
    ),
)
def test_cleanup_authority_allows_only_exact_epoch_bound_candidate(
    purpose: AutomaticThermalDispatchPurpose,
    operation: str,
    target: str,
    value: bool | int,
) -> None:
    authority = ready()
    context = _cleanup_context(
        authority,
        purpose=purpose,
        operation=operation,
        target=target,
        value=value,
    )
    exact = PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=value,
        automatic_thermal_context=context,
    )
    assert authority.assess(exact).allowed

    wrong_value = PhysicalCommandRequest(
        operation=operation,
        target=target,
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=(True if value is False else int(value) + 1),
        automatic_thermal_context=context,
    )
    assert authority.assess(wrong_value).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )

    authority.begin_automatic_thermal_epoch("newer-epoch")
    assert authority.assess(exact).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
    )


def test_cleanup_authority_binds_recycled_target_without_retargeting() -> None:
    authority = ready()
    context = _cleanup_context(
        authority,
        purpose=AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
        operation="pump_circuit_speed",
        target="p0199",
        value=2600,
    )

    exact = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0199",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2600,
        automatic_thermal_context=context,
    )
    stale = PhysicalCommandRequest(
        operation="pump_circuit_speed",
        target="p0102",
        source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        requested_value=2600,
        automatic_thermal_context=context,
    )

    assert authority.assess(exact).allowed
    assert authority.assess(stale).reason is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )


@pytest.mark.parametrize(
    ("purpose", "operation", "target", "value"),
    (
        (
            AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
            "body_active",
            "B1101",
            True,
        ),
        (
            AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
            "pump_circuit_speed",
            "p9999",
            2600,
        ),
        (
            AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
            "body_heat_source",
            "B1101",
            2600,
        ),
    ),
)
def test_cleanup_candidate_registration_rejects_cross_purpose_shapes(
    purpose: AutomaticThermalDispatchPurpose,
    operation: str,
    target: str,
    value: bool | int,
) -> None:
    authority = ready()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("cleanup-epoch")

    with pytest.raises(ValueError, match="cleanup authority"):
        authority.register_automatic_thermal_cleanup(
            epoch_identity="cleanup-epoch",
            candidate_identity="forged",
            body="pool",
            purpose=purpose,
            operation=operation,
            target=target,
            requested_value=value,
        )
