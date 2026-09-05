from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from poolos.physical_command_authority import (
    AutomaticThermalDispatchContext,
    ExpectedNativeConsequence,
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
