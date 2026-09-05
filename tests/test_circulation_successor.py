from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from poolos.circulation_successor import (
    CirculationArbitrationDisposition,
    CirculationOrigin,
    CirculationSuccessorArbitrator,
    CirculationSuccessorKind,
    FiltrationSuccessorEvidence,
    FiltrationTargetSemantics,
)
from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    THERMAL_RUNTIME_TAKEOVER_CONCEPTS,
    ThermalRuntimeExternalChangeEvidence,
)
from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationDisposition,
    FiltrationObservation,
)
from poolos.grid_outage_confirmation import (
    GridOutageAssessment,
    GridOutageConfirmationTracker,
    GridOutageDisposition,
)
from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation
from poolos.thermal_live_execution import ThermalLiveExecutionContext
from poolos.thermal_runtime_ownership import (
    SharedHydraulicCircuitEvidence,
    SharedHydraulicSafetyClass,
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipEvidence,
)


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
AT = NOW + timedelta(seconds=1)


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
    source_owned: bool = True,
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
            _provenance(ThermalRuntimeOwnedConcept.BODY_ACTIVATION, True) if body_owned else None
        ),
        pump_setpoint=(
            _provenance(ThermalRuntimeOwnedConcept.PUMP_SETPOINT, 2900) if pump_owned else None
        ),
        heat_source=(
            _provenance(ThermalRuntimeOwnedConcept.HEAT_SOURCE, PhysicalHeatMode.SOLAR)
            if source_owned
            else None
        ),
    )


def _circuits(
    *,
    active: str | None = None,
    stale: str | None = None,
) -> tuple[SharedHydraulicCircuitEvidence, ...]:
    return tuple(
        SharedHydraulicCircuitEvidence(
            concept=concept,
            active=concept == active,
            fresh=concept != stale,
            usable=concept != stale,
            safety_class=SharedHydraulicSafetyClass.CONFLICTING,
            observed_at=AT,
        )
        for concept in ("waterfall.active", "jets.active", "slide.active")
    )


def _evidence(
    *,
    pool_active: bool | None = True,
    spa_active: bool | None = False,
    observed_at: datetime = AT,
    fresh: bool = True,
    usable: bool = True,
    source: PhysicalHeatMode = PhysicalHeatMode.OFF,
    circuits: tuple[SharedHydraulicCircuitEvidence, ...] | None = None,
    changes: ExternalChangeBatch = ExternalChangeBatch(()),
    pump_rpm: int = 2900,
    configured_rpm: int = 2900,
) -> ThermalRuntimeOwnershipEvidence:
    return ThermalRuntimeOwnershipEvidence(
        evaluated_at=AT,
        current_context=ThermalLiveExecutionContext("evaluation-2", "plan-2"),
        requested_mode="Off",
        pool_active=pool_active,
        spa_active=spa_active,
        pool_activity_fresh=fresh,
        spa_activity_fresh=fresh,
        pool_activity_usable=usable,
        spa_activity_usable=usable,
        pool_activity_observed_at=observed_at,
        spa_activity_observed_at=observed_at,
        pump_rpm=pump_rpm,
        pump_observation_fresh=fresh,
        pump_observation_usable=usable,
        pump_observed_at=observed_at,
        configured_pump_speed_rpm=configured_rpm,
        configured_pump_speed_observation_fresh=fresh,
        configured_pump_speed_observation_usable=usable,
        configured_pump_speed_observed_at=observed_at,
        effective_heat_source=source,
        heat_source_observation_fresh=fresh,
        heat_source_observation_usable=usable,
        heat_source_observed_at=observed_at,
        external_changes=changes,
        shared_hydraulic_circuits=_circuits() if circuits is None else circuits,
        shared_hydraulic_inventory_complete=True,
    )


def _filtration(
    disposition: FiltrationDisposition = FiltrationDisposition.SATISFIED,
    *,
    debt: timedelta = timedelta(0),
    target: int | None = None,
    evaluated_at: datetime = AT,
) -> FiltrationSuccessorEvidence:
    immediate = disposition in {
        FiltrationDisposition.CREDITING,
        FiltrationDisposition.RUN_NOW,
    }
    return FiltrationSuccessorEvidence(
        evaluated_at=evaluated_at,
        disposition=disposition,
        total_remaining_runtime=debt,
        currently_earning_credit=disposition is FiltrationDisposition.CREDITING,
        immediate_circulation_required=immediate,
        successor_target_rpm=target,
        target_semantics=(
            FiltrationTargetSemantics.ORDINARY_POLICY_BASELINE
            if target is not None
            else FiltrationTargetSemantics.NONE
        ),
    )


def _grid(*, off_grid: bool = False) -> GridOutageAssessment:
    observation = PoolObservation(
        observation_id="grid.outage_active",
        value=off_grid,
        observed_at=AT,
        source_kind=ObservationSourceKind.LIVE,
        source_id="ha:grid",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )
    return GridOutageConfirmationTracker().evaluate(observation, evaluated_at=AT)


def _evaluate(
    *,
    entitlement: ThermalResidualTerminationEntitlement | None = None,
    evidence: ThermalRuntimeOwnershipEvidence | None = None,
    filtration: FiltrationSuccessorEvidence | None = None,
    outage: GridOutageAssessment | None = None,
):
    return CirculationSuccessorArbitrator().evaluate(
        entitlement=_entitlement() if entitlement is None else entitlement,
        evidence=_evidence() if evidence is None else evidence,
        filtration=_filtration() if filtration is None else filtration,
        outage=_grid() if outage is None else outage,
    )


def test_poolos_cold_start_can_be_command_free_future_eligible() -> None:
    result = _evaluate()

    assert result.disposition is CirculationArbitrationDisposition.EXCLUSIVE_THERMAL
    assert result.circulation_origin is CirculationOrigin.POOLOS_THERMAL
    assert result.successor_kind is CirculationSuccessorKind.NONE
    assert result.body_deactivation_eligible
    assert not result.keep_body_active
    assert not result.command_delivery_enabled


@pytest.mark.parametrize("entitlement", [None, _entitlement(body_owned=False)])
def test_no_body_provenance_is_retained_as_preexisting_or_external(
    entitlement: ThermalResidualTerminationEntitlement | None,
) -> None:
    result = CirculationSuccessorArbitrator().evaluate(
        entitlement=entitlement,
        evidence=_evidence(),
        filtration=_filtration(),
        outage=_grid(),
    )

    assert result.disposition is CirculationArbitrationDisposition.RETAIN_PREEXISTING
    assert result.successor_kind is CirculationSuccessorKind.PREEXISTING_OR_EXTERNAL
    assert result.keep_body_active
    assert not result.body_deactivation_eligible


def test_pump_or_source_provenance_cannot_manufacture_body_origin() -> None:
    result = _evaluate(entitlement=_entitlement(body_owned=False))

    assert result.body_activation_provenance_present is False
    assert result.circulation_origin is CirculationOrigin.PREEXISTING_OR_EXTERNAL
    assert result.pump_handoff_eligible is False


@pytest.mark.parametrize(
    "disposition",
    [FiltrationDisposition.RUN_NOW, FiltrationDisposition.CREDITING],
)
def test_immediate_filtration_is_a_typed_successor(
    disposition: FiltrationDisposition,
) -> None:
    result = _evaluate(filtration=_filtration(disposition, debt=timedelta(hours=2), target=2600))

    assert result.successor_kind is CirculationSuccessorKind.FILTRATION
    assert result.filtration_debt_present is True
    assert result.filtration_immediate_need is True
    assert result.filtration_target_rpm == 2600
    assert result.pump_handoff_eligible
    assert result.physical_handoff_ready
    assert result.keep_body_active
    assert not result.command_delivery_enabled


@pytest.mark.parametrize(
    "disposition",
    [
        FiltrationDisposition.DEFERRED_TOU,
        FiltrationDisposition.DEFERRED_OPTIMIZATION,
        FiltrationDisposition.DEFERRED_HIGHER_PRIORITY,
    ],
)
def test_deferred_debt_is_not_immediate_filtration(
    disposition: FiltrationDisposition,
) -> None:
    result = _evaluate(filtration=_filtration(disposition, debt=timedelta(hours=2)))

    assert result.filtration_debt_present is True
    assert result.filtration_immediate_need is False
    assert result.successor_kind is CirculationSuccessorKind.NONE
    assert result.body_deactivation_eligible


def test_latest_satisfied_filtration_truth_does_not_retain_stale_debt() -> None:
    previous = _evaluate(
        filtration=_filtration(
            FiltrationDisposition.RUN_NOW,
            debt=timedelta(hours=1),
            target=2600,
        )
    )
    current = _evaluate(filtration=_filtration(FiltrationDisposition.SATISFIED))

    assert previous.successor_kind is CirculationSuccessorKind.FILTRATION
    assert current.successor_kind is CirculationSuccessorKind.NONE
    assert current.body_deactivation_eligible


def test_filtration_successor_without_target_retains_body_but_not_pump_handoff() -> None:
    result = _evaluate(
        filtration=_filtration(
            FiltrationDisposition.RUN_NOW,
            debt=timedelta(hours=1),
        )
    )

    assert result.successor_kind is CirculationSuccessorKind.FILTRATION
    assert result.filtration_target_semantics is FiltrationTargetSemantics.NONE
    assert not result.pump_handoff_eligible
    assert not result.physical_handoff_ready


def test_unavailable_filtration_evidence_blocks_exclusive_release() -> None:
    result = _evaluate(
        filtration=_filtration(
            FiltrationDisposition.EVIDENCE_UNAVAILABLE,
            debt=timedelta(hours=6),
        )
    )

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert not result.body_deactivation_eligible


@pytest.mark.parametrize("concept", ["waterfall.active", "jets.active", "slide.active"])
def test_shared_hydraulic_consumers_retain_circulation(concept: str) -> None:
    result = _evaluate(evidence=_evidence(circuits=_circuits(active=concept)))

    assert result.successor_kind is CirculationSuccessorKind.SHARED_HYDRAULICS
    assert result.shared_hydraulic_blocker == concept
    assert result.keep_body_active
    assert not result.body_deactivation_eligible


def test_pool_light_is_not_a_shared_hydraulic_successor() -> None:
    evidence = _evidence()
    light = SharedHydraulicCircuitEvidence(
        concept="pool_light.active",
        active=True,
        fresh=True,
        usable=True,
        safety_class=SharedHydraulicSafetyClass.NON_CONFLICTING,
        observed_at=AT,
    )
    result = _evaluate(
        evidence=replace(
            evidence,
            shared_hydraulic_circuits=(*evidence.shared_hydraulic_circuits, light),
        )
    )

    assert result.successor_kind is CirculationSuccessorKind.NONE
    assert result.body_deactivation_eligible


def test_unusable_pool_light_does_not_block_shared_hydraulic_currentness() -> None:
    evidence = _evidence()
    light = SharedHydraulicCircuitEvidence(
        concept="pool_light.active",
        active=True,
        fresh=False,
        usable=False,
        safety_class=SharedHydraulicSafetyClass.NON_CONFLICTING,
        observed_at=AT - timedelta(hours=1),
    )
    result = _evaluate(
        evidence=replace(
            evidence,
            shared_hydraulic_circuits=(*evidence.shared_hydraulic_circuits, light),
        )
    )

    assert result.successor_kind is CirculationSuccessorKind.NONE
    assert result.shared_hydraulic_evidence_current
    assert result.body_deactivation_eligible


def test_missing_shared_hydraulic_inventory_fails_closed() -> None:
    result = _evaluate(
        evidence=replace(
            _evidence(),
            shared_hydraulic_circuits=(),
            shared_hydraulic_inventory_complete=True,
        )
    )

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert not result.body_deactivation_eligible


@pytest.mark.parametrize(
    ("pool_active", "spa_active"),
    [(False, False), (False, True), (True, True)],
)
def test_unsafe_pool_spa_topology_blocks(pool_active: bool, spa_active: bool) -> None:
    result = _evaluate(evidence=_evidence(pool_active=pool_active, spa_active=spa_active))

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert result.successor_kind is CirculationSuccessorKind.SPA_OR_TOPOLOGY
    assert not result.body_deactivation_eligible


@pytest.mark.parametrize("field", ["pool", "spa", "shared", "filtration"])
def test_stale_embedded_critical_fact_blocks_exclusivity(field: str) -> None:
    evidence = _evidence()
    filtration = _filtration()
    if field == "pool":
        evidence = replace(evidence, pool_activity_fresh=False)
    elif field == "spa":
        evidence = replace(evidence, spa_activity_fresh=False)
    elif field == "shared":
        evidence = replace(evidence, shared_hydraulic_circuits=_circuits(stale="jets.active"))
    else:
        filtration = _filtration(evaluated_at=NOW)

    result = _evaluate(evidence=evidence, filtration=filtration)

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert not result.body_deactivation_eligible


def test_future_and_pre_entitlement_observation_timestamps_fail_closed() -> None:
    future = _evaluate(evidence=_evidence(observed_at=AT + timedelta(seconds=1)))
    old = _evaluate(evidence=_evidence(observed_at=NOW - timedelta(seconds=1)))

    assert future.disposition is CirculationArbitrationDisposition.BLOCKED
    assert old.disposition is CirculationArbitrationDisposition.BLOCKED


@pytest.mark.parametrize(
    "concept",
    ["pool.active", "pump.rpm", "pool.raw_heater_id", "waterfall.active"],
)
def test_external_takeover_defeats_thermal_exclusivity(concept: str) -> None:
    event = ExternalChangeEvent(
        concept=concept,
        semantic_event_type="native_value_changed",
        native_object_id="p0101",
        previous_value=2900,
        new_value=2600,
        observed_at=AT,
        external_policy="reconcile",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=True,
    )
    result = _evaluate(evidence=_evidence(changes=ExternalChangeBatch((event,))))

    assert result.external_takeover
    assert result.disposition is CirculationArbitrationDisposition.RETAIN_PREEXISTING
    assert not result.body_deactivation_eligible


def test_transient_spa_takeover_defeats_later_matching_pool_topology() -> None:
    event = ExternalChangeEvent(
        concept="spa.active",
        semantic_event_type="native_value_changed",
        native_object_id="B1202",
        previous_value=False,
        new_value=True,
        observed_at=NOW,
        external_policy="accept",
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )
    result = _evaluate(
        evidence=_evidence(
            pool_active=True,
            spa_active=False,
            changes=ExternalChangeBatch((event,)),
        )
    )

    assert result.external_takeover
    assert result.disposition is CirculationArbitrationDisposition.RETAIN_PREEXISTING
    assert not result.body_deactivation_eligible


def test_prelease_takeover_event_does_not_invalidate_newer_entitlement() -> None:
    entitlement = _entitlement()
    event = ExternalChangeEvent(
        concept="pool.active",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value=False,
        new_value=True,
        observed_at=(
            entitlement.originating_lease_established_at - timedelta(seconds=1)
        ),
        external_policy="accept",
        action_taken="accepted_native_value",
        notification_recommended=True,
        reconciliation_required=False,
    )
    result = _evaluate(
        entitlement=entitlement,
        evidence=_evidence(changes=ExternalChangeBatch((event,))),
    )

    assert not result.external_takeover
    assert result.disposition is CirculationArbitrationDisposition.EXCLUSIVE_THERMAL
    assert result.body_deactivation_eligible


def _change_event(concept: str, *, at: datetime = NOW) -> ExternalChangeEvent:
    return ExternalChangeEvent(
        concept=concept,
        semantic_event_type="native_value_changed",
        native_object_id="native-1",
        previous_value=False,
        new_value=True,
        observed_at=at,
        external_policy="accept",
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )


def test_bounded_takeover_retention_survives_empty_and_unrelated_batches() -> None:
    retained = ThermalRuntimeExternalChangeEvidence()
    takeover = _change_event("pool.active")

    first = retained.update(ExternalChangeBatch((takeover,)))
    empty = retained.update(ExternalChangeBatch(()))
    unrelated = retained.update(
        ExternalChangeBatch(
            (_change_event("pool.target_temperature", at=AT),)
        )
    )
    after_unrelated = retained.update(ExternalChangeBatch(()))

    assert first.events == (takeover,)
    assert empty.events == (takeover,)
    assert {item.concept for item in unrelated.events} == {
        "pool.active",
        "pool.target_temperature",
    }
    assert after_unrelated.events == (takeover,)


def test_later_same_concept_transition_does_not_erase_first_takeover() -> None:
    retained = ThermalRuntimeExternalChangeEvidence()
    takeover = _change_event("pool.active", at=NOW)
    later = _change_event("pool.active", at=AT)

    retained.update(ExternalChangeBatch((takeover,)))
    current = retained.update(ExternalChangeBatch((later,)))

    assert current.events == (takeover,)
    assert retained.retained_count == 1


def test_correlated_consequence_does_not_erase_retained_takeover() -> None:
    retained = ThermalRuntimeExternalChangeEvidence()
    takeover = _change_event("pump.rpm")
    correlation = object()

    retained.update(ExternalChangeBatch((takeover,)))
    current = retained.update(
        ExternalChangeBatch((), (correlation,))  # type: ignore[arg-type]
    )

    assert current.events == (takeover,)
    assert current.correlated_consequences == (correlation,)


def test_retained_takeover_evidence_is_bounded_and_resettable() -> None:
    retained = ThermalRuntimeExternalChangeEvidence()

    for index, concept in enumerate(sorted(THERMAL_RUNTIME_TAKEOVER_CONCEPTS)):
        retained.update(
            ExternalChangeBatch(
                (
                    _change_event(
                        concept,
                        at=NOW + timedelta(milliseconds=index),
                    ),
                )
            )
        )

    for index in range(50):
        retained.update(
            ExternalChangeBatch(
                (
                    _change_event(
                        f"unrelated.{index}",
                        at=AT + timedelta(milliseconds=index),
                    ),
                )
            )
        )

    settled = retained.update(ExternalChangeBatch(()))

    assert retained.retained_count == len(THERMAL_RUNTIME_TAKEOVER_CONCEPTS)
    assert len(settled.events) == len(THERMAL_RUNTIME_TAKEOVER_CONCEPTS)

    retained.reset()

    assert retained.retained_count == 0
    assert retained.update(ExternalChangeBatch(())).events == ()


def test_latest_filtration_state_can_become_immediate_during_thermal() -> None:
    deferred = _evaluate(
        filtration=_filtration(
            FiltrationDisposition.DEFERRED_TOU,
            debt=timedelta(hours=1),
        )
    )
    due = _evaluate(
        filtration=_filtration(
            FiltrationDisposition.RUN_NOW,
            debt=timedelta(hours=1),
            target=2600,
        )
    )

    assert deferred.filtration_immediate_need is False
    assert due.successor_kind is CirculationSuccessorKind.FILTRATION


def test_matching_hardware_after_restart_does_not_reconstruct_ownership() -> None:
    result = CirculationSuccessorArbitrator().evaluate(
        entitlement=None,
        evidence=_evidence(pump_rpm=2900, configured_rpm=2900),
        filtration=_filtration(),
        outage=_grid(),
    )

    assert result.circulation_origin is CirculationOrigin.PREEXISTING_OR_EXTERNAL
    assert not result.body_deactivation_eligible


@pytest.mark.parametrize(
    "outage",
    [
        None,
        _grid(off_grid=True),
        replace(_grid(), disposition=GridOutageDisposition.CONFIRMED_OUTAGE),
        replace(_grid(), disposition=GridOutageDisposition.UNKNOWN),
    ],
)
def test_only_current_on_grid_evidence_allows_positive_eligibility(
    outage: GridOutageAssessment | None,
) -> None:
    result = CirculationSuccessorArbitrator().evaluate(
        entitlement=_entitlement(),
        evidence=_evidence(),
        filtration=_filtration(),
        outage=outage,
    )

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert not result.body_deactivation_eligible


def test_current_on_grid_evidence_is_reported_and_permits_exclusivity() -> None:
    result = _evaluate()

    assert result.grid_disposition is GridOutageDisposition.ON_GRID
    assert result.grid_evidence_current
    assert result.critical_evidence_current


def test_hot_tub_remains_fail_closed() -> None:
    result = _evaluate(entitlement=_entitlement(body=ThermalBody.HOT_TUB))

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert result.reason_code == "circulation_hot_tub_not_commissioned"


def test_source_off_is_required_but_does_not_create_body_origin() -> None:
    source_on = _evaluate(evidence=_evidence(source=PhysicalHeatMode.SOLAR))
    no_body = _evaluate(entitlement=_entitlement(body_owned=False))

    assert source_on.disposition is CirculationArbitrationDisposition.BLOCKED
    assert no_body.source_cleanup_complete
    assert not no_body.body_deactivation_eligible


def test_pump_handoff_requires_current_owned_pump_provenance() -> None:
    filtration = _filtration(
        FiltrationDisposition.RUN_NOW,
        debt=timedelta(hours=1),
        target=2600,
    )
    no_pump = _evaluate(entitlement=_entitlement(pump_owned=False), filtration=filtration)
    stale_pump = _evaluate(
        evidence=replace(_evidence(), pump_observation_fresh=False),
        filtration=filtration,
    )

    assert not no_pump.pump_handoff_eligible
    assert not stale_pump.pump_handoff_eligible


def test_repeated_arbitration_is_pure_and_does_not_consume_entitlement() -> None:
    entitlement = _entitlement()
    evidence = _evidence()
    filtration = _filtration()
    policy = CirculationSuccessorArbitrator()

    first = policy.evaluate(
        entitlement=entitlement,
        evidence=evidence,
        filtration=filtration,
        outage=_grid(),
    )
    second = policy.evaluate(
        entitlement=entitlement,
        evidence=evidence,
        filtration=filtration,
        outage=_grid(),
    )

    assert first == second
    assert entitlement == _entitlement()
    assert filtration == _filtration()
    assert first.command_delivery_enabled is False


def test_filtration_evidence_adapter_preserves_canonical_state() -> None:
    from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE

    tracker = FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)
    snapshot = tracker.observe(
        # No circulation and an outstanding minimum yields the policy's current decision.
        FiltrationObservation(
            observed_at=AT,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
            water_temperature_f=80,
            circulation_evidence_usable=True,
            temperature_evidence_usable=True,
        ),
        safely_deferrable=False,
    )
    assert snapshot is not None

    evidence = FiltrationSuccessorEvidence.from_accounting(snapshot)

    assert evidence.disposition is snapshot.disposition
    assert evidence.total_remaining_runtime == snapshot.total_remaining_runtime
    assert evidence.successor_target_rpm == snapshot.ordinary_filtration_rpm
    assert evidence.command_delivery_enabled is False
