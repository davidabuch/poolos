from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.physical_command_authority import (
    NativeConsequenceAttribution,
    PhysicalRequestSource,
)
from poolos.pump_speed_session import PumpSpeedOverrideState, PumpSpeedSessionPurpose
from poolos.thermal_execution_currentness import (
    ThermalExecutionCurrentness,
    ThermalExecutionProgress,
    operation_signature,
)
from poolos.thermal_execution_planning import (
    ThermalCurrentState,
    ThermalDesiredState,
    ThermalExecutionPlanAssessment,
    ThermalExecutionPlanBuilder,
)
from poolos.thermal_live_execution import (
    ThermalLiveExecutionContext,
    ThermalLiveExecutionOwnership,
)
from poolos.thermal_runtime_ownership import (
    SharedHydraulicCircuitEvidence,
    SharedHydraulicSafetyClass,
    ThermalRuntimeHandoffRequest,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipDisposition,
    ThermalRuntimeOwnershipEvidence,
    ThermalRuntimeOwnershipManager,
    ThermalRuntimeOwnershipStatus,
    shared_hydraulic_safety_class,
)


NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
_UNSET = object()


def execution_ownership(
    *,
    body: ThermalBody = ThermalBody.POOL,
    activation: bool = False,
    pump_rpm: int | None = None,
    source: PhysicalHeatMode | None = None,
    evaluation_id: str = "evaluation-1",
    plan_id: str = "plan-1",
    execution_plan_id: str = "execution-plan-1",
) -> ThermalLiveExecutionOwnership:
    prefix = body.value
    return ThermalLiveExecutionOwnership(
        evaluation_id=evaluation_id,
        thermal_plan_id=plan_id,
        execution_plan_id=execution_plan_id,
        target_body=body,
        body_activation_operation_id=(f"{prefix}-body-op" if activation else None),
        body_activation_receipt_id=(f"{prefix}-body-receipt" if activation else None),
        body_activation_correlation_id=(f"{prefix}-body-correlation" if activation else None),
        pump_operation_id=(f"{prefix}-pump-op" if pump_rpm is not None else None),
        pump_receipt_id=(f"{prefix}-pump-receipt" if pump_rpm is not None else None),
        pump_correlation_id=(
            f"{prefix}-pump-correlation" if pump_rpm is not None else None
        ),
        commanded_pump_rpm=pump_rpm,
        heat_source_operation_id=(f"{prefix}-source-op" if source is not None else None),
        heat_source_receipt_id=(
            f"{prefix}-source-receipt" if source is not None else None
        ),
        heat_source_correlation_id=(
            f"{prefix}-source-correlation" if source is not None else None
        ),
        commanded_heat_source=source,
    )


def evidence(
    *,
    body: ThermalBody = ThermalBody.POOL,
    at: datetime = NOW,
    evaluation_id: str = "evaluation-1",
    plan_id: str = "plan-1",
    requested_mode: str = "Solar",
    pool_active: bool | None | object = _UNSET,
    spa_active: bool | None | object = _UNSET,
    pool_fresh: bool = True,
    spa_fresh: bool = True,
    pool_usable: bool = True,
    spa_usable: bool = True,
    pump_rpm: int | None = 2900,
    pump_fresh: bool = True,
    pump_usable: bool = True,
    configured_pump_rpm: int | None = 2900,
    configured_pump_fresh: bool = True,
    configured_pump_usable: bool = True,
    heat_source: PhysicalHeatMode | None = PhysicalHeatMode.SOLAR,
    source_fresh: bool = True,
    source_usable: bool = True,
    changes: ExternalChangeBatch = ExternalChangeBatch(()),
    circuits: tuple[SharedHydraulicCircuitEvidence, ...] = (),
    circuit_inventory_complete: bool = True,
    execution_currentness: ThermalExecutionCurrentness | None = None,
    pool_observed_at: datetime | None = None,
    spa_observed_at: datetime | None = None,
    pump_observed_at: datetime | None = None,
    configured_pump_observed_at: datetime | None = None,
    source_observed_at: datetime | None = None,
    pump_session_id: str | None = None,
    pump_session_purpose: PumpSpeedSessionPurpose | None = None,
    pump_session_pump_circuit_id: str | None = None,
    pump_session_effective_rpm: int | None = None,
    pump_session_override_state: PumpSpeedOverrideState = PumpSpeedOverrideState.NONE,
) -> ThermalRuntimeOwnershipEvidence:
    if pool_active is _UNSET:
        pool_active = body is ThermalBody.POOL
    if spa_active is _UNSET:
        spa_active = body is ThermalBody.HOT_TUB
    assert isinstance(pool_active, bool) or pool_active is None
    assert isinstance(spa_active, bool) or spa_active is None
    return ThermalRuntimeOwnershipEvidence(
        evaluated_at=at,
        current_context=ThermalLiveExecutionContext(
            evaluation_id,
            plan_id,
            execution_currentness,
        ),
        requested_mode=requested_mode,
        pool_active=pool_active,
        spa_active=spa_active,
        pool_activity_fresh=pool_fresh,
        spa_activity_fresh=spa_fresh,
        pool_activity_usable=pool_usable,
        spa_activity_usable=spa_usable,
        pump_rpm=pump_rpm,
        pump_observation_fresh=pump_fresh,
        pump_observation_usable=pump_usable,
        configured_pump_speed_rpm=configured_pump_rpm,
        configured_pump_speed_observation_fresh=configured_pump_fresh,
        configured_pump_speed_observation_usable=configured_pump_usable,
        effective_heat_source=heat_source,
        heat_source_observation_fresh=source_fresh,
        heat_source_observation_usable=source_usable,
        external_changes=changes,
        shared_hydraulic_circuits=circuits,
        shared_hydraulic_inventory_complete=circuit_inventory_complete,
        pool_activity_observed_at=pool_observed_at,
        spa_activity_observed_at=spa_observed_at,
        pump_observed_at=pump_observed_at,
        configured_pump_speed_observed_at=configured_pump_observed_at,
        heat_source_observed_at=source_observed_at,
        pump_session_id=pump_session_id,
        pump_session_purpose=pump_session_purpose,
        pump_session_pump_circuit_id=pump_session_pump_circuit_id,
        pump_session_effective_rpm=pump_session_effective_rpm,
        pump_session_override_state=pump_session_override_state,
    )


def establish(
    manager: ThermalRuntimeOwnershipManager,
    ownership: ThermalLiveExecutionOwnership,
    *,
    requested_mode: str = "Solar",
) -> None:
    decision = manager.establish(
        ownership,
        established_at=NOW,
        requested_mode=requested_mode,
        current_context=ThermalLiveExecutionContext(
            ownership.evaluation_id,
            ownership.thermal_plan_id,
        ),
    )
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED


def external_event(
    concept: str,
    previous: object,
    new: object,
    *,
    reconciliation_required: bool = True,
    observed_at: datetime | None = None,
) -> ExternalChangeEvent:
    return ExternalChangeEvent(
        concept=concept,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="native-object",
        previous_value=previous,
        new_value=new,
        observed_at=(NOW + timedelta(seconds=1) if observed_at is None else observed_at),
        external_policy=ExternalChangePolicy.RECONCILE,
        action_taken="reconciliation_required",
        notification_recommended=True,
        reconciliation_required=reconciliation_required,
    )


def attribution(operation: str) -> NativeConsequenceAttribution:
    return NativeConsequenceAttribution(
        expectation_id=f"expect-{operation}",
        request_id=f"request-{operation}",
        request_source=PhysicalRequestSource.AUTONOMOUS,
        operation=operation,
        target="native-object",
    )


def thermal_assessment(
    *,
    at: datetime = NOW,
    body: ThermalBody = ThermalBody.POOL,
    requested_mode: str = "solar",
    source: PhysicalHeatMode = PhysicalHeatMode.SOLAR,
    rpm: int = 2900,
    current_source: PhysicalHeatMode = PhysicalHeatMode.OFF,
    current_rpm: int = 2600,
    current_body_active: bool = True,
) -> ThermalExecutionPlanAssessment:
    return ThermalExecutionPlanBuilder(
        pump_equipment_id="p0102" if body is ThermalBody.POOL else "p0198"
    ).build(
        ThermalDesiredState(
            evaluated_at=at,
            body=body,
            requested_mode=requested_mode,
            selected_source=source,
            required_pump_rpm=rpm,
            reason_code=f"selected_{source.value}",
            rpm_reason_code=f"baseline:{rpm}",
            rationale=("Current thermal objective.",),
            criteria=("authoritative_evidence",),
            evidence={"pool_target_f": 90.0},
        ),
        ThermalCurrentState(
            observed_at=at,
            body=body,
            selected_source=current_source,
            pump_rpm=current_rpm,
            body_active=current_body_active,
        ),
    )


@pytest.mark.parametrize("body", (ThermalBody.POOL, ThermalBody.HOT_TUB))
def test_preexisting_or_matching_native_state_does_not_create_ownership(
    body: ThermalBody,
) -> None:
    manager = ThermalRuntimeOwnershipManager()

    decision = manager.evaluate(evidence(body=body))

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_empty_authorized_but_undelivered_provenance_cannot_establish() -> None:
    manager = ThermalRuntimeOwnershipManager()

    decision = manager.establish(
        execution_ownership(),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext("evaluation-1", "plan-1"),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


@pytest.mark.parametrize(
    ("ownership", "owned", "unowned"),
    (
        (execution_ownership(activation=True), "body_activation", ("pump_setpoint", "heat_source")),
        (execution_ownership(pump_rpm=2900), "pump_setpoint", ("body_activation", "heat_source")),
        (
            execution_ownership(source=PhysicalHeatMode.SOLAR),
            "heat_source",
            ("body_activation", "pump_setpoint"),
        ),
        (
            execution_ownership(
                body=ThermalBody.HOT_TUB,
                activation=True,
                evaluation_id="evaluation-1",
                plan_id="plan-1",
            ),
            "body_activation",
            ("pump_setpoint", "heat_source"),
        ),
    ),
)
def test_accepted_execution_provenance_establishes_only_its_exact_concepts(
    ownership: ThermalLiveExecutionOwnership,
    owned: str,
    unowned: tuple[str, ...],
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, ownership)

    lease = manager.state.lease
    assert lease is not None
    assert getattr(lease, owned) is not None
    assert all(getattr(lease, concept) is None for concept in unowned)


def test_full_execution_provenance_is_eligible_for_runtime_ownership() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
        ),
    )

    lease = manager.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert lease.owns_pump_setpoint
    assert lease.owns_heat_source


@pytest.mark.parametrize("operation", ("body_active", "pump_speed", "body_heat_source"))
def test_exact_expected_poolos_consequence_does_not_self_preempt(operation: str) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
        ),
    )
    batch = ExternalChangeBatch((), (attribution(operation),))

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), changes=batch)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED


def test_prelease_external_event_cannot_preempt_new_lease() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    batch = ExternalChangeBatch(
        (
            external_event(
                "pump.rpm",
                2600,
                2900,
                observed_at=NOW - timedelta(microseconds=1),
            ),
        )
    )

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), changes=batch)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1)])
def test_external_event_at_or_after_lease_start_still_preempts(
    offset: timedelta,
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    batch = ExternalChangeBatch(
        (
            external_event(
                "pump.rpm",
                2600,
                2900,
                observed_at=NOW + offset,
            ),
        )
    )

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), changes=batch)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED


def test_duplicate_postlease_event_cannot_mutate_terminal_ownership_twice() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    event = external_event("pump.rpm", 2600, 2900, observed_at=NOW)
    batch = ExternalChangeBatch((event,))

    first = manager.evaluate(evidence(at=NOW + timedelta(seconds=1), changes=batch))
    duplicate = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=2), changes=batch)
    )

    assert first.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert duplicate.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.PREEMPTED


def test_old_event_cannot_preempt_successor_lease_after_prior_preemption() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    event = external_event(
        "pump.rpm",
        2900,
        2600,
        observed_at=NOW + timedelta(seconds=1),
    )
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            pump_rpm=2600,
            changes=ExternalChangeBatch((event,)),
        )
    )
    successor = execution_ownership(
        pump_rpm=2900,
        evaluation_id="evaluation-2",
        plan_id="plan-2",
        execution_plan_id="execution-plan-2",
    )
    decision = manager.establish(
        successor,
        established_at=NOW + timedelta(seconds=2),
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext("evaluation-2", "plan-2"),
    )
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED

    retained = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=3),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
            changes=ExternalChangeBatch((event,)),
        )
    )

    assert retained.disposition is ThermalRuntimeOwnershipDisposition.RETAINED


@pytest.mark.parametrize(
    ("body", "changes", "kwargs", "reason"),
    (
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_active": False},
            "runtime_ownership_preempted:pool_inactive",
        ),
        (
            ThermalBody.HOT_TUB,
            ExternalChangeBatch(()),
            {"pool_active": False, "spa_active": False},
            "runtime_ownership_preempted:hot_tub_inactive",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_active": False, "spa_active": True},
            "runtime_ownership_preempted:spa_takeover",
        ),
        (
            ThermalBody.HOT_TUB,
            ExternalChangeBatch(()),
            {"pool_active": True, "spa_active": False},
            "runtime_ownership_preempted:pool_takeover",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_active": True, "spa_active": True},
            "runtime_ownership_preempted:body_topology_contradictory",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_active": None},
            "runtime_ownership_preempted:pool_activity_missing",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"spa_active": None},
            "runtime_ownership_preempted:spa_activity_missing",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_fresh": False},
            "runtime_ownership_preempted:pool_activity_stale",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"spa_fresh": False},
            "runtime_ownership_preempted:spa_activity_stale",
        ),
        (
            ThermalBody.POOL,
            ExternalChangeBatch(()),
            {"pool_usable": False},
            "runtime_ownership_preempted:pool_activity_unusable",
        ),
    ),
)
def test_hydraulic_loss_or_takeover_preempts_runtime_ownership(
    body: ThermalBody,
    changes: ExternalChangeBatch,
    kwargs: dict[str, object],
    reason: str,
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(
            body=body,
            activation=True,
            evaluation_id="evaluation-1",
            plan_id="plan-1",
        ),
    )

    decision = manager.evaluate(
        evidence(body=body, at=NOW + timedelta(seconds=1), changes=changes, **kwargs)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    (
        ({"pump_rpm": None}, "runtime_ownership_preempted:pump_evidence_missing"),
        ({"pump_fresh": False}, "runtime_ownership_preempted:pump_evidence_stale"),
        ({"pump_usable": False}, "runtime_ownership_preempted:pump_evidence_unusable"),
        ({"pump_rpm": 2600}, "runtime_ownership_preempted:pump_external_change"),
        (
            {"configured_pump_rpm": None},
            "runtime_ownership_preempted:pump_setpoint_evidence_missing",
        ),
        (
            {"configured_pump_fresh": False},
            "runtime_ownership_preempted:pump_setpoint_evidence_stale",
        ),
        (
            {"configured_pump_usable": False},
            "runtime_ownership_preempted:pump_setpoint_evidence_unusable",
        ),
        (
            {"configured_pump_rpm": 2600},
            "runtime_ownership_preempted:pump_setpoint_external_change",
        ),
        ({"heat_source": None}, "runtime_ownership_preempted:source_evidence_missing"),
        ({"source_fresh": False}, "runtime_ownership_preempted:source_evidence_stale"),
        ({"source_usable": False}, "runtime_ownership_preempted:source_evidence_unusable"),
        ({"heat_source": PhysicalHeatMode.GAS}, "runtime_ownership_preempted:source_external_change"),
    ),
)
def test_owned_pump_and_source_fail_closed_on_relevant_evidence(
    kwargs: dict[str, object],
    reason: str,
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(pump_rpm=2900, source=PhysicalHeatMode.SOLAR),
    )

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), **kwargs)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert decision.reason_code == reason


def test_expected_pump_change_does_not_hide_unrelated_source_preemption() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(pump_rpm=2900, source=PhysicalHeatMode.SOLAR),
    )
    batch = ExternalChangeBatch(
        (external_event("pool.raw_heater_id", "H0002", "H0001"),),
        (attribution("pump_speed"),),
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            heat_source=PhysicalHeatMode.GAS,
            changes=batch,
        )
    )

    assert decision.reason_code == "runtime_ownership_preempted:source_external_change"


def test_expected_source_change_does_not_hide_unrelated_body_preemption() -> None:
    manager = full_manager()
    batch = ExternalChangeBatch(
        (external_event("pool.active", True, False),),
        (attribution("body_heat_source"),),
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            pool_active=False,
            changes=batch,
        )
    )

    assert decision.reason_code == "runtime_ownership_preempted:pool_inactive"


def test_expected_consequence_does_not_hide_shared_hydraulic_conflict() -> None:
    manager = full_manager()
    batch = ExternalChangeBatch((), (attribution("pump_speed"),))

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            changes=batch,
            circuits=(
                SharedHydraulicCircuitEvidence(
                    concept="waterfall.active",
                    active=True,
                    fresh=True,
                    usable=True,
                    safety_class=shared_hydraulic_safety_class("waterfall.active"),
                ),
            ),
        )
    )

    assert decision.reason_code.endswith("shared_hydraulic_conflict:waterfall.active")


@pytest.mark.parametrize(
    ("circuit", "reason"),
    (
        (
            "waterfall.active",
            "runtime_ownership_preempted:shared_hydraulic_conflict:waterfall.active",
        ),
        (
            "jets.active",
            "runtime_ownership_preempted:shared_hydraulic_conflict:jets.active",
        ),
        (
            "slide.active",
            "runtime_ownership_preempted:shared_hydraulic_conflict:slide.active",
        ),
    ),
)
def test_repository_proven_shared_hydraulic_circuit_preempts(
    circuit: str,
    reason: str,
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            circuits=(
                SharedHydraulicCircuitEvidence(
                    concept=circuit,
                    active=True,
                    fresh=True,
                    usable=True,
                    safety_class=shared_hydraulic_safety_class(circuit),
                ),
            ),
        )
    )

    assert decision.reason_code == reason


def test_proven_nonhydraulic_circuit_does_not_preempt() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            circuits=(
                SharedHydraulicCircuitEvidence(
                    concept="pool_light.active",
                    active=True,
                    fresh=True,
                    usable=True,
                    safety_class=shared_hydraulic_safety_class("pool_light.active"),
                ),
            ),
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED


@pytest.mark.parametrize(
    "circuits",
    (
        (
            SharedHydraulicCircuitEvidence(
                concept="unknown_feature.active",
                active=True,
                fresh=True,
                usable=True,
                safety_class=SharedHydraulicSafetyClass.UNKNOWN,
            ),
        ),
        (
            SharedHydraulicCircuitEvidence(
                concept="waterfall.active",
                active=None,
                fresh=False,
                usable=False,
                safety_class=SharedHydraulicSafetyClass.CONFLICTING,
            ),
        ),
    ),
)
def test_ambiguous_shared_hydraulic_evidence_fails_closed(
    circuits: tuple[SharedHydraulicCircuitEvidence, ...],
) -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), circuits=circuits)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED


def handoff_request(
    manager: ThermalRuntimeOwnershipManager,
    *,
    body: ThermalBody = ThermalBody.POOL,
    explicit: bool = True,
    evaluation_id: str = "evaluation-2",
    plan_id: str = "plan-2",
    execution_plan_id: str = "execution-plan-2",
    requested_mode: str = "Solar",
    pump_rpm: int | None = 2900,
    source: PhysicalHeatMode | None = PhysicalHeatMode.SOLAR,
) -> ThermalRuntimeHandoffRequest:
    lease = manager.state.lease
    assert lease is not None
    return ThermalRuntimeHandoffRequest(
        explicit=explicit,
        predecessor_lease_id=lease.lease_id,
        predecessor_generation=lease.generation,
        successor_context=ThermalLiveExecutionContext(evaluation_id, plan_id),
        successor_execution_plan_id=execution_plan_id,
        successor_body=body,
        successor_requested_mode=requested_mode,
        successor_requires_body_active=True,
        successor_required_pump_rpm=pump_rpm,
        successor_heat_source=source,
    )


def full_manager() -> ThermalRuntimeOwnershipManager:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
        ),
    )
    return manager


def verified_full_manager() -> ThermalRuntimeOwnershipManager:
    """Build a lease by accepting and observing each exact operation in order."""

    accepted_base = NOW - timedelta(seconds=10)
    assessment = thermal_assessment(
        at=accepted_base,
        current_body_active=False,
        current_rpm=0,
    )
    currentness = ThermalExecutionCurrentness.from_assessment(
        assessment,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        "evaluation-1",
        assessment.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = ThermalLiveExecutionOwnership(
        evaluation_id="evaluation-1",
        thermal_plan_id=assessment.plan_id,
        execution_plan_id="execution-plan-1",
        target_body=ThermalBody.POOL,
    )
    values = (
        (0, {"pool_observed_at": accepted_base + timedelta(seconds=1)}),
        (
            1,
            {
                "pump_rpm": 3000,
                "configured_pump_rpm": 3000,
                "pump_observed_at": accepted_base + timedelta(seconds=3),
                "configured_pump_observed_at": accepted_base + timedelta(seconds=3),
            },
        ),
        (
            2,
            {
                "pump_rpm": 2900,
                "configured_pump_rpm": 2900,
                "pump_observed_at": accepted_base + timedelta(seconds=5),
                "configured_pump_observed_at": accepted_base + timedelta(seconds=5),
            },
        ),
        (
            3,
            {
                "heat_source": PhysicalHeatMode.SOLAR,
                "source_observed_at": accepted_base + timedelta(seconds=7),
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
                body_activation_receipt_id="body-receipt",
                body_activation_correlation_id="body-correlation",
                body_activation_accepted_at=accepted_at,
            )
        elif index in {1, 2}:
            ownership = replace(
                ownership,
                pump_operation_id=operation.operation_id,
                pump_receipt_id=f"pump-receipt-{index}",
                pump_correlation_id=f"pump-correlation-{index}",
                commanded_pump_rpm=3000 if index == 1 else 2900,
                pump_accepted_at=accepted_at,
            )
        else:
            ownership = replace(
                ownership,
                heat_source_operation_id=operation.operation_id,
                heat_source_receipt_id="source-receipt",
                heat_source_correlation_id="source-correlation",
                commanded_heat_source=PhysicalHeatMode.SOLAR,
                heat_source_accepted_at=accepted_at,
            )
        decision = manager.promote_session_provenance(
            ownership,
            promoted_at=accepted_at,
            requested_mode="Solar",
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
                plan_id=assessment.plan_id,
                execution_currentness=currentness,
                **evidence_values,
            )
        )
        verified_prefix = currentness.residual_plan.operations[: index + 1]
    return manager


def test_explicit_compatible_same_body_handoff_creates_new_generation() -> None:
    manager = full_manager()
    predecessor = manager.state.lease
    assert predecessor is not None
    request = handoff_request(manager)

    decision = manager.handoff(
        request,
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.HANDED_OFF
    successor = manager.state.lease
    assert successor is not None
    assert successor.generation == predecessor.generation + 1
    assert successor.lease_id != predecessor.lease_id
    assert successor.predecessor_lease_id == predecessor.lease_id


def test_probe_successor_handoff_retains_body_and_replaces_pump_provenance() -> None:
    builder = ThermalExecutionPlanBuilder(pump_equipment_id="p0102")
    probe_plan = builder.build(
        ThermalDesiredState(
            evaluated_at=NOW,
            body=ThermalBody.POOL,
            requested_mode="solar",
            selected_source=PhysicalHeatMode.SOLAR,
            required_pump_rpm=1500,
            reason_code="pool_temperature_probe_required",
            rpm_reason_code="baseline:temperature_probe",
            rationale=("Acquire trusted Pool water temperature.",),
            criteria=("canonical_probe",),
            evidence={"pool_target_f": 90.0},
        ),
        ThermalCurrentState(
            observed_at=NOW,
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=0,
            body_active=False,
        ),
    )
    probe_currentness = ThermalExecutionCurrentness.from_assessment(
        probe_plan,
        evaluation_id="probe-evaluation",
    )
    manager = ThermalRuntimeOwnershipManager()
    established = manager.establish(
        execution_ownership(
            activation=True,
            pump_rpm=1500,
            source=PhysicalHeatMode.OFF,
            evaluation_id=probe_currentness.evaluation_id,
            plan_id=probe_currentness.plan_id,
            execution_plan_id="probe-execution",
        ),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            probe_currentness.evaluation_id,
            probe_currentness.plan_id,
            probe_currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            verified_prefix=tuple(
                operation_signature(operation, specification.metadata)
                for operation, specification in zip(
                    probe_plan.operations,
                    probe_plan.step_specifications,
                    strict=True,
                )
            )
        ),
    )
    predecessor = manager.state.lease
    assert established.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    assert predecessor is not None
    successor_plan = thermal_assessment(
        at=NOW + timedelta(seconds=1),
        current_rpm=1500,
    )
    successor_currentness = ThermalExecutionCurrentness.from_assessment(
        successor_plan,
        evaluation_id="successor-evaluation",
    )
    request = ThermalRuntimeHandoffRequest(
        explicit=True,
        predecessor_lease_id=predecessor.lease_id,
        predecessor_generation=predecessor.generation,
        successor_context=ThermalLiveExecutionContext(
            successor_currentness.evaluation_id,
            successor_currentness.plan_id,
            successor_currentness,
        ),
        successor_execution_plan_id="successor-execution",
        successor_body=ThermalBody.POOL,
        successor_requested_mode="Solar",
        successor_requires_body_active=True,
        successor_required_pump_rpm=2900,
        successor_heat_source=PhysicalHeatMode.SOLAR,
        successor_progress=ThermalExecutionProgress(),
        replace_pump_setpoint=True,
        replace_heat_source=True,
    )

    decision = manager.handoff(
        request,
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id=successor_currentness.evaluation_id,
            plan_id=successor_currentness.plan_id,
            requested_mode="Solar",
            pump_rpm=1500,
            configured_pump_rpm=1500,
            heat_source=PhysicalHeatMode.OFF,
            execution_currentness=successor_currentness,
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.HANDED_OFF
    successor = manager.state.lease
    assert successor is not None
    assert successor.generation == predecessor.generation + 1
    assert successor.body_activation == predecessor.body_activation
    assert successor.pump_setpoint is None
    assert successor.heat_source is None


def test_probe_replacement_handoff_rejects_stale_generation() -> None:
    manager = full_manager()
    request = replace(
        handoff_request(manager, pump_rpm=3000),
        predecessor_generation=999,
        replace_pump_setpoint=True,
    )

    decision = manager.handoff(
        request,
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("predecessor_provenance_mismatch")


@pytest.mark.parametrize(
    ("request_changes", "evidence_changes", "reason"),
    (
        ({"explicit": False}, {}, "runtime_ownership_handoff_denied:not_explicit"),
        (
            {"body": ThermalBody.HOT_TUB},
            {"body": ThermalBody.HOT_TUB},
            "runtime_ownership_handoff_denied:cross_body",
        ),
        (
            {"evaluation_id": "evaluation-2"},
            {"evaluation_id": "evaluation-3", "plan_id": "plan-2"},
            "runtime_ownership_handoff_denied:successor_evaluation_not_current",
        ),
        (
            {"plan_id": "plan-2"},
            {"evaluation_id": "evaluation-2", "plan_id": "plan-3"},
            "runtime_ownership_handoff_denied:successor_plan_not_current",
        ),
        (
            {"pump_rpm": 3000},
            {},
            "runtime_ownership_handoff_denied:pump_incompatible",
        ),
        (
            {"source": PhysicalHeatMode.GAS},
            {},
            "runtime_ownership_handoff_denied:source_incompatible",
        ),
    ),
)
def test_invalid_handoff_is_denied(
    request_changes: dict[str, object],
    evidence_changes: dict[str, object],
    reason: str,
) -> None:
    manager = full_manager()
    request = handoff_request(manager, **request_changes)
    successor_evidence = {
        "at": NOW + timedelta(seconds=1),
        "evaluation_id": "evaluation-2",
        "plan_id": "plan-2",
    }
    successor_evidence.update(evidence_changes)

    decision = manager.handoff(request, evidence(**successor_evidence))

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code == reason


def test_hot_tub_to_pool_handoff_is_denied_symmetrically() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(
            body=ThermalBody.HOT_TUB,
            activation=True,
            pump_rpm=3000,
            source=PhysicalHeatMode.GAS,
        ),
        requested_mode="Gas",
    )
    request = handoff_request(
        manager,
        body=ThermalBody.POOL,
        requested_mode="Gas",
        pump_rpm=3000,
        source=PhysicalHeatMode.GAS,
    )

    decision = manager.handoff(
        request,
        evidence(
            body=ThermalBody.POOL,
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
            requested_mode="Gas",
            pump_rpm=3000,
            configured_pump_rpm=3000,
            heat_source=PhysicalHeatMode.GAS,
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("cross_body")


def test_handoff_rejects_mismatched_predecessor_provenance() -> None:
    manager = full_manager()
    request = handoff_request(manager)
    request = ThermalRuntimeHandoffRequest(
        explicit=request.explicit,
        predecessor_lease_id="another-lease",
        predecessor_generation=request.predecessor_generation,
        successor_context=request.successor_context,
        successor_execution_plan_id=request.successor_execution_plan_id,
        successor_body=request.successor_body,
        successor_requested_mode=request.successor_requested_mode,
        successor_requires_body_active=request.successor_requires_body_active,
        successor_required_pump_rpm=request.successor_required_pump_rpm,
        successor_heat_source=request.successor_heat_source,
    )

    decision = manager.handoff(
        request,
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("predecessor_provenance_mismatch")


def test_restart_cannot_handoff_an_old_runtime_lease() -> None:
    prior_manager = full_manager()
    request = handoff_request(prior_manager)
    restarted = ThermalRuntimeOwnershipManager()

    decision = restarted.handoff(
        request,
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("predecessor_not_owned")
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_preempted_or_relinquished_ownership_cannot_handoff() -> None:
    preempted = full_manager()
    preempted.evaluate(
        evidence(at=NOW + timedelta(seconds=1), pool_active=False)
    )
    denied_preempted = preempted.handoff(
        handoff_request(preempted),
        evidence(
            at=NOW + timedelta(seconds=2),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    relinquished = full_manager()
    lease = relinquished.state.lease
    assert lease is not None
    relinquished.relinquish(
        lease_id=lease.lease_id,
        relinquished_at=NOW + timedelta(seconds=1),
        reason_code="thermal_lifecycle_complete",
    )
    denied_relinquished = relinquished.handoff(
        handoff_request(relinquished),
        evidence(
            at=NOW + timedelta(seconds=2),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        ),
    )

    assert denied_preempted.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert denied_relinquished.disposition is ThermalRuntimeOwnershipDisposition.DENIED


def test_superseded_ownership_cannot_handoff() -> None:
    manager = full_manager()
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        )
    )

    decision = manager.handoff(
        handoff_request(manager, evaluation_id="evaluation-3", plan_id="plan-3"),
        evidence(
            at=NOW + timedelta(seconds=2),
            evaluation_id="evaluation-3",
            plan_id="plan-3",
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("predecessor_not_owned")


def test_relinquishment_is_terminal_and_command_free() -> None:
    manager = full_manager()
    lease = manager.state.lease
    assert lease is not None

    decision = manager.relinquish(
        lease_id=lease.lease_id,
        relinquished_at=NOW + timedelta(seconds=1),
        reason_code="thermal_lifecycle_complete",
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RELINQUISHED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert decision.command_delivery_enabled is False


def test_relinquishment_can_retain_concept_specific_residual_provenance() -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None

    manager.relinquish(
        lease_id=lease.lease_id,
        relinquished_at=NOW + timedelta(seconds=1),
        reason_code="thermal_target_converged",
        retain_termination_entitlement=True,
    )

    residual = manager.residual_termination
    assert residual is not None
    assert residual.lease_id == lease.lease_id
    assert residual.generation == lease.generation
    assert residual.body_activation == lease.body_activation
    assert residual.pump_setpoint == lease.pump_setpoint
    assert residual.heat_source == lease.heat_source
    assert manager.state.status is ThermalRuntimeOwnershipStatus.RELINQUISHED


def test_residual_provenance_is_not_restored_or_reconstructed_from_truth() -> None:
    manager = ThermalRuntimeOwnershipManager()

    decision = manager.evaluate(evidence(at=NOW, pump_rpm=2900))

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP
    assert manager.residual_termination is None


def test_new_positive_session_provenance_invalidates_old_residual_token() -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    manager.relinquish(
        lease_id=lease.lease_id,
        relinquished_at=NOW + timedelta(seconds=1),
        reason_code="interrupted",
        retain_termination_entitlement=True,
    )
    assert manager.residual_termination is not None

    ownership = execution_ownership(
        activation=True,
        execution_plan_id="execution-plan-new",
    )
    established = manager.establish(
        ownership,
        established_at=NOW + timedelta(seconds=2),
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            ownership.evaluation_id,
            ownership.thermal_plan_id,
        ),
    )

    assert established.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    assert manager.residual_termination is None
    assert not hasattr(manager, "deliver")


def test_unowned_observation_coincidence_cannot_be_relinquished_or_handed_off() -> None:
    manager = ThermalRuntimeOwnershipManager()

    decision = manager.relinquish(
        lease_id="observed-matching-state",
        relinquished_at=NOW,
        reason_code="thermal_lifecycle_complete",
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_restart_manager_never_reconstructs_ownership_from_state_or_history() -> None:
    old = full_manager()
    assert old.state.status is ThermalRuntimeOwnershipStatus.OWNED

    restarted = ThermalRuntimeOwnershipManager()
    decision = restarted.evaluate(evidence())

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP
    assert restarted.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_historical_delivery_provenance_cannot_establish_against_new_context() -> None:
    manager = ThermalRuntimeOwnershipManager()
    historical = execution_ownership(pump_rpm=2900)

    decision = manager.establish(
        historical,
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext("evaluation-2", "plan-2"),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("provenance_not_current")
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_runtime_ownership_survives_compatible_new_evaluation_epoch() -> None:
    original_plan = thermal_assessment()
    originating = ThermalExecutionCurrentness.from_assessment(
        original_plan,
        evaluation_id="evaluation-1",
    )
    progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            original_plan.operations[0],
            original_plan.step_specifications[0].metadata,
        )
    )
    manager = ThermalRuntimeOwnershipManager()
    established = manager.establish(
        execution_ownership(pump_rpm=2900, plan_id=originating.plan_id),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            originating.evaluation_id,
            originating.plan_id,
            originating,
        ),
        execution_progress=progress,
    )
    residual_plan = thermal_assessment(
        at=NOW + timedelta(seconds=1),
        current_rpm=2900,
    )
    current = ThermalExecutionCurrentness.from_assessment(
        residual_plan,
        evaluation_id="evaluation-2",
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id=current.evaluation_id,
            plan_id=current.plan_id,
            execution_currentness=current,
        )
    )

    assert established.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED


@pytest.mark.parametrize(
    "override_state",
    (PumpSpeedOverrideState.PENDING, PumpSpeedOverrideState.VERIFIED),
)
def test_same_purpose_pump_override_preserves_body_and_source_provenance(
    override_state: PumpSpeedOverrideState,
) -> None:
    original_plan = thermal_assessment()
    originating = ThermalExecutionCurrentness.from_assessment(
        original_plan,
        evaluation_id="evaluation-1",
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.establish(
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
            plan_id=originating.plan_id,
        ),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            originating.evaluation_id,
            originating.plan_id,
            originating,
        ),
        execution_progress=ThermalExecutionProgress(),
    )
    current_plan = thermal_assessment(
        at=NOW + timedelta(seconds=1),
        rpm=3200,
        current_source=PhysicalHeatMode.SOLAR,
        current_rpm=(3200 if override_state is PumpSpeedOverrideState.VERIFIED else 2900),
    )
    current = ThermalExecutionCurrentness.from_assessment(
        current_plan,
        evaluation_id="evaluation-2",
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id=current.evaluation_id,
            plan_id=current.plan_id,
            execution_currentness=current,
            pump_rpm=(
                3200 if override_state is PumpSpeedOverrideState.VERIFIED else 2900
            ),
            configured_pump_rpm=(
                3200 if override_state is PumpSpeedOverrideState.VERIFIED else 2900
            ),
            pump_session_id="pool-solar-session",
            pump_session_purpose=PumpSpeedSessionPurpose.SOLAR,
            pump_session_pump_circuit_id="p0102",
            pump_session_effective_rpm=3200,
            pump_session_override_state=override_state,
        )
    )

    lease = manager.state.lease
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.heat_source is not None
    if override_state is PumpSpeedOverrideState.VERIFIED:
        assert lease.pump_setpoint is None
        assert lease.pump_session_id == "pool-solar-session"
        assert lease.pump_session_effective_rpm == 3200
        assert lease.originating_currentness == current
    else:
        assert lease.pump_setpoint is not None
        assert lease.originating_currentness == originating


def test_return_to_baseline_preserves_body_and_source_after_override() -> None:
    original_plan = thermal_assessment()
    originating = ThermalExecutionCurrentness.from_assessment(
        original_plan,
        evaluation_id="evaluation-1",
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.establish(
        execution_ownership(
            activation=True,
            pump_rpm=2900,
            source=PhysicalHeatMode.SOLAR,
            plan_id=originating.plan_id,
        ),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            originating.evaluation_id,
            originating.plan_id,
            originating,
        ),
        execution_progress=ThermalExecutionProgress(),
    )
    overridden_plan = thermal_assessment(
        at=NOW + timedelta(seconds=1),
        rpm=3200,
        current_source=PhysicalHeatMode.SOLAR,
        current_rpm=3200,
    )
    overridden = ThermalExecutionCurrentness.from_assessment(
        overridden_plan,
        evaluation_id="evaluation-2",
    )
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id=overridden.evaluation_id,
            plan_id=overridden.plan_id,
            execution_currentness=overridden,
            pump_rpm=3200,
            configured_pump_rpm=3200,
            pump_session_id="pool-solar-session",
            pump_session_purpose=PumpSpeedSessionPurpose.SOLAR,
            pump_session_pump_circuit_id="p0102",
            pump_session_effective_rpm=3200,
            pump_session_override_state=PumpSpeedOverrideState.VERIFIED,
        )
    )
    baseline_plan = thermal_assessment(
        at=NOW + timedelta(seconds=2),
        rpm=2900,
        current_source=PhysicalHeatMode.SOLAR,
        current_rpm=2900,
    )
    baseline = ThermalExecutionCurrentness.from_assessment(
        baseline_plan,
        evaluation_id="evaluation-3",
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=2),
            evaluation_id=baseline.evaluation_id,
            plan_id=baseline.plan_id,
            execution_currentness=baseline,
            pump_rpm=2900,
            configured_pump_rpm=2900,
            pump_session_id="pool-solar-session",
            pump_session_purpose=PumpSpeedSessionPurpose.SOLAR,
            pump_session_pump_circuit_id="p0102",
            pump_session_effective_rpm=2900,
            pump_session_override_state=PumpSpeedOverrideState.NONE,
        )
    )

    lease = manager.state.lease
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.heat_source is not None
    assert lease.pump_setpoint is None
    assert lease.pump_session_id == "pool-solar-session"
    assert lease.pump_session_effective_rpm == 2900
    assert lease.originating_currentness == baseline


def test_typed_runtime_ownership_fails_closed_without_current_purpose() -> None:
    original_plan = thermal_assessment()
    originating = ThermalExecutionCurrentness.from_assessment(
        original_plan,
        evaluation_id="evaluation-1",
    )
    progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            original_plan.operations[0],
            original_plan.step_specifications[0].metadata,
        )
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.establish(
        execution_ownership(pump_rpm=2900, plan_id=originating.plan_id),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            originating.evaluation_id,
            originating.plan_id,
            originating,
        ),
        execution_progress=progress,
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert decision.reason_code.endswith("execution_currentness_unavailable")


def test_runtime_ownership_is_superseded_by_changed_execution_purpose() -> None:
    original_plan = thermal_assessment()
    originating = ThermalExecutionCurrentness.from_assessment(
        original_plan,
        evaluation_id="evaluation-1",
    )
    progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            original_plan.operations[0],
            original_plan.step_specifications[0].metadata,
        )
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.establish(
        execution_ownership(pump_rpm=2900, plan_id=originating.plan_id),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            originating.evaluation_id,
            originating.plan_id,
            originating,
        ),
        execution_progress=progress,
    )
    gas_plan = thermal_assessment(
        at=NOW + timedelta(seconds=1),
        requested_mode="gas",
        source=PhysicalHeatMode.GAS,
        rpm=3000,
        current_rpm=2900,
    )
    current = ThermalExecutionCurrentness.from_assessment(
        gas_plan,
        evaluation_id="evaluation-2",
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id=current.evaluation_id,
            plan_id=current.plan_id,
            requested_mode="Gas",
            execution_currentness=current,
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.SUPERSEDED
    assert decision.reason_code == "runtime_ownership_superseded:execution_purpose"


def test_typed_ownership_cannot_be_established_without_poolos_progress() -> None:
    plan = thermal_assessment()
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    manager = ThermalRuntimeOwnershipManager()

    decision = manager.establish(
        execution_ownership(pump_rpm=2900, plan_id=currentness.plan_id),
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            currentness.evaluation_id,
            currentness.plan_id,
            currentness,
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("execution_currentness_progress_incomplete")
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


def test_same_session_accepted_operations_promote_exact_owned_concepts() -> None:
    plan = thermal_assessment(current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    activation = execution_ownership(
        activation=True,
        plan_id=currentness.plan_id,
    )
    first_progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            plan.operations[0],
            plan.step_specifications[0].metadata,
        )
    )

    established = manager.promote_session_provenance(
        activation,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=first_progress,
    )
    combined = execution_ownership(
        activation=True,
        pump_rpm=2900,
        source=PhysicalHeatMode.SOLAR,
        plan_id=currentness.plan_id,
    )
    promoted = manager.promote_session_provenance(
        combined,
        promoted_at=NOW + timedelta(seconds=1),
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=operation_signature(
                plan.operations[-1],
                plan.step_specifications[-1].metadata,
            )
        ),
    )

    assert established.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    assert promoted.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    lease = manager.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert lease.owns_pump_setpoint
    assert lease.owns_heat_source


def test_delayed_post_acceptance_body_proof_survives_pending_refreshes() -> None:
    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = execution_ownership(
        activation=True,
        plan_id=currentness.plan_id,
    )
    progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            plan.operations[0],
            plan.step_specifications[0].metadata,
        ),
        accepted_operation_id=ownership.body_activation_operation_id,
    )
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=progress,
    )

    pending = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=10),
            pool_active=False,
            execution_currentness=currentness,
            plan_id=currentness.plan_id,
            pool_observed_at=NOW + timedelta(seconds=5),
        )
    )
    confirmed = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=20),
            pool_active=True,
            execution_currentness=currentness,
            plan_id=currentness.plan_id,
            pool_observed_at=NOW + timedelta(seconds=6),
        )
    )

    assert pending.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert confirmed.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    lease = manager.state.lease
    assert lease is not None
    assert lease.last_confirmed_at == NOW + timedelta(seconds=20)
    assert lease.body_activation_accepted_at == NOW
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in lease.verified_concepts


@pytest.mark.parametrize("concept", ("body", "pump", "source"))
def test_explicit_external_intervention_preempts_pending_command_settling(
    concept: str,
) -> None:
    if concept == "body":
        plan = thermal_assessment(current_body_active=False, current_rpm=0)
        operation = plan.operations[0]
        ownership = replace(
            execution_ownership(activation=True, plan_id=plan.plan_id),
            body_activation_operation_id=operation.operation_id,
            body_activation_accepted_at=NOW,
        )
        event = external_event(
            "pool.active",
            True,
            False,
            reconciliation_required=False,
        )
        evidence_values = {
            "pool_active": False,
            "pool_observed_at": NOW + timedelta(seconds=1),
        }
    elif concept == "pump":
        plan = thermal_assessment(current_rpm=2600)
        operation = plan.operations[0]
        ownership = replace(
            execution_ownership(pump_rpm=2900, plan_id=plan.plan_id),
            pump_operation_id=operation.operation_id,
            pump_accepted_at=NOW,
        )
        event = external_event("pump.rpm", 2900, 2600)
        evidence_values = {
            "pump_rpm": 2600,
            "configured_pump_rpm": 2600,
            "pump_observed_at": NOW + timedelta(seconds=1),
            "configured_pump_observed_at": NOW + timedelta(seconds=1),
        }
    else:
        plan = thermal_assessment(current_rpm=2900)
        operation = plan.operations[0]
        ownership = replace(
            execution_ownership(
                source=PhysicalHeatMode.SOLAR,
                plan_id=plan.plan_id,
            ),
            heat_source_operation_id=operation.operation_id,
            heat_source_accepted_at=NOW,
        )
        event = external_event("pool.raw_heater_id", "H0002", "H0001")
        evidence_values = {
            "heat_source": PhysicalHeatMode.GAS,
            "source_observed_at": NOW + timedelta(seconds=1),
        }
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=operation.operation_id,
        ),
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            changes=ExternalChangeBatch((event,)),
            **evidence_values,
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert manager.residual_termination is None


def test_receipt_time_remains_causal_boundary_when_promotion_is_delayed() -> None:
    """Later bookkeeping must not exclude a valid post-acceptance observation."""

    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_accepted_at=NOW,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW + timedelta(seconds=2),
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=operation_signature(
                plan.operations[0],
                plan.step_specifications[0].metadata,
            ),
            accepted_operation_id=ownership.body_activation_operation_id,
        ),
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=3),
            pool_active=True,
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(seconds=1),
        )
    )

    lease = manager.state.lease
    assert lease is not None
    assert lease.body_activation_accepted_at == NOW
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in lease.verified_concepts


@pytest.mark.parametrize(
    "observed_at",
    (NOW - timedelta(microseconds=1), NOW),
)
def test_body_observation_not_strictly_after_acceptance_cannot_verify(
    observed_at: datetime,
) -> None:
    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id=plan.operations[0].operation_id,
        body_activation_accepted_at=NOW,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=ThermalLiveExecutionContext(
            currentness.evaluation_id,
            currentness.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=plan.operations[0].operation_id,
        ),
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=observed_at,
        )
    )

    lease = manager.state.lease
    assert lease is not None
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION not in lease.verified_concepts


def test_repeated_post_acceptance_observation_verification_is_idempotent() -> None:
    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id=plan.operations[0].operation_id,
        body_activation_accepted_at=NOW,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=ThermalLiveExecutionContext(
            currentness.evaluation_id,
            currentness.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=plan.operations[0].operation_id,
        ),
    )
    first = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )
    second = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=2),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )

    assert first.current_state.lease is not None
    assert second.current_state.lease is not None
    assert first.current_state.lease.verified_concepts == (
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
    )
    assert second.current_state.lease.verified_concepts == (
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
    )


def test_replaced_same_concept_provenance_requires_new_post_acceptance_proof() -> None:
    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    original = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id=plan.operations[0].operation_id,
        body_activation_accepted_at=NOW,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        original,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=plan.operations[0].operation_id,
        ),
    )
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )
    replacement = replace(
        original,
        body_activation_operation_id="replacement-body-operation",
        body_activation_receipt_id="replacement-body-receipt",
        body_activation_correlation_id="replacement-body-correlation",
        body_activation_accepted_at=NOW + timedelta(seconds=2),
    )
    manager.promote_session_provenance(
        replacement,
        promoted_at=NOW + timedelta(seconds=2),
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id="replacement-body-operation",
        ),
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=3),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(seconds=1),
        )
    )
    lease = manager.state.lease
    assert lease is not None
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION not in lease.verified_concepts

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=4),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(seconds=3),
        )
    )
    lease = manager.state.lease
    assert lease is not None
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in lease.verified_concepts


def test_verified_prefix_same_value_cannot_verify_different_operation_provenance() -> None:
    """Semantic equality is not correlation to the accepted operation."""

    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id="different-body-operation",
        body_activation_accepted_at=NOW,
    )

    manager.establish(
        ownership,
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            "evaluation-1",
            currentness.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            verified_prefix=(currentness.residual_plan.operations[0],),
        ),
    )

    lease = manager.state.lease
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.body_activation.operation_id == "different-body-operation"
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION not in lease.verified_concepts


def test_accepted_same_value_cannot_verify_different_operation_provenance() -> None:
    """Post-acceptance native equality must match the exact accepted operation."""

    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id="different-body-operation",
        body_activation_accepted_at=NOW,
    )
    manager = ThermalRuntimeOwnershipManager()
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=ThermalLiveExecutionContext(
            currentness.evaluation_id,
            currentness.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=plan.operations[0].operation_id,
        ),
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )

    lease = manager.state.lease
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.body_activation.operation_id == "different-body-operation"
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION not in lease.verified_concepts


def test_stale_body_continuity_cannot_retain_body_cleanup_entitlement() -> None:
    plan = thermal_assessment(current_body_active=False, current_rpm=0)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = replace(
        execution_ownership(activation=True, plan_id=currentness.plan_id),
        body_activation_operation_id=plan.operations[0].operation_id,
        body_activation_accepted_at=NOW,
    )
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=ThermalExecutionProgress(
            accepted_current=currentness.residual_plan.operations[0],
            accepted_operation_id=plan.operations[0].operation_id,
        ),
    )
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=2),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pool_fresh=False,
            pool_observed_at=NOW + timedelta(milliseconds=500),
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert manager.residual_termination is None


def test_terminal_diagnostic_selects_event_that_caused_preemption() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    earlier_nonterminal = external_event(
        "pump.rpm",
        2600,
        2900,
        reconciliation_required=False,
        observed_at=NOW + timedelta(milliseconds=250),
    )
    causal = external_event(
        "pump.rpm",
        2900,
        2600,
        observed_at=NOW + timedelta(milliseconds=500),
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            pump_rpm=2600,
            configured_pump_rpm=2900,
            changes=ExternalChangeBatch((earlier_nonterminal, causal)),
        )
    )

    diagnostic = manager.last_terminal_transition
    assert diagnostic is not None
    assert diagnostic.external_event_id == causal.event_id
    assert diagnostic.external_event_observed_at == causal.observed_at


def test_shared_hydraulic_diagnostic_is_body_scoped_even_if_concept_mentions_pump() -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=lease.thermal_plan_id,
            execution_currentness=lease.originating_currentness,
            circuits=(
                SharedHydraulicCircuitEvidence(
                    concept="pump_room_valve.active",
                    active=None,
                    fresh=True,
                    usable=False,
                    safety_class=SharedHydraulicSafetyClass.UNKNOWN,
                ),
            ),
        )
    )

    diagnostic = manager.last_terminal_transition
    assert diagnostic is not None
    assert diagnostic.affected_concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION


def test_external_body_off_then_on_in_one_batch_breaks_owned_activation_epoch() -> None:
    """Final ON equality cannot erase an observed external OFF/ON epoch break."""

    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None
    body_off = external_event(
        "pool.active",
        True,
        False,
        reconciliation_required=False,
        observed_at=NOW + timedelta(seconds=1),
    )
    body_on = external_event(
        "pool.active",
        False,
        True,
        reconciliation_required=False,
        observed_at=NOW + timedelta(seconds=2),
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=3),
            plan_id=lease.thermal_plan_id,
            execution_currentness=lease.originating_currentness,
            pool_active=True,
            pool_observed_at=NOW + timedelta(seconds=2),
            changes=ExternalChangeBatch((body_off, body_on)),
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert manager.residual_termination is None
    diagnostic = manager.last_terminal_transition
    assert diagnostic is not None
    assert diagnostic.external_event_id == body_on.event_id
    assert diagnostic.affected_concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION


def test_pump_proof_requires_exact_configured_speed_and_tolerant_actual_rpm() -> None:
    plan = thermal_assessment(current_rpm=2600)
    currentness = ThermalExecutionCurrentness.from_assessment(
        plan,
        evaluation_id="evaluation-1",
    )
    context = ThermalLiveExecutionContext(
        currentness.evaluation_id,
        currentness.plan_id,
        currentness,
    )
    manager = ThermalRuntimeOwnershipManager()
    ownership = replace(
        execution_ownership(pump_rpm=2900, plan_id=currentness.plan_id),
        pump_operation_id=plan.operations[0].operation_id,
    )
    progress = ThermalExecutionProgress(
        accepted_current=operation_signature(
            plan.operations[0],
            plan.step_specifications[0].metadata,
        ),
        accepted_operation_id=plan.operations[0].operation_id,
    )
    manager.promote_session_provenance(
        ownership,
        promoted_at=NOW,
        requested_mode="Solar",
        originating_context=context,
        execution_progress=progress,
    )

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pump_rpm=2900,
            configured_pump_rpm=2880,
            pump_observed_at=NOW + timedelta(seconds=1),
            configured_pump_observed_at=NOW + timedelta(seconds=1),
        )
    )
    lease = manager.state.lease
    assert lease is not None
    assert ThermalRuntimeOwnedConcept.PUMP_SETPOINT not in lease.verified_concepts

    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=2),
            plan_id=currentness.plan_id,
            execution_currentness=currentness,
            pump_rpm=2876,
            configured_pump_rpm=2900,
            pump_observed_at=NOW + timedelta(seconds=2),
            configured_pump_observed_at=NOW + timedelta(seconds=2),
        )
    )
    lease = manager.state.lease
    assert lease is not None
    assert ThermalRuntimeOwnedConcept.PUMP_SETPOINT in lease.verified_concepts


def test_session_provenance_promotion_rejects_different_session() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(activation=True))

    decision = manager.promote_session_provenance(
        execution_ownership(
            pump_rpm=2900,
            execution_plan_id="execution-plan-2",
        ),
        promoted_at=NOW + timedelta(seconds=1),
        requested_mode="Solar",
        originating_context=ThermalLiveExecutionContext(
            "evaluation-1",
            "plan-1",
        ),
        execution_progress=ThermalExecutionProgress(),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("session_provenance_mismatch")
    lease = manager.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert not lease.owns_pump_setpoint


def test_incomplete_delivery_provenance_is_denied_without_partial_ownership() -> None:
    manager = ThermalRuntimeOwnershipManager()
    incomplete = execution_ownership(pump_rpm=2900)
    incomplete = ThermalLiveExecutionOwnership(
        evaluation_id=incomplete.evaluation_id,
        thermal_plan_id=incomplete.thermal_plan_id,
        execution_plan_id=incomplete.execution_plan_id,
        target_body=incomplete.target_body,
        pump_operation_id=incomplete.pump_operation_id,
        pump_receipt_id=incomplete.pump_receipt_id,
        pump_correlation_id=None,
        commanded_pump_rpm=2900,
    )

    decision = manager.establish(
        incomplete,
        established_at=NOW,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext("evaluation-1", "plan-1"),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("provenance_incomplete")
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    (
        (
            {"evaluation_id": "evaluation-2"},
            "runtime_ownership_superseded:evaluation_id",
        ),
        ({"plan_id": "plan-2"}, "runtime_ownership_superseded:plan_id"),
        (
            {"requested_mode": "Off"},
            "runtime_ownership_superseded:requested_mode",
        ),
    ),
)
def test_incompatible_current_thermal_identity_supersedes_ownership(
    kwargs: dict[str, object],
    reason: str,
) -> None:
    manager = full_manager()

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), **kwargs)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.SUPERSEDED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.SUPERSEDED
    assert decision.reason_code == reason
    assert manager.residual_termination is None


def test_terminal_ownership_never_silently_becomes_owned_again() -> None:
    manager = full_manager()
    manager.evaluate(evidence(at=NOW + timedelta(seconds=1), pool_active=False))

    decision = manager.evaluate(evidence(at=NOW + timedelta(seconds=2)))

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert manager.state.status is ThermalRuntimeOwnershipStatus.PREEMPTED


def test_preempted_external_body_session_cannot_reestablish_automatically() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(
        manager,
        execution_ownership(body=ThermalBody.HOT_TUB, pump_rpm=2600),
    )
    manager.evaluate(
        evidence(
            body=ThermalBody.HOT_TUB,
            at=NOW + timedelta(seconds=1),
            pump_rpm=2900,
            configured_pump_rpm=2600,
            heat_source=PhysicalHeatMode.OFF,
        )
    )

    decision = manager.promote_session_provenance(
        execution_ownership(
            body=ThermalBody.HOT_TUB,
            pump_rpm=3000,
            evaluation_id="evaluation-2",
            plan_id="plan-2",
            execution_plan_id="execution-plan-2",
        ),
        promoted_at=NOW + timedelta(seconds=2),
        requested_mode="Gas",
        originating_context=ThermalLiveExecutionContext(
            "evaluation-2",
            "plan-2",
        ),
        execution_progress=ThermalExecutionProgress(),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.DENIED
    assert decision.reason_code.endswith("ownership_terminal")
    assert manager.state.status is ThermalRuntimeOwnershipStatus.PREEMPTED


def test_superseded_external_body_session_can_start_fresh_accepted_generation() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2600))
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            evaluation_id="evaluation-2",
            plan_id="plan-2",
            heat_source=PhysicalHeatMode.OFF,
            pump_rpm=2600,
            configured_pump_rpm=2600,
        )
    )
    assert manager.residual_termination is None
    successor_plan = thermal_assessment(
        at=NOW + timedelta(seconds=2),
        body=ThermalBody.HOT_TUB,
        requested_mode="gas",
        source=PhysicalHeatMode.GAS,
        rpm=3000,
        current_rpm=2600,
    )
    currentness = ThermalExecutionCurrentness.from_assessment(
        successor_plan,
        evaluation_id="evaluation-2",
    )

    decision = manager.promote_session_provenance(
        execution_ownership(
            body=ThermalBody.HOT_TUB,
            pump_rpm=3000,
            evaluation_id="evaluation-2",
            plan_id=currentness.plan_id,
            execution_plan_id="execution-plan-2",
        ),
        promoted_at=NOW + timedelta(seconds=2),
        requested_mode="Gas",
        originating_context=ThermalLiveExecutionContext(
            "evaluation-2",
            currentness.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(
            accepted_current=operation_signature(
                successor_plan.operations[0],
                successor_plan.step_specifications[0].metadata,
            ),
        ),
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    lease = manager.state.lease
    assert lease is not None
    assert lease.generation == 2
    assert lease.body_activation is None
    assert lease.pump_setpoint is not None


def test_external_exact_matching_rpm_does_not_manufacture_unowned_ownership() -> None:
    manager = ThermalRuntimeOwnershipManager()
    batch = ExternalChangeBatch(
        (external_event("pump.rpm", 2600, 2900, reconciliation_required=False),)
    )

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), changes=batch)
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP


def test_matching_external_rpm_cannot_replace_accepted_delivery_provenance() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))
    original = manager.state.lease
    assert original is not None and original.pump_setpoint is not None
    batch = ExternalChangeBatch(
        (external_event("pump.rpm", 2600, 2900, reconciliation_required=False),)
    )

    decision = manager.evaluate(
        evidence(at=NOW + timedelta(seconds=1), changes=batch)
    )

    retained = decision.current_state.lease
    assert decision.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert retained is not None and retained.pump_setpoint == original.pump_setpoint


def test_matching_actual_rpm_cannot_hide_external_configured_setpoint_change() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            pump_rpm=2900,
            configured_pump_rpm=2600,
        )
    )

    assert decision.reason_code == "runtime_ownership_preempted:pump_setpoint_external_change"


def test_verified_body_origin_survives_source_takeover_as_body_only_cleanup() -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    assert lease.originating_currentness is not None
    event = external_event(
        "pool.raw_heater_id",
        "H0002",
        "H0001",
        observed_at=NOW + timedelta(seconds=1),
    )

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=lease.thermal_plan_id,
            execution_currentness=lease.originating_currentness,
            heat_source=PhysicalHeatMode.GAS,
            source_observed_at=NOW + timedelta(seconds=1),
            changes=ExternalChangeBatch((event,)),
        )
    )

    assert decision.disposition is ThermalRuntimeOwnershipDisposition.PREEMPTED
    assert decision.reason_code == "runtime_ownership_preempted:source_external_change"
    residual = manager.residual_termination
    assert residual is not None
    assert residual.body_activation is not None
    assert residual.pump_setpoint is None
    assert residual.heat_source is None
    diagnostic = manager.last_terminal_transition
    assert diagnostic is not None
    assert diagnostic.affected_concept is ThermalRuntimeOwnedConcept.HEAT_SOURCE
    assert diagnostic.expected_value == "solar"
    assert diagnostic.observed_value == "gas"
    assert diagnostic.external_event_id == event.event_id


def test_matching_configured_setpoint_cannot_hide_actual_rpm_change() -> None:
    manager = ThermalRuntimeOwnershipManager()
    establish(manager, execution_ownership(pump_rpm=2900))

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            pump_rpm=2600,
            configured_pump_rpm=2900,
        )
    )

    assert decision.reason_code == "runtime_ownership_preempted:pump_external_change"


def test_duplicate_evidence_timestamp_is_idempotent_confirmation() -> None:
    manager = full_manager()

    first = manager.evaluate(evidence(at=NOW + timedelta(seconds=1)))
    second = manager.evaluate(evidence(at=NOW + timedelta(seconds=1)))

    assert first.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert second.disposition is ThermalRuntimeOwnershipDisposition.RETAINED
    assert second.current_state.lease == first.current_state.lease


def test_temporal_regression_preempts_owned_runtime_lease() -> None:
    manager = full_manager()
    manager.evaluate(evidence(at=NOW + timedelta(seconds=2)))

    decision = manager.evaluate(evidence(at=NOW + timedelta(seconds=1)))

    assert decision.reason_code == "runtime_ownership_preempted:evidence_temporal_regression"


def test_shared_hydraulic_inventory_must_be_explicitly_complete() -> None:
    manager = full_manager()

    decision = manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            circuit_inventory_complete=False,
        )
    )

    assert decision.reason_code == "runtime_ownership_preempted:shared_hydraulic_evidence_incomplete"


def test_runtime_ownership_models_are_command_free() -> None:
    manager = ThermalRuntimeOwnershipManager()

    assert manager.state.command_delivery_enabled is False
    assert not hasattr(manager, "deliver")
    assert not hasattr(manager, "execute")
    assert not hasattr(manager, "command")
