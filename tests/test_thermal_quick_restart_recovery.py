from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import pytest

from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.thermal_execution_currentness import ThermalExecutionCurrentness, ThermalExecutionProgress
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipDisposition,
    ThermalRuntimeOwnershipManager,
    ThermalRuntimeOwnershipStatus,
)
from poolos.thermal_live_execution import ThermalLiveExecutionContext, ThermalLiveExecutionOwnership

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





def _stable_verified_hot_tub_solar_manager() -> ThermalRuntimeOwnershipManager:
    """Return a fully verified PoolOS-started Hot Tub Solar lease."""

    accepted_base = NOW - timedelta(seconds=10)
    assessment = thermal_assessment(
        at=accepted_base,
        body=ThermalBody.HOT_TUB,
        requested_mode="Solar Preferred",
        source=PhysicalHeatMode.SOLAR,
        rpm=2900,
        current_source=PhysicalHeatMode.OFF,
        current_rpm=0,
        current_body_active=False,
    )
    currentness = ThermalExecutionCurrentness.from_assessment(
        assessment,
        evaluation_id="hot-tub-evaluation",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        assessment.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = ThermalLiveExecutionOwnership(
        evaluation_id=currentness.evaluation_id,
        thermal_plan_id=assessment.plan_id,
        execution_plan_id="hot-tub-execution-plan",
        target_body=ThermalBody.HOT_TUB,
    )

    values = (
        (
            0,
            {
                "body": ThermalBody.HOT_TUB,
                "pool_active": False,
                "spa_active": True,
                "spa_observed_at": accepted_base + timedelta(seconds=1),
                "pool_observed_at": accepted_base + timedelta(seconds=1),
            },
        ),
        (
            1,
            {
                "body": ThermalBody.HOT_TUB,
                "pool_active": False,
                "spa_active": True,
                "pump_rpm": 3000,
                "configured_pump_rpm": 3000,
                "pump_observed_at": accepted_base + timedelta(seconds=3),
                "configured_pump_observed_at": accepted_base + timedelta(seconds=3),
                "spa_observed_at": accepted_base + timedelta(seconds=3),
                "pool_observed_at": accepted_base + timedelta(seconds=3),
            },
        ),
        (
            2,
            {
                "body": ThermalBody.HOT_TUB,
                "pool_active": False,
                "spa_active": True,
                "pump_rpm": 2900,
                "configured_pump_rpm": 2900,
                "pump_observed_at": accepted_base + timedelta(seconds=5),
                "configured_pump_observed_at": accepted_base + timedelta(seconds=5),
                "spa_observed_at": accepted_base + timedelta(seconds=5),
                "pool_observed_at": accepted_base + timedelta(seconds=5),
            },
        ),
        (
            3,
            {
                "body": ThermalBody.HOT_TUB,
                "pool_active": False,
                "spa_active": True,
                "heat_source": PhysicalHeatMode.SOLAR,
                "source_observed_at": accepted_base + timedelta(seconds=7),
                "spa_observed_at": accepted_base + timedelta(seconds=7),
                "pool_observed_at": accepted_base + timedelta(seconds=7),
            },
        ),
    )

    verified_prefix = ()
    for offset, (index, evidence_values) in enumerate(values):
        operation = assessment.operations[index]
        accepted_at = accepted_base + timedelta(seconds=offset * 2)
        if index == 0:
            ownership = replace(
                ownership,
                body_activation_operation_id=operation.operation_id,
                body_activation_receipt_id="hot-tub-body-receipt",
                body_activation_correlation_id="hot-tub-body-correlation",
                body_activation_accepted_at=accepted_at,
            )
        elif index in {1, 2}:
            ownership = replace(
                ownership,
                pump_operation_id=operation.operation_id,
                pump_receipt_id=f"hot-tub-pump-receipt-{index}",
                pump_correlation_id=f"hot-tub-pump-correlation-{index}",
                commanded_pump_rpm=3000 if index == 1 else 2900,
                pump_accepted_at=accepted_at,
            )
        else:
            ownership = replace(
                ownership,
                heat_source_operation_id=operation.operation_id,
                heat_source_receipt_id="hot-tub-source-receipt",
                heat_source_correlation_id="hot-tub-source-correlation",
                commanded_heat_source=PhysicalHeatMode.SOLAR,
                heat_source_accepted_at=accepted_at,
            )

        decision = manager.promote_session_provenance(
            ownership,
            promoted_at=accepted_at,
            requested_mode="Solar Preferred",
            originating_context=context,
            execution_progress=ThermalExecutionProgress(
                verified_prefix=verified_prefix,
                accepted_current=currentness.residual_plan.operations[index],
                accepted_operation_id=operation.operation_id,
            ),
        )
        assert decision.current_state.status is ThermalRuntimeOwnershipStatus.OWNED
        manager.evaluate(
            evidence(
                at=accepted_at + timedelta(seconds=1),
                evaluation_id=currentness.evaluation_id,
                plan_id=assessment.plan_id,
                requested_mode="Solar Preferred",
                execution_currentness=currentness,
                **evidence_values,
            )
        )
        verified_prefix = currentness.residual_plan.operations[: index + 1]

    lease = manager.state.lease
    assert lease is not None
    assert set(lease.verified_concepts) == {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE,
    }

    # Match the Pool quick-restart contract: checkpoint export is allowed only
    # after one later clean steady-state epoch has reconfirmed every owned
    # domain as stable PoolOS authority.
    stable_at = NOW + timedelta(seconds=10)
    stable = manager.evaluate(
        evidence(
            body=ThermalBody.HOT_TUB,
            at=stable_at,
            evaluation_id=currentness.evaluation_id,
            plan_id=assessment.plan_id,
            requested_mode="Solar Preferred",
            pool_active=False,
            spa_active=True,
            pump_rpm=2900,
            configured_pump_rpm=2900,
            heat_source=PhysicalHeatMode.SOLAR,
            execution_currentness=currentness,
            pool_observed_at=stable_at,
            spa_observed_at=stable_at,
            pump_observed_at=stable_at,
            configured_pump_observed_at=stable_at,
            source_observed_at=stable_at,
        )
    )
    assert stable.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    return manager


def _fresh_matching_hot_tub_evidence(
    source: ThermalRuntimeOwnershipManager,
    *,
    at,
    pool_active: bool = False,
    spa_active: bool = True,
):
    lease = source.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None
    currentness = replace(
        lease.originating_currentness,
        evaluation_id="hot-tub-restart-evaluation",
        plan_id="hot-tub-restart-plan",
        evaluated_at=at,
    )
    return evidence(
        body=ThermalBody.HOT_TUB,
        at=at,
        evaluation_id=currentness.evaluation_id,
        plan_id=currentness.plan_id,
        requested_mode=lease.requested_mode,
        pool_active=pool_active,
        spa_active=spa_active,
        pump_rpm=2900,
        configured_pump_rpm=2900,
        heat_source=PhysicalHeatMode.SOLAR,
        execution_currentness=currentness,
        pool_observed_at=at,
        spa_observed_at=at,
        pump_observed_at=at,
        configured_pump_observed_at=at,
        source_observed_at=at,
    )


def test_fully_verified_hot_tub_solar_session_exports_restart_checkpoint() -> None:
    manager = _stable_verified_hot_tub_solar_manager()

    checkpoint = manager.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )

    assert checkpoint is not None
    assert checkpoint.body is ThermalBody.HOT_TUB
    assert checkpoint.body_activation.intended_value is True
    assert checkpoint.pump_setpoint.intended_value == 2900
    assert checkpoint.heat_source.intended_value is PhysicalHeatMode.SOLAR


def test_matching_fresh_hot_tub_restart_restores_same_provenance() -> None:
    before = _stable_verified_hot_tub_solar_manager()
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
        evidence=_fresh_matching_hot_tub_evidence(before, at=at),
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    lease = restarted.state.lease
    assert lease is not None
    assert lease.body is ThermalBody.HOT_TUB
    assert lease.body_activation == old_lease.body_activation
    assert lease.pump_setpoint == old_lease.pump_setpoint
    assert lease.heat_source == old_lease.heat_source
    assert lease.reason_code == "runtime_ownership_restored:quick_restart"


def test_hot_tub_restart_topology_mismatch_fails_closed() -> None:
    before = _stable_verified_hot_tub_solar_manager()
    checkpoint = before.export_restart_checkpoint(
        captured_at=NOW + timedelta(seconds=11)
    )
    assert checkpoint is not None

    restarted = ThermalRuntimeOwnershipManager()
    at = NOW + timedelta(seconds=40)
    decision = restarted.restore_restart_checkpoint(
        checkpoint,
        evidence=_fresh_matching_hot_tub_evidence(
            before,
            at=at,
            pool_active=True,
            spa_active=True,
        ),
        max_age=timedelta(minutes=5),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED

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


@pytest.mark.parametrize("invalid", ["configured_stale", "configured_old", "configured_mismatch", "shared_incomplete", "shared_stale", "shared_active", "shared_old", "body_future", "pump_future"])
def test_restart_requires_current_configured_pump_and_shared_topology(invalid) -> None:
    from poolos.thermal_runtime_ownership import SharedHydraulicCircuitEvidence, SharedHydraulicSafetyClass

    before = _stable_verified_solar_manager()
    checkpoint = before.export_restart_checkpoint(captured_at=NOW + timedelta(seconds=11))
    current = _fresh_matching_evidence(before, at=NOW + timedelta(seconds=40))
    changes = {
        "configured_stale": {"configured_pump_speed_observation_fresh": False},
        "configured_old": {"configured_pump_speed_observed_at": checkpoint.captured_at},
        "configured_mismatch": {"configured_pump_speed_rpm": 3200},
        "shared_incomplete": {"shared_hydraulic_inventory_complete": False},
        "body_future": {"pool_activity_observed_at": current.evaluated_at + timedelta(seconds=1)},
        "pump_future": {"pump_observed_at": current.evaluated_at + timedelta(seconds=1)},
    }
    if invalid.startswith("shared_") and invalid != "shared_incomplete":
        circuit = SharedHydraulicCircuitEvidence(
            concept="jets.active", active=invalid == "shared_active",
            fresh=invalid != "shared_stale", usable=True,
            observed_at=checkpoint.captured_at if invalid == "shared_old" else current.evaluated_at,
            safety_class=SharedHydraulicSafetyClass.CONFLICTING,
        )
        changes[invalid] = {"shared_hydraulic_circuits": (circuit,)}
    restarted = ThermalRuntimeOwnershipManager()
    decision = restarted.restore_restart_checkpoint(checkpoint, evidence=replace(current, **changes[invalid]), max_age=timedelta(minutes=5))
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
