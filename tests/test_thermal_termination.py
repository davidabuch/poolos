from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.external_change import ExternalChangeBatch, ExternalChangeEvent
from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.thermal_live_execution import ThermalLiveExecutionContext
from poolos.thermal_runtime_ownership import (
    SharedHydraulicCircuitEvidence,
    SharedHydraulicSafetyClass,
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipEvidence,
)
from poolos.thermal_termination import (
    ThermalTerminationBodyAction,
    ThermalTerminationDisposition,
    ThermalTerminationPolicy,
    ThermalTerminationPumpAction,
    ThermalTerminationSourceAction,
)


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _provenance(
    concept: ThermalRuntimeOwnedConcept,
    value: bool | int | PhysicalHeatMode,
) -> ThermalRuntimeConceptProvenance:
    return ThermalRuntimeConceptProvenance(
        concept=concept,
        operation_id=f"operation:{concept.value}",
        receipt_id=f"receipt:{concept.value}",
        correlation_id=f"correlation:{concept.value}",
        intended_value=value,
    )


def _entitlement(
    *,
    body_owned: bool = True,
    pump_owned: bool = True,
    source: PhysicalHeatMode | None = PhysicalHeatMode.SOLAR,
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalResidualTerminationEntitlement:
    return ThermalResidualTerminationEntitlement(
        entitlement_id="entitlement-1",
        lease_id="lease-1",
        generation=1,
        body=body,
        originating_execution_plan_id="execution-plan-1",
        originating_lease_established_at=NOW - timedelta(seconds=1),
        retained_at=NOW,
        reason_code="runtime_ownership_superseded:execution_purpose",
        body_activation=(
            _provenance(ThermalRuntimeOwnedConcept.BODY_ACTIVATION, True)
            if body_owned
            else None
        ),
        pump_setpoint=(
            _provenance(ThermalRuntimeOwnedConcept.PUMP_SETPOINT, 2900)
            if pump_owned
            else None
        ),
        heat_source=(
            None
            if source is None
            else _provenance(ThermalRuntimeOwnedConcept.HEAT_SOURCE, source)
        ),
    )


def _evidence(
    *,
    source: PhysicalHeatMode = PhysicalHeatMode.SOLAR,
    pool_active: bool | None = True,
    spa_active: bool | None = False,
    changes: ExternalChangeBatch = ExternalChangeBatch(()),
    fresh: bool = True,
    usable: bool = True,
    pump_rpm: int = 2900,
    configured_rpm: int = 2900,
    source_observed_at: datetime | None = None,
) -> ThermalRuntimeOwnershipEvidence:
    circuits = tuple(
        SharedHydraulicCircuitEvidence(
            concept=concept,
            active=False,
            fresh=True,
            usable=True,
            safety_class=SharedHydraulicSafetyClass.CONFLICTING,
        )
        for concept in ("waterfall.active", "jets.active", "slide.active")
    )
    return ThermalRuntimeOwnershipEvidence(
        evaluated_at=NOW + timedelta(seconds=1),
        current_context=ThermalLiveExecutionContext("evaluation-2", "plan-2"),
        requested_mode="Off",
        pool_active=pool_active,
        spa_active=spa_active,
        pool_activity_fresh=fresh,
        spa_activity_fresh=fresh,
        pool_activity_usable=usable,
        spa_activity_usable=usable,
        pump_rpm=pump_rpm,
        pump_observation_fresh=True,
        pump_observation_usable=True,
        configured_pump_speed_rpm=configured_rpm,
        configured_pump_speed_observation_fresh=True,
        configured_pump_speed_observation_usable=True,
        effective_heat_source=source,
        heat_source_observation_fresh=True,
        heat_source_observation_usable=True,
        heat_source_observed_at=source_observed_at,
        external_changes=changes,
        shared_hydraulic_circuits=circuits,
        shared_hydraulic_inventory_complete=True,
    )


def test_owned_pool_source_off_is_the_only_physical_termination_action() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.source_action is ThermalTerminationSourceAction.SET_OFF
    assert result.pump_action is ThermalTerminationPumpAction.RELINQUISH
    assert result.body_action is ThermalTerminationBodyAction.KEEP_ACTIVE
    assert result.successor_owner == "filtration"
    assert result.operation is not None
    assert result.operation.mode is PhysicalHeatMode.OFF
    assert result.operation.equipment_id == ThermalBody.POOL.value
    assert result.monotonic


def test_preexisting_body_is_never_claimed_or_deactivated() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(body_owned=False),
        _evidence(),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.body_action is ThermalTerminationBodyAction.NONE
    assert result.operation is not None


def test_current_policy_requiring_heat_relinquishes_without_source_off() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(),
        desired_source=PhysicalHeatMode.GAS,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.operation is None


def test_already_off_needs_no_command() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(source=PhysicalHeatMode.OFF),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.source_action is ThermalTerminationSourceAction.ALREADY_OFF
    assert result.operation is None


def test_external_source_takeover_invalidates_stale_cleanup() -> None:
    event = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="H0002",
        new_value="H0001",
        observed_at=NOW + timedelta(milliseconds=1),
        external_policy="reconcile",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=True,
    )
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(changes=ExternalChangeBatch((event,))),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.INVALIDATED
    assert result.operation is None


def test_hydraulic_takeover_and_unusable_evidence_fail_closed() -> None:
    policy = ThermalTerminationPolicy()

    spa = policy.evaluate(
        _entitlement(),
        _evidence(pool_active=False, spa_active=True),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )
    stale = policy.evaluate(
        _entitlement(),
        _evidence(fresh=False),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert spa.disposition is ThermalTerminationDisposition.INVALIDATED
    assert stale.disposition is ThermalTerminationDisposition.INVALIDATED
    assert spa.operation is None
    assert stale.operation is None


def test_external_pump_takeover_invalidates_source_cleanup_too() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(),
        _evidence(pump_rpm=2600, configured_rpm=2600),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.INVALIDATED
    assert result.reason_code == "thermal_termination_pump_external_takeover"
    assert result.operation is None


def test_hot_tub_residual_does_not_expand_automatic_authority() -> None:
    result = ThermalTerminationPolicy().evaluate(
        _entitlement(body=ThermalBody.HOT_TUB),
        _evidence(pool_active=False, spa_active=True),
        desired_source=PhysicalHeatMode.OFF,
        filtration_remaining=None,
    )

    assert result.disposition is ThermalTerminationDisposition.BLOCKED
    assert result.reason_code == "thermal_termination_hot_tub_not_commissioned"
    assert result.operation is None
