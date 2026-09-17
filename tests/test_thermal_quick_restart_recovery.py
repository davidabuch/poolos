from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from poolos.integration import PhysicalHeatMode
from poolos.thermal_execution_currentness import ThermalExecutionCurrentness
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipDisposition,
    ThermalRuntimeOwnershipManager,
    ThermalRuntimeOwnershipStatus,
)

from test_thermal_runtime_ownership import (
    NOW,
    evidence,
    establish,
    execution_ownership,
    thermal_assessment,
    verified_full_manager,
)


def _stable_verified_solar_manager() -> ThermalRuntimeOwnershipManager:
    """Return a fully verified Solar lease after one clean steady-state epoch."""

    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None
    assert lease.heat_source is not None

    at = NOW + timedelta(seconds=10)

    decision = manager.evaluate(
        evidence(
            at=at,
            evaluation_id=lease.originating_currentness.evaluation_id,
            plan_id=lease.originating_currentness.plan_id,
            requested_mode=lease.requested_mode,
            pool_active=True,
            spa_active=False,
            pump_rpm=2900,
            configured_pump_rpm=2900,
            heat_source=PhysicalHeatMode.SOLAR,
            execution_currentness=lease.originating_currentness,
            pool_observed_at=at,
            spa_observed_at=at,
            pump_observed_at=at,
            configured_pump_observed_at=at,
            source_observed_at=at,
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    return manager


def _fresh_matching_evidence(
    source: ThermalRuntimeOwnershipManager,
    *,
    at,
    pump_rpm: int = 2900,
    heat_source: PhysicalHeatMode = PhysicalHeatMode.SOLAR,
):
    lease = source.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None

    currentness = replace(
        lease.originating_currentness,
        evaluation_id="restart-evaluation",
        plan_id="restart-plan",
        evaluated_at=at,
    )

    return evidence(
        at=at,
        evaluation_id=currentness.evaluation_id,
        plan_id=currentness.plan_id,
        requested_mode=lease.requested_mode,
        pool_active=True,
        spa_active=False,
        pump_rpm=pump_rpm,
        configured_pump_rpm=2900,
        heat_source=heat_source,
        execution_currentness=currentness,
        pool_observed_at=at,
        spa_observed_at=at,
        pump_observed_at=at,
        configured_pump_observed_at=at,
        source_observed_at=at,
    )


def test_fully_verified_solar_session_exports_restart_checkpoint() -> None:
    manager = _stable_verified_solar_manager()

    checkpoint = manager.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )

    assert checkpoint is not None
    assert checkpoint.body.value == "pool"
    assert checkpoint.purpose_id
    assert checkpoint.body_activation is not None
    assert checkpoint.pump_setpoint is not None
    assert checkpoint.heat_source is not None
    assert checkpoint.pump_setpoint.intended_value == 2900
    assert checkpoint.heat_source.intended_value is PhysicalHeatMode.SOLAR
    assert set(checkpoint.verified_concepts) == {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE,
    }


def test_matching_fresh_restart_restores_same_provenance_without_new_delivery() -> None:
    before = _stable_verified_solar_manager()
    old_lease = before.state.lease
    assert old_lease is not None

    checkpoint = before.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )
    assert checkpoint is not None

    restarted = ThermalRuntimeOwnershipManager()
    at = NOW + timedelta(seconds=40)

    decision = restarted.restore_restart_checkpoint(
        checkpoint,
        evidence=_fresh_matching_evidence(before, at=at),
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.OWNED

    lease = restarted.state.lease
    assert lease is not None

    # This is continuation of the exact prior PoolOS session, not adoption from
    # physical equality and not a new command generation.
    assert lease.lease_id == old_lease.lease_id
    assert lease.generation == old_lease.generation
    assert lease.body_session_id == old_lease.body_session_id
    assert lease.body_session_generation == old_lease.body_session_generation

    assert lease.body_activation == old_lease.body_activation
    assert lease.pump_setpoint == old_lease.pump_setpoint
    assert lease.heat_source == old_lease.heat_source

    assert set(lease.verified_concepts) == {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE,
    }

    assert lease.originating_currentness is not None
    assert (
        lease.originating_currentness.purpose.purpose_id
        == checkpoint.purpose_id
    )
    assert lease.reason_code == "runtime_ownership_restored:quick_restart"


def test_stale_restart_checkpoint_fails_closed() -> None:
    before = _stable_verified_solar_manager()
    checkpoint = before.export_restart_checkpoint(captured_at=NOW + timedelta(seconds=11))
    assert checkpoint is not None

    restarted = ThermalRuntimeOwnershipManager()
    at = NOW + timedelta(minutes=6, seconds=12)

    decision = restarted.restore_restart_checkpoint(
        checkpoint,
        evidence=_fresh_matching_evidence(before, at=at),
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_changed_semantic_purpose_fails_closed() -> None:
    before = _stable_verified_solar_manager()
    lease = before.state.lease
    assert lease is not None

    checkpoint = before.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )
    assert checkpoint is not None

    at = NOW + timedelta(seconds=40)

    changed = ThermalExecutionCurrentness.from_assessment(
        thermal_assessment(
            at=at,
            requested_mode="different-purpose",
            source=PhysicalHeatMode.SOLAR,
            rpm=2900,
            current_source=PhysicalHeatMode.SOLAR,
            current_rpm=2900,
            current_body_active=True,
        ),
        evaluation_id="restart-different-evaluation",
    )

    changed_evidence = evidence(
        at=at,
        evaluation_id=changed.evaluation_id,
        plan_id=changed.plan_id,
        requested_mode="different-purpose",
        pool_active=True,
        spa_active=False,
        pump_rpm=2900,
        configured_pump_rpm=2900,
        heat_source=PhysicalHeatMode.SOLAR,
        execution_currentness=changed,
        pool_observed_at=at,
        spa_observed_at=at,
        pump_observed_at=at,
        configured_pump_observed_at=at,
        source_observed_at=at,
    )

    restarted = ThermalRuntimeOwnershipManager()
    decision = restarted.restore_restart_checkpoint(
        checkpoint,
        evidence=changed_evidence,
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_restart_hardware_mismatch_fails_closed() -> None:
    before = _stable_verified_solar_manager()
    checkpoint = before.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )
    assert checkpoint is not None

    restarted = ThermalRuntimeOwnershipManager()
    at = NOW + timedelta(seconds=40)

    decision = restarted.restore_restart_checkpoint(
        checkpoint,
        evidence=_fresh_matching_evidence(
            before,
            at=at,
            pump_rpm=2600,
        ),
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_partial_or_unverified_session_cannot_create_restart_checkpoint() -> None:
    manager = ThermalRuntimeOwnershipManager()

    establish(
        manager,
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
        ),
    )

    # Accepted receipts exist, but their native consequences have not yet been
    # authoritatively verified. Restart persistence must not widen that into
    # recoverable ownership.
    checkpoint = manager.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=1)
    )

    assert checkpoint is None


def test_restart_checkpoint_restore_state_round_trip() -> None:
    manager = _stable_verified_solar_manager()
    lease = manager.state.lease
    assert lease is not None

    checkpoint = manager.export_restart_checkpoint(
        captured_at=lease.last_confirmed_at
    )
    assert checkpoint is not None

    payload = checkpoint.to_restore_state()
    restored = type(checkpoint).from_restore_state(payload)

    assert restored.lease_id == checkpoint.lease_id
    assert restored.generation == checkpoint.generation
    assert restored.body == checkpoint.body
    assert restored.purpose_id == checkpoint.purpose_id
    assert restored.execution_plan_id == checkpoint.execution_plan_id
    assert restored.body_activation == checkpoint.body_activation
    assert restored.pump_setpoint == checkpoint.pump_setpoint
    assert restored.heat_source == checkpoint.heat_source
    assert restored.body_session_id == checkpoint.body_session_id
    assert (
        restored.body_session_generation
        == checkpoint.body_session_generation
    )


def test_restart_checkpoint_restore_state_rejects_wrong_schema() -> None:
    manager = _stable_verified_solar_manager()
    lease = manager.state.lease
    assert lease is not None

    checkpoint = manager.export_restart_checkpoint(
        captured_at=lease.last_confirmed_at
    )
    assert checkpoint is not None

    payload = checkpoint.to_restore_state()
    payload["schema"] = 999

    try:
        type(checkpoint).from_restore_state(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid restore schema was accepted")
