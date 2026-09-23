"""Adversarial shutdown matrix for selected source and body responsibility."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from poolos.circulation_successor import (
    CirculationArbitrationDisposition,
    CirculationSuccessorArbitrator,
    CirculationSuccessorKind,
)
from poolos.external_change import ExternalChangeBatch, ExternalChangeEvent
from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    ThermalBody,
)
from poolos.ownership_evidence import OwnershipDomain, PositiveOperatorEvidence
from poolos.thermal_source_cleanup import (
    ThermalSourceCleanupDisposition,
    ThermalSourceCleanupPolicy,
)
from poolos.thermal_termination import (
    ThermalTerminationDisposition,
    ThermalTerminationPolicy,
)
from poolos.thermal_circulation_cleanup import ThermalCirculationCleanupProvenance
from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from test_circulation_successor import _evidence as _circulation_evidence
from test_circulation_successor import _filtration, _grid
from test_thermal_termination import NOW, _entitlement, _evidence
from test_thermal_automatic_execution import (
    FakeDelivery,
    FakeDeliveryFactory,
    ThermalRequestedMode,
    _driver_with_residual_body_entitlement,
    _frame,
)
from poolos.filtration_policy import FiltrationDisposition


def _operator_source_event(source: PhysicalHeatMode, *, generation: int = 1):
    entitlement = _entitlement(source=None)
    requested_at = NOW + timedelta(milliseconds=100)
    return ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="00000",
        new_value={
            PhysicalHeatMode.OFF: "00000",
            PhysicalHeatMode.SOLAR: "H0002",
            PhysicalHeatMode.GAS: "H0001",
        }[source],
        observed_at=NOW + timedelta(milliseconds=200),
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id=f"operator-{source.value}",
            authority_generation=generation,
            body_session_id=entitlement.body_session_id or entitlement.lease_id,
            domain=OwnershipDomain.THERMAL,
            equipment_id="pool.raw_heater_id",
            requested_at=requested_at,
        ),
    )


@pytest.mark.parametrize("source", (PhysicalHeatMode.SOLAR, PhysicalHeatMode.GAS))
@pytest.mark.parametrize("source_owned", (False, True), ids=("body_cleanup", "thermal_owned"))
def test_selected_source_without_operator_intent_has_exact_off_reduction(
    source,
    source_owned,
):
    entitlement = _entitlement(source=source if source_owned else None)
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        _evidence(source=source),
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.operation is not None
    assert result.operation.mode is PhysicalHeatMode.OFF
    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.OWNED_SOURCE_OFF_REQUIRED
        if source_owned
        else ThermalSourceCleanupDisposition.BODY_SESSION_SOURCE_OFF_REQUIRED
    )
    assert result.source_cleanup.reactivation_possible_while_body_active
    assert not result.source_cleanup.source_cleanup_complete
    assert not result.source_cleanup.body_shutdown_source_safe


@pytest.mark.parametrize("source", (PhysicalHeatMode.SOLAR, PhysicalHeatMode.GAS))
def test_positive_operator_source_is_preserved_but_body_completion_remains_authorized(source):
    entitlement = _entitlement(source=None)
    evidence = _circulation_evidence(
        source=source,
        changes=ExternalChangeBatch((_operator_source_event(source),)),
    )
    termination = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert termination.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert termination.operation is None
    assert termination.source_cleanup is not None
    assert termination.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.OPERATOR_SELECTION_PRESERVED
    )
    assert termination.source_cleanup.operator_selection_preserved
    assert termination.source_cleanup.body_shutdown_source_safe
    assert not termination.source_cleanup.filtration_handoff_source_safe

    for disposition, debt, target in (
        (FiltrationDisposition.SATISFIED, timedelta(0), None),
        (FiltrationDisposition.DEFERRED_TOU, timedelta(hours=1), None),
        (FiltrationDisposition.RUN_NOW, timedelta(hours=1), 2600),
    ):
        filtration = _filtration(disposition, debt=debt, target=target)
        circulation = CirculationSuccessorArbitrator().evaluate(
            entitlement=entitlement,
            evidence=evidence,
            source_cleanup=termination.source_cleanup,
            filtration=filtration,
            outage=_grid(),
        )
        assert circulation.disposition is CirculationArbitrationDisposition.EXCLUSIVE_THERMAL, circulation.reason_code
        assert circulation.successor_kind is CirculationSuccessorKind.NONE
        assert circulation.body_deactivation_eligible
        assert not circulation.pump_handoff_eligible
        assert circulation.source_selection_preserved
        assert not circulation.source_cleanup_complete


def test_positive_operator_off_is_already_safe_and_needs_no_source_command():
    entitlement = _entitlement(source=None)
    evidence = _evidence(
        source=PhysicalHeatMode.OFF,
        changes=ExternalChangeBatch(
            (_operator_source_event(PhysicalHeatMode.OFF),)
        ),
    )
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.operation is None
    assert result.source_cleanup is not None
    assert result.source_cleanup.source_cleanup_complete
    assert result.source_cleanup.body_shutdown_source_safe
    assert result.source_cleanup.filtration_handoff_source_safe


def test_old_generation_operator_event_cannot_block_current_safe_reduction():
    entitlement = _entitlement(source=None)
    evidence = _evidence(
        source=PhysicalHeatMode.SOLAR,
        changes=ExternalChangeBatch(
            (_operator_source_event(PhysicalHeatMode.SOLAR, generation=99),)
        ),
    )
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.BODY_SESSION_SOURCE_OFF_REQUIRED
    )


def test_prior_operator_solar_event_cannot_preserve_later_unattributed_gas_selection():
    entitlement = _entitlement(source=None)
    evidence = _evidence(
        source=PhysicalHeatMode.GAS,
        changes=ExternalChangeBatch(
            (_operator_source_event(PhysicalHeatMode.SOLAR),)
        ),
    )
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.SOURCE_OFF_READY
    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.BODY_SESSION_SOURCE_OFF_REQUIRED
    )


def test_same_snapshot_selected_off_just_before_entitlement_is_current_for_cleanup():
    entitlement = _entitlement(source=None)
    evidence = _circulation_evidence(source=PhysicalHeatMode.OFF)
    evidence = replace(
        evidence,
        heat_source_observation_fresh=True,
        heat_source_observation_usable=True,
        heat_source_observed_at=NOW - timedelta(milliseconds=500),
    )
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is ThermalSourceCleanupDisposition.SELECTED_OFF
    assert result.source_cleanup.source_cleanup_complete
    assert result.source_cleanup.body_shutdown_source_safe


@pytest.mark.parametrize(
    "fresh,usable,observed_offset",
    (
        (False, True, 1),
        (True, False, 1),
        (True, True, -2),
    ),
    ids=("stale", "unusable", "pre_entitlement_off"),
)
def test_unusable_or_preboundary_source_evidence_cannot_authorize_cleanup(
    fresh,
    usable,
    observed_offset,
):
    entitlement = _entitlement(source=None)
    evidence = _circulation_evidence(source=PhysicalHeatMode.OFF)
    evidence = replace(
        evidence,
        heat_source_observation_fresh=fresh,
        heat_source_observation_usable=usable,
        heat_source_observed_at=NOW + timedelta(seconds=observed_offset),
    )
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.operation is None
    assert result.source_cleanup is not None
    assert not result.source_cleanup.body_shutdown_source_safe
    assert not result.source_cleanup.filtration_handoff_source_safe


def test_current_policy_source_requirement_cannot_be_unwound_as_cleanup():
    entitlement = _entitlement(source=None)
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        _evidence(source=PhysicalHeatMode.SOLAR),
        desired_source=PhysicalHeatMode.SOLAR,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.operation is None
    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.CURRENT_POLICY_REQUIRES_SOURCE
    )
    assert not result.source_cleanup.body_shutdown_source_safe


def test_pump_only_origin_cannot_synthesize_source_or_body_cleanup_authority():
    entitlement = _entitlement(body_owned=False, pump_owned=True, source=None)
    result = ThermalTerminationPolicy().evaluate(
        entitlement,
        _evidence(source=PhysicalHeatMode.SOLAR),
        desired_source=PhysicalHeatMode.OFF,
    )

    assert result.disposition is ThermalTerminationDisposition.RELINQUISH_ONLY
    assert result.operation is None
    assert result.source_cleanup is not None
    assert result.source_cleanup.disposition is (
        ThermalSourceCleanupDisposition.NO_SOURCE_CLEANUP_CAPABILITY
    )
    assert not result.source_cleanup.body_shutdown_source_safe


def test_selected_off_allows_immediate_filtration_handoff_only_with_real_provenance():
    entitlement = _entitlement(source=None)
    evidence = _circulation_evidence(source=PhysicalHeatMode.OFF)
    source = ThermalSourceCleanupPolicy().evaluate(
        entitlement,
        evidence,
        desired_source=PhysicalHeatMode.OFF,
    )
    result = CirculationSuccessorArbitrator().evaluate(
        entitlement=entitlement,
        evidence=evidence,
        source_cleanup=source,
        filtration=_filtration(
            FiltrationDisposition.RUN_NOW,
            debt=timedelta(hours=1),
            target=2600,
        ),
        outage=_grid(),
    )

    assert result.successor_kind is CirculationSuccessorKind.FILTRATION, result.reason_code
    assert result.pump_handoff_eligible
    assert result.filtration_handoff_source_safe
    assert result.source_cleanup_complete


def test_source_cleanup_assessment_is_required_for_owned_body_arbitration():
    result = CirculationSuccessorArbitrator().evaluate(
        entitlement=_entitlement(source=None),
        evidence=_circulation_evidence(source=PhysicalHeatMode.OFF),
        source_cleanup=None,
        filtration=_filtration(),
        outage=_grid(),
    )

    assert result.disposition is CirculationArbitrationDisposition.BLOCKED
    assert result.reason_code == "circulation_source_cleanup_assessment_unavailable"
    assert not result.body_deactivation_eligible
    assert not result.pump_handoff_eligible


@pytest.mark.parametrize(
    "source,raw",
    ((PhysicalHeatMode.SOLAR, "H0002"), (PhysicalHeatMode.GAS, "H0001")),
)
def test_runtime_preserves_operator_source_and_completes_owned_body_session(source, raw):
    orchestrator, driver, factory = _driver_with_residual_body_entitlement()
    residual = orchestrator.ownership.residual_termination
    assert residual is not None
    requested_at = NOW + timedelta(seconds=3)
    event = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="00000",
        new_value=raw,
        observed_at=requested_at,
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id=f"runtime-operator-{source.value}",
            authority_generation=residual.body_session_generation or residual.generation,
            body_session_id=residual.body_session_id or residual.lease_id,
            domain=OwnershipDomain.THERMAL,
            equipment_id="pool.raw_heater_id",
            requested_at=requested_at,
        ),
    )
    changes = ExternalChangeBatch((event,))

    captured = driver.process_epoch(
        _frame(
            orchestrator,
            NOW + timedelta(seconds=4),
            pool_active=True,
            pump_rpm=2600,
            configured_rpm=2600,
            pool_heater=raw,
            mode=ThermalRequestedMode.OFF,
            filtration_remaining=timedelta(hours=1),
            filtration_disposition=FiltrationDisposition.RUN_NOW,
            external_changes=changes,
        ),
        delivery_factory=factory,
    )
    result = asyncio.run(captured)
    assert result.runtime_ownership_summary["circulation_source_selection_preserved"]
    assert driver.cleanup_provenance is not None
    assert orchestrator.ownership.residual_termination is None
    before = len(factory.delivery.calls)

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=5),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater=raw,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(hours=1),
                filtration_disposition=FiltrationDisposition.RUN_NOW,
                external_changes=changes,
            ),
            delivery_factory=factory,
        )
    )
    assert result.state.value == "awaiting_cleanup_verification"
    assert len(factory.delivery.calls) == before + 1
    assert isinstance(factory.delivery.calls[-1], SetBodyActive)
    assert factory.delivery.calls[-1].active is False
    assert not any(isinstance(operation, SetHeatMode) for operation in factory.delivery.calls)

    final = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=6),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2600,
                pool_heater=raw,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(hours=1),
                filtration_disposition=FiltrationDisposition.RUN_NOW,
                external_changes=changes,
            ),
            delivery_factory=factory,
        )
    )
    assert final.blocker == "thermal_cleanup_pool_body_off_verified"
    assert driver.cleanup_provenance is None


def test_hot_tub_cleanup_preserves_operator_source_and_releases_only_owned_body():
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    entitlement = _entitlement(
        body=ThermalBody.HOT_TUB,
        source=None,
    )
    provenance = ThermalCirculationCleanupProvenance.from_residual(
        entitlement,
        established_at=NOW + timedelta(seconds=1),
    )
    assert provenance is not None
    driver.cleanup_provenance = provenance
    requested_at = NOW + timedelta(seconds=2)
    operator_gas = ExternalChangeEvent(
        concept="spa.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1201",
        previous_value="00000",
        new_value="H0001",
        observed_at=requested_at,
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id="operator-hot-tub-gas",
            authority_generation=provenance.body_session_generation or provenance.generation,
            body_session_id=provenance.body_session_id or provenance.lease_id,
            domain=OwnershipDomain.THERMAL,
            equipment_id="spa.raw_heater_id",
            requested_at=requested_at,
        ),
    )

    requested = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=True,
                spa_heater="H0001",
                mode=ThermalRequestedMode.OFF,
                external_changes=ExternalChangeBatch((operator_gas,)),
            ),
            delivery_factory=factory,
        )
    )

    assert requested.state.value == "awaiting_cleanup_verification"
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetBodyActive)
    assert delivery.calls[0].equipment_id == ThermalBody.HOT_TUB.value
    assert delivery.calls[0].active is False
    assert not any(isinstance(operation, SetHeatMode) for operation in delivery.calls)
