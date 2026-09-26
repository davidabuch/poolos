"""ADR-110 regressions through existing ownership and delivery lifecycles."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from poolos.integration import PhysicalHeatMode
from poolos.external_change import ExternalChangeBatch, ExternalChangeEvent
from poolos.ownership_evidence import (
    OwnershipAuthority, OwnershipDomain, OwnershipHealth, PositiveOperatorEvidence,
)
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus

from test_filtration_automatic_execution import (
    NOW as FILTRATION_NOW,
    _frame,
    _verified_filtration_driver,
)
from test_thermal_runtime_ownership import NOW, evidence, external_event, verified_full_manager
from test_thermal_automatic_execution import _frame as thermal_frame
from test_thermal_automatic_execution import FakeDelivery, FakeDeliveryFactory, StructuredCommandLedger
from poolos.thermal_automatic_execution import ThermalAutomaticExecutionDriver
from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator
from poolos.filtration_policy import FiltrationDisposition
from poolos.integration import SetBodyActive, SetHeatMode, SetPumpSpeed
from poolos.pump_speed_session import PumpSpeedNativeTransition, PumpSpeedSessionRuntime, PumpSpeedOverrideState
from test_pump_speed_session import BASELINES as PUMP_BASELINES, NOW as PUMP_NOW, evidence as pump_evidence, verified_manual
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from poolos.thermal_runtime_assessment import ThermalRequestedMode
from poolos.pool_circulation_ownership import PoolCirculationOwner


@pytest.mark.parametrize("manual_override", [False, True])
def test_established_configured_speed_override_and_exact_baseline_handback(
    manual_override: bool,
) -> None:
    runtime = PumpSpeedSessionRuntime(PUMP_BASELINES)
    runtime.observe(pump_evidence())
    if manual_override:
        verified_manual(runtime)
    before = runtime.snapshot
    runtime.apply_transition(PumpSpeedNativeTransition(
        concept="pool.pump_circuit.configured_speed_rpm", native_object_id="p0102",
        previous_rpm=before.effective_rpm, new_rpm=2650 if manual_override else 3200,
        observed_at=PUMP_NOW + timedelta(seconds=4),
    ))
    if manual_override:
        assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
        assert runtime.snapshot.effective_rpm == 2650
    else:
        assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
        assert runtime.snapshot.effective_rpm == 3200


def test_solar_preparation_and_actual_engagement_have_distinct_rpm_requirements() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    preparing = thermal_frame(orchestrator, at=NOW, pool_active=True, pump_rpm=2600,
                              solar_active=False, mode=ThermalRequestedMode.SOLAR)
    assert preparing.thermal is not None
    assert preparing.thermal.pool.plan.desired.required_pump_rpm == 2600
    engaged = thermal_frame(orchestrator, at=NOW + timedelta(seconds=1),
                           pool_active=True, pump_rpm=2600, solar_active=True,
                           pool_heater="H0002", mode=ThermalRequestedMode.SOLAR)
    assert engaged.thermal is not None
    assert engaged.thermal.pool.plan.desired.required_pump_rpm == 2900


@pytest.mark.parametrize("native_disengagement", [False, True])
@pytest.mark.parametrize("native_settling", [False, True])
def test_autonomous_solar_body_origin_survives_engagement_and_final_shutdown(
    native_disengagement: bool, native_settling: bool,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    ledger = StructuredCommandLedger()
    delivery = FakeDelivery(ledger=ledger)
    factory = FakeDeliveryFactory(delivery, driver=driver)
    thermal_frame(ThermalRuntimeOrchestrator(), NOW - timedelta(seconds=1),
                  pool_active=True, pump_rpm=2600, evaluator=evaluator,
                  mode=ThermalRequestedMode.SOLAR)
    physical = dict(pool_active=False, pump_rpm=0, configured_rpm=2600,
                    pool_heater="00000", solar_active=False)
    baseline = thermal_frame(orchestrator, NOW, evaluator=evaluator,
                             mode=ThermalRequestedMode.SOLAR, **physical)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    body_origin = None
    solar_owned = False
    history = []
    changes = ExternalChangeBatch(())
    settling: list[int] = []
    for seconds in range(1, 751):
        if settling:
            physical["pump_rpm"] = settling.pop(0)
        if native_disengagement and seconds == 121:
            physical["solar_active"] = False
            physical["pump_rpm"] = 3200
            changes = ExternalChangeBatch((external_event(
                "pump.rpm", 2900, 3200, observed_at=NOW + timedelta(seconds=121),
            ),))
        prior_count = len(delivery.calls)
        frame = thermal_frame(
            orchestrator, NOW + timedelta(seconds=seconds), evaluator=evaluator,
            driver=driver, mode=ThermalRequestedMode.SOLAR,
            verification_timeout=timedelta(seconds=120),
            pool_temperature=100 if seconds >= 125 else 80,
            filtration_remaining=timedelta(0),
            filtration_disposition=FiltrationDisposition.SATISFIED,
            external_changes=changes,
            command_ledger=ledger, **physical,
        )
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        history.append((seconds, result.state.value, result.blocker))
        lease = orchestrator.ownership.state.lease
        if lease is not None and lease.owns_body_activation:
            body_origin = body_origin or lease.body_activation
            assert lease.body_activation == body_origin
        if seconds == 120:
            assert lease is not None and lease.owns_body_activation, history
            assert lease.owns_pump_setpoint and lease.owns_heat_source, history
            assert lease.domain_state(OwnershipDomain.PUMP).health is OwnershipHealth.STABLE
            assert physical["solar_active"] and physical["pump_rpm"] == 2900, history[-10:]
            solar_owned = True
        for operation in delivery.calls[prior_count:]:
            if isinstance(operation, SetBodyActive):
                physical["pool_active"] = operation.active
                if not operation.active:
                    physical["pump_rpm"] = 0
                    physical["solar_active"] = False
            elif isinstance(operation, SetPumpSpeed):
                if operation.rpm == 2900:
                    assert physical["solar_active"], history
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm
                if native_settling and operation.rpm == 2900:
                    settling = [3450, 3000, 2880, 2900]
            elif isinstance(operation, SetHeatMode):
                physical["pool_heater"] = {
                    PhysicalHeatMode.OFF: "00000", PhysicalHeatMode.SOLAR: "H0002",
                    PhysicalHeatMode.GAS: "H0001",
                }[operation.mode]
                physical["solar_active"] = operation.mode is PhysicalHeatMode.SOLAR
    assert solar_owned
    assert physical["pool_active"] is False, (history[-3:], frame.thermal.pool.plan.desired)
    assert physical["pump_rpm"] == 0, history
    assert physical["pool_heater"] == "00000", history
    assert driver.cleanup_attempt is None
    assert driver.cleanup_provenance is None
    assert orchestrator.ownership.residual_termination is None
    ledger.assert_complete()


@pytest.mark.parametrize("domain,concept,value", [
    (OwnershipDomain.PUMP, "pump.rpm", 3200),
    (OwnershipDomain.THERMAL, "pool.raw_heater_id", "H0001"),
])
@pytest.mark.parametrize("positive_intent", [False, True])
def test_same_contradiction_yields_only_with_positive_domain_intent(
    domain: OwnershipDomain, concept: str, value: int | str, positive_intent: bool,
) -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None and lease.body_session_id is not None
    assert lease.body_session_generation is not None
    event = external_event(concept, 2900 if domain is OwnershipDomain.PUMP else "H0002", value)
    if positive_intent:
        event = replace(event, positive_operator_evidence=PositiveOperatorEvidence(
            "explicit-operator-request", lease.body_session_generation,
            lease.body_session_id, domain, concept, NOW + timedelta(seconds=1),
        ))
    manager.evaluate(evidence(
        at=NOW + timedelta(seconds=1), plan_id=lease.thermal_plan_id,
        execution_currentness=lease.originating_currentness,
        pump_rpm=3200 if domain is OwnershipDomain.PUMP else 2900,
        heat_source=PhysicalHeatMode.GAS if domain is OwnershipDomain.THERMAL else PhysicalHeatMode.SOLAR,
        changes=ExternalChangeBatch((event,)),
    ))
    after = manager.state.lease
    assert after is not None
    assert after.status is ThermalRuntimeOwnershipStatus.OWNED
    assert after.body_activation == lease.body_activation
    assert after.domain_state(OwnershipDomain.BODY).authority is OwnershipAuthority.POOLOS
    other = OwnershipDomain.PUMP if domain is OwnershipDomain.THERMAL else OwnershipDomain.THERMAL
    assert after.domain_state(other).authority is OwnershipAuthority.POOLOS
    assert after.domain_state(domain).authority is (
        OwnershipAuthority.OPERATOR if positive_intent else OwnershipAuthority.POOLOS
    )
    if not positive_intent:
        assert after.domain_state(domain).health is OwnershipHealth.RECONCILING


@pytest.mark.parametrize("rpm", [3450, 3000, 2550, 3200])
def test_unattributed_pump_drift_preserves_owned_body_lifecycle(rpm: int) -> None:
    manager = verified_full_manager()
    before = manager.state.lease
    assert before is not None
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=before.thermal_plan_id,
            execution_currentness=before.originating_currentness,
            pump_rpm=rpm,
        )
    )
    after = manager.state.lease
    assert after is not None
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert after.body_activation == before.body_activation
    assert after.pump_setpoint == before.pump_setpoint
    assert after.heat_source == before.heat_source


def test_unattributed_source_drift_preserves_owned_body_lifecycle() -> None:
    manager = verified_full_manager()
    before = manager.state.lease
    assert before is not None
    manager.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            plan_id=before.thermal_plan_id,
            execution_currentness=before.originating_currentness,
            heat_source=PhysicalHeatMode.OFF,
        )
    )
    after = manager.state.lease
    assert after is not None
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert after.body_activation == before.body_activation
    assert after.pump_setpoint == before.pump_setpoint
    assert after.heat_source == before.heat_source


def test_filtration_shutdown_requires_observed_actual_pump_zero() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    lease = driver.ownership.filtration_lease
    stopping = asyncio.run(driver.process_epoch(
        _frame(FILTRATION_NOW + timedelta(seconds=5), pool=True, rpm=2600,
               configured=2600, satisfied=True), delivery_factory=factory,
    ))
    assert stopping.command_delivery_performed
    count = len(delivery.operations)
    pending = asyncio.run(driver.process_epoch(
        _frame(FILTRATION_NOW + timedelta(seconds=6), pool=False, rpm=900,
               configured=2600, satisfied=True), delivery_factory=factory,
    ))
    assert pending.blocker != "automatic_filtration_pool_off_verified"
    retained = driver.ownership.filtration_lease
    assert retained is not None and lease is not None
    assert retained.lease_id == lease.lease_id
    assert retained.body_activation == lease.body_activation
    assert retained.pump_setpoint == lease.pump_setpoint
    assert len(delivery.operations) == count
    stopped = asyncio.run(driver.process_epoch(
        _frame(FILTRATION_NOW + timedelta(seconds=7), pool=False, rpm=0,
               configured=2600, satisfied=True), delivery_factory=factory,
    ))
    assert stopped.blocker == "automatic_filtration_pool_off_verified"
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == count


@pytest.mark.parametrize("positive_intent", [False, True])
def test_filtration_pump_disturbance_preserves_body_and_respects_operator(positive_intent: bool) -> None:
    driver, delivery, factory = _verified_filtration_driver()
    lease = driver.ownership.filtration_lease
    assert lease is not None
    at = FILTRATION_NOW + timedelta(seconds=3)
    event = external_event("pump.rpm", 2600, 2550, observed_at=at)
    if positive_intent:
        event = replace(event, positive_operator_evidence=PositiveOperatorEvidence(
            "explicit-filtration-pump-request", lease.generation, lease.session_id,
            OwnershipDomain.PUMP, lease.pool_pump_circuit_id, at,
        ))
    count = len(delivery.operations)
    result = asyncio.run(driver.process_epoch(
        _frame(at, pool=True, rpm=2550, configured=2600,
               changes=ExternalChangeBatch((event,))), delivery_factory=factory,
    ))
    after = driver.ownership.filtration_lease
    assert after is not None
    assert after.body_activation == lease.body_activation
    assert len(delivery.operations) == count + (0 if positive_intent else 1)
    if not positive_intent:
        assert isinstance(delivery.operations[-1], SetPumpSpeed)
        assert delivery.operations[-1].rpm == 2600
        assert result.command_delivery_performed


@pytest.mark.parametrize("blocker", [
    "ownership_evidence_unusable", "ownership_reconciliation_binding_changed",
])
def test_filtration_domain_gate_denies_unusable_or_rebound_episode(blocker: str) -> None:
    driver, _, _ = _verified_filtration_driver()
    registry = driver.ownership
    lease = registry.filtration_lease
    assert lease is not None
    registry.update_filtration_domain(
        replace(lease.domain_state(OwnershipDomain.PUMP), command_blocker=blocker),
        session_id=lease.session_id,
    )
    assert registry.domain_permission_blocker(OwnershipDomain.PUMP) is not None
    assert registry.filtration_lease is not None
    assert registry.filtration_lease.body_activation == lease.body_activation


@pytest.mark.parametrize("field,value", [
    ("equipment_id", "another-pump"),
    ("requested_at", NOW + timedelta(seconds=10)),
    ("authority_generation", 999),
    ("body_session_id", "obsolete-session"),
])
def test_direct_operator_adapter_cannot_yield_unrelated_or_future_binding(field, value) -> None:
    manager = verified_full_manager()
    lease = manager.state.lease
    assert lease is not None
    request = PositiveOperatorEvidence(
        "manual-pump", lease.body_session_generation, lease.body_session_id,
        OwnershipDomain.PUMP, "pump.rpm", NOW,
    )
    assert not manager.record_operator_intent(replace(request, **{field: value}), evaluated_at=NOW)
    assert manager.state.lease == lease


def test_body_operator_intent_invalidates_pending_filtration_to_thermal_transfer() -> None:
    driver, _, _ = _verified_filtration_driver()
    registry = driver.ownership
    lease = registry.filtration_lease
    assert lease is not None
    at = FILTRATION_NOW + timedelta(seconds=5)
    registry.begin_epoch("successor-epoch")
    assert registry.reserve_thermal("successor-epoch")
    token = registry.begin_filtration_to_thermal(
        thermal_purpose_id="solar-purpose", established_at=at,
    )
    assert token is not None
    assert registry.record_operator_intent(PositiveOperatorEvidence(
        "manual-pool-off", lease.generation, lease.session_id,
        OwnershipDomain.BODY, "B1101", at,
    ), evaluated_at=at)
    with pytest.raises(ValueError, match="body authority"):
        registry.complete_filtration_to_thermal(
            token_id=token.token_id, thermal_lease_id="new-thermal-lease",
        )
    assert registry.domain_permission_blocker(OwnershipDomain.PUMP) is not None
    assert registry.filtration_lease is not None
    assert registry.filtration_lease.body_activation == lease.body_activation


def test_full_pool_day_filtration_solar_filtration_shutdown_and_independent_restart() -> None:
    from poolos.filtration_automatic_execution import FiltrationAutomaticExecutionDriver
    from poolos.pool_circulation_ownership import PoolCirculationOwner
    from test_thermal_automatic_execution import _filtration_frame

    orchestrator = ThermalRuntimeOrchestrator()
    thermal = ThermalAutomaticExecutionDriver(orchestrator)
    registry = thermal.circulation_ownership
    filtration = FiltrationAutomaticExecutionDriver(registry)
    evaluator = ThermalRuntimeEvaluator()
    ledger = StructuredCommandLedger()
    delivery = FakeDelivery(ledger=ledger)
    factory = FakeDeliveryFactory(delivery, driver=thermal)
    physical = dict(pool_active=False, pump_rpm=0, configured_rpm=2600,
                    pool_heater="H0002", solar_active=False)
    baseline = thermal_frame(orchestrator, NOW, evaluator=evaluator,
                             mode=ThermalRequestedMode.OFF, **physical)
    thermal.note_disabled_epoch(baseline)
    thermal.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    filtration.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    origin = None
    first_generation = None
    body_session = None
    history = []
    for seconds in range(1, 901):
        at = NOW + timedelta(seconds=seconds)
        satisfied = 760 <= seconds < 850 or seconds >= 870
        mode = ThermalRequestedMode.OFF if seconds < 20 or seconds >= 800 else ThermalRequestedMode.SOLAR
        before = len(delivery.calls)
        frame = thermal_frame(
            orchestrator, at, evaluator=evaluator, driver=thermal, mode=mode,
            pool_temperature=100 if seconds >= 125 else 80,
            verification_timeout=timedelta(seconds=120),
            filtration_remaining=timedelta(0) if satisfied else timedelta(hours=1),
            filtration_disposition=FiltrationDisposition.SATISFIED if satisfied else FiltrationDisposition.RUN_NOW,
            command_ledger=ledger, **physical,
        )
        registry.begin_epoch(frame.epoch_identity)
        thermal.reserve_circulation_candidate(frame)
        try:
            thermal_result = asyncio.run(thermal.process_epoch(frame, delivery_factory=factory))
        except ValueError as exc:
            raise AssertionError((seconds, history[-10:], str(exc))) from exc
        filtration_frame = replace(_filtration_frame(
            at, pool_active=physical["pool_active"], pump_rpm=physical["pump_rpm"],
            configured_rpm=physical["configured_rpm"], satisfied=satisfied,
        ), epoch_identity=frame.epoch_identity, observations=frame.observations,
            thermal_owned=registry.owner is PoolCirculationOwner.THERMAL,
            thermal_candidate_ready=registry.thermal_reserved_for(frame.epoch_identity))
        filtration_result = asyncio.run(filtration.process_epoch(filtration_frame, delivery_factory=factory))
        history.append((seconds, thermal_result.state.value, thermal_result.blocker,
                        filtration_result.state.value, filtration_result.blocker, registry.owner.value))
        if seconds == 15:
            lease = registry.filtration_lease
            assert lease is not None and lease.verified, history
            origin = lease.body_activation
            first_generation = lease.generation
            body_session = (lease.body_session_id, lease.body_session_generation)
            assert origin is not None
        if seconds == 120:
            lease = orchestrator.ownership.state.lease
            assert lease is not None and lease.owns_body_activation, history
            assert lease.body_activation == origin
            assert (lease.body_session_id, lease.body_session_generation) == body_session
            from poolos.thermal_runtime_ownership import ThermalRuntimeOwnedConcept
            assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in lease.verified_concepts
            assert lease.owns_pump_setpoint and lease.owns_heat_source
            assert physical["solar_active"] and physical["pump_rpm"] == 2900, history[-10:]
        if seconds == 750:
            lease = registry.filtration_lease
            assert lease is not None and lease.verified, repr(history[720:740])
            assert lease.body_activation == origin
            assert (lease.body_session_id, lease.body_session_generation) == body_session
            assert physical["pool_active"] and physical["pump_rpm"] == 2600
            retired_thermal = orchestrator.ownership.state.lease
            assert retired_thermal is not None
            assert retired_thermal.body_activation == origin
            assert retired_thermal.domain_state(OwnershipDomain.BODY).authority is OwnershipAuthority.NONE
        if seconds == 790:
            assert physical["pool_active"] is False and physical["pump_rpm"] == 0, history[-30:]
            assert registry.owner is PoolCirculationOwner.NONE
        if seconds == 860:
            lease = registry.filtration_lease
            assert lease is not None and lease.verified, repr(history[-12:])
            assert lease.generation > first_generation
            assert lease.body_activation != origin
            assert (lease.body_session_id, lease.body_session_generation) != body_session
        new_commands = delivery.calls[before:]
        assert len(new_commands) <= 1, history[-5:]
        for operation in new_commands:
            if isinstance(operation, SetBodyActive):
                if operation.active:
                    assert physical["pool_heater"] == "00000"
                physical["pool_active"] = operation.active
                if not operation.active:
                    physical["pump_rpm"] = 0
                    physical["solar_active"] = False
            elif isinstance(operation, SetPumpSpeed):
                if operation.rpm == 2900:
                    assert physical["solar_active"]
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm
            else:
                assert isinstance(operation, SetHeatMode)
                physical["pool_heater"] = {PhysicalHeatMode.OFF: "00000",
                                          PhysicalHeatMode.SOLAR: "H0002"}[operation.mode]
                physical["solar_active"] = operation.mode is PhysicalHeatMode.SOLAR
    assert physical["pool_active"] is False and physical["pump_rpm"] == 0, history[-30:]
    assert physical["pool_heater"] == "00000"
    assert thermal.cleanup_attempt is None and thermal.cleanup_provenance is None
    assert orchestrator.ownership.residual_termination is None
    assert registry.owner is PoolCirculationOwner.NONE
    ledger.assert_complete()


def test_suspended_filtration_owner_defers_thermal_candidate_without_collision() -> None:
    """Thermal must not deliver before a suspended filtration owner can hand off."""

    filtration, _, _ = _verified_filtration_driver()
    registry = filtration.ownership
    filtration_lease = registry.filtration_lease
    assert filtration_lease is not None and filtration_lease.verified
    registry.suspend_filtration(session_id=filtration_lease.session_id)

    orchestrator = ThermalRuntimeOrchestrator()
    thermal = ThermalAutomaticExecutionDriver(
        orchestrator,
        circulation_ownership=registry,
    )
    thermal.set_enabled(
        True,
        changed_at=FILTRATION_NOW,
        current_epoch_identity=None,
    )
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=thermal)
    frame = thermal_frame(
        orchestrator,
        FILTRATION_NOW + timedelta(seconds=3),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        pool_heater="00000",
        solar_active=False,
        solar_temperature=110.0,
        pool_temperature=80.0,
        mode=ThermalRequestedMode.SOLAR,
    )
    registry.begin_epoch(frame.epoch_identity)
    thermal.reserve_circulation_candidate(frame)

    result = asyncio.run(
        thermal.process_epoch(frame, delivery_factory=factory)
    )

    assert result.state.value == "blocked"
    assert result.blocker == "automatic_thermal_circulation_handoff_unavailable"
    assert delivery.calls == []
    assert registry.owner.value == "filtration_suspended"
    assert registry.filtration_lease == filtration_lease
    assert orchestrator.ownership.state.lease is None


@pytest.mark.parametrize("positive_intent", [False, True])
def test_solar_active_transfers_owned_filtration_pump_to_solar_requirement(
    positive_intent: bool,
) -> None:
    """Solar ACTIVE requires 2900 without fabricating THERMAL authority."""

    filtration, _, _ = _verified_filtration_driver()
    registry = filtration.ownership
    filtration_lease = registry.filtration_lease
    assert filtration_lease is not None and filtration_lease.verified
    body_session_id = filtration_lease.body_session_id or filtration_lease.session_id
    body_generation = (
        filtration_lease.body_session_generation or filtration_lease.generation
    )
    at = FILTRATION_NOW + timedelta(seconds=3)
    manual_solar = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="00000",
        new_value="H0002",
        observed_at=at,
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=(
            PositiveOperatorEvidence(
                request_id="operator-select-solar",
                authority_generation=body_generation,
                body_session_id=body_session_id,
                domain=OwnershipDomain.THERMAL,
                equipment_id="pool.raw_heater_id",
                requested_at=at,
            )
            if positive_intent
            else None
        ),
    )
    orchestrator = ThermalRuntimeOrchestrator()
    thermal = ThermalAutomaticExecutionDriver(
        orchestrator,
        circulation_ownership=registry,
    )
    thermal.set_enabled(
        True,
        changed_at=FILTRATION_NOW,
        current_epoch_identity=None,
    )
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=thermal)
    frame = thermal_frame(
        orchestrator,
        at,
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        pool_heater="H0002",
        solar_active=True,
        solar_temperature=110.0,
        pool_temperature=80.0,
        mode=ThermalRequestedMode.SOLAR,
        external_changes=ExternalChangeBatch((manual_solar,)),
    )
    registry.begin_epoch(frame.epoch_identity)
    thermal.reserve_circulation_candidate(frame)
    assert registry.thermal_reserved_for(frame.epoch_identity), (
        frame.orchestration.lifecycle,
        frame.orchestration.blocking_reason,
        registry.owner,
    )

    result = asyncio.run(
        thermal.process_epoch(frame, delivery_factory=factory)
    )

    assert result.state.value == "awaiting_reobservation"
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetPumpSpeed)
    assert delivery.calls[0].rpm == 2900
    transferred = orchestrator.ownership.state.lease
    assert transferred is not None
    assert transferred.domain_state(OwnershipDomain.THERMAL).authority is (
        OwnershipAuthority.OPERATOR
        if positive_intent
        else OwnershipAuthority.NONE
    )
    verified_frame = thermal_frame(
        orchestrator,
        at + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        solar_temperature=110.0,
        pool_temperature=80.0,
        mode=ThermalRequestedMode.SOLAR,
        external_changes=ExternalChangeBatch((manual_solar,)),
    )
    registry.begin_epoch(verified_frame.epoch_identity)
    thermal.reserve_circulation_candidate(verified_frame)
    asyncio.run(
        thermal.process_epoch(verified_frame, delivery_factory=factory)
    )
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.domain_state(OwnershipDomain.BODY).authority is OwnershipAuthority.POOLOS
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.POOLOS
    assert lease.domain_state(OwnershipDomain.THERMAL).authority is (
        OwnershipAuthority.OPERATOR
        if positive_intent
        else OwnershipAuthority.NONE
    )


@pytest.mark.parametrize("filtration_required", [False, True])
def test_operator_solar_then_off_preserves_poolos_body_pump_scope(
    filtration_required: bool,
) -> None:
    """Operator THERMAL changes neither steal nor widen BODY/PUMP authority."""

    filtration, _, _ = _verified_filtration_driver()
    registry = filtration.ownership
    filtration_lease = registry.filtration_lease
    assert filtration_lease is not None and filtration_lease.verified
    body_session_id = filtration_lease.body_session_id or filtration_lease.session_id
    body_generation = (
        filtration_lease.body_session_generation or filtration_lease.generation
    )
    at = FILTRATION_NOW + timedelta(seconds=3)
    manual_solar = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="00000",
        new_value="H0002",
        observed_at=at,
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id="operator-select-solar",
            authority_generation=body_generation,
            body_session_id=body_session_id,
            domain=OwnershipDomain.THERMAL,
            equipment_id="pool.raw_heater_id",
            requested_at=at,
        ),
    )
    orchestrator = ThermalRuntimeOrchestrator()
    thermal = ThermalAutomaticExecutionDriver(
        orchestrator,
        circulation_ownership=registry,
    )
    thermal.set_enabled(True, changed_at=FILTRATION_NOW, current_epoch_identity=None)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=thermal)
    first = thermal_frame(
        orchestrator,
        at,
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        pool_heater="H0002",
        solar_active=True,
        solar_temperature=110.0,
        pool_temperature=80.0,
        mode=ThermalRequestedMode.SOLAR,
        external_changes=ExternalChangeBatch((manual_solar,)),
    )
    registry.begin_epoch(first.epoch_identity)
    thermal.reserve_circulation_candidate(first)
    asyncio.run(thermal.process_epoch(first, delivery_factory=factory))
    verified = thermal_frame(
        orchestrator,
        at + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        solar_temperature=110.0,
        pool_temperature=80.0,
        mode=ThermalRequestedMode.SOLAR,
        external_changes=ExternalChangeBatch((manual_solar,)),
    )
    registry.begin_epoch(verified.epoch_identity)
    thermal.reserve_circulation_candidate(verified)
    asyncio.run(thermal.process_epoch(verified, delivery_factory=factory))
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.domain_state(OwnershipDomain.BODY).authority is OwnershipAuthority.POOLOS
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.POOLOS
    assert lease.domain_state(OwnershipDomain.THERMAL).authority is OwnershipAuthority.OPERATOR

    off_at = at + timedelta(seconds=2)
    assert lease.body_session_id is not None
    assert lease.body_session_generation is not None
    manual_off = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="H0002",
        new_value="00000",
        observed_at=off_at,
        external_policy="accept",
        action_taken="operator_request",
        notification_recommended=True,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id="operator-select-off",
            authority_generation=lease.body_session_generation,
            body_session_id=lease.body_session_id,
            domain=OwnershipDomain.THERMAL,
            equipment_id="pool.raw_heater_id",
            requested_at=off_at,
        ),
    )
    physical = {
        "pool_active": True,
        "pump_rpm": 2900,
        "configured_rpm": 2900,
    }
    for seconds in range(2, 10):
        before = len(delivery.calls)
        frame = thermal_frame(
            orchestrator,
            at + timedelta(seconds=seconds),
            pool_heater="00000",
            solar_active=False,
            solar_temperature=80.0,
            pool_temperature=100.0,
            mode=ThermalRequestedMode.SOLAR,
            filtration_remaining=(
                timedelta(hours=1) if filtration_required else timedelta(0)
            ),
            filtration_disposition=(
                FiltrationDisposition.RUN_NOW
                if filtration_required
                else FiltrationDisposition.SATISFIED
            ),
            external_changes=ExternalChangeBatch((manual_off,)),
            **physical,
        )
        registry.begin_epoch(frame.epoch_identity)
        thermal.reserve_circulation_candidate(frame)
        asyncio.run(thermal.process_epoch(frame, delivery_factory=factory))
        for operation in delivery.calls[before:]:
            if isinstance(operation, SetPumpSpeed):
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm
            elif isinstance(operation, SetBodyActive):
                physical["pool_active"] = operation.active
                if not operation.active:
                    physical["pump_rpm"] = 0

    assert not any(isinstance(operation, SetHeatMode) for operation in delivery.calls)
    if filtration_required:
        assert physical == {
            "pool_active": True,
            "pump_rpm": 2600,
            "configured_rpm": 2600,
        }
        assert registry.owner is PoolCirculationOwner.FILTRATION
        assert not any(
            isinstance(operation, SetBodyActive) and not operation.active
            for operation in delivery.calls
        )
    else:
        assert physical["pool_active"] is False
        assert physical["pump_rpm"] == 0
        assert registry.owner is PoolCirculationOwner.NONE


def test_rejected_filtration_correction_retains_body_for_verified_completion() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    original = driver.ownership.filtration_lease
    assert original is not None
    delivery.accepted = False
    drift = _frame(FILTRATION_NOW + timedelta(seconds=3), pool=True, rpm=2550, configured=2600)
    result = asyncio.run(driver.process_epoch(drift, delivery_factory=factory))
    assert result.state.value == "failed"
    lease = driver.ownership.filtration_lease
    assert lease is not None and lease.body_activation == original.body_activation
    assert lease.domain_state(OwnershipDomain.PUMP).health is OwnershipHealth.FAULTED
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.POOLOS
    count = len(delivery.operations)
    for seconds in (4, 5, 40, 140):
        repeated = _frame(FILTRATION_NOW + timedelta(seconds=seconds),
                          pool=True, rpm=2550, configured=2600)
        asyncio.run(driver.process_epoch(repeated, delivery_factory=factory))
    assert len(delivery.operations) == count
    delivery.accepted = True
    complete = _frame(FILTRATION_NOW + timedelta(seconds=141), pool=True,
                      rpm=2550, configured=2600, satisfied=True)
    asyncio.run(driver.process_epoch(complete, delivery_factory=factory))
    assert len(delivery.operations) == count + 1
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False
    observed = _frame(FILTRATION_NOW + timedelta(seconds=142), pool=False,
                      rpm=0, configured=2600, satisfied=True)
    asyncio.run(driver.process_epoch(observed, delivery_factory=factory))
    assert driver.ownership.filtration_lease is None


@pytest.mark.parametrize("later_opportunity", [False, True])
def test_rejected_thermal_prime_does_not_block_owned_body_cleanup(later_opportunity: bool) -> None:
    from poolos.hal import CommandStatus

    class RejectPump(FakeDelivery):
        async def deliver(self, operation, *, correlation_id):
            receipt = await super().deliver(operation, correlation_id=correlation_id)
            return replace(receipt, status=CommandStatus.REJECTED) if isinstance(operation, SetPumpSpeed) else receipt

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    thermal_frame(ThermalRuntimeOrchestrator(), NOW - timedelta(seconds=1),
                  pool_active=True, pump_rpm=2600, evaluator=evaluator,
                  mode=ThermalRequestedMode.SOLAR)
    delivery = RejectPump()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    physical = dict(pool_active=False, pump_rpm=0, configured_rpm=2600,
                    pool_heater="00000", solar_active=False)
    baseline = thermal_frame(orchestrator, NOW, evaluator=evaluator,
                             mode=ThermalRequestedMode.SOLAR, **physical)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppression
    opportunities = PoolAutomaticControlSuppression()
    opportunity_id = opportunities.observe_opportunity("thermal", eligible=True, observed_at=NOW)
    for seconds in range(1, 30):
        if later_opportunity and seconds in {15, 16}:
            opportunity_id = opportunities.observe_opportunity(
                "thermal", eligible=seconds == 16, observed_at=NOW + timedelta(seconds=seconds),
            )
        before = len(delivery.calls)
        frame = thermal_frame(orchestrator, NOW + timedelta(seconds=seconds),
                              evaluator=evaluator, driver=driver, mode=ThermalRequestedMode.SOLAR,
                              filtration_remaining=timedelta(0),
                              filtration_disposition=FiltrationDisposition.SATISFIED, **physical)
        frame = replace(frame, pool_opportunity_id=opportunity_id)
        asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        for operation in delivery.calls[before:]:
            if isinstance(operation, SetBodyActive):
                physical["pool_active"] = operation.active
    sessions = 2 if later_opportunity else 1
    assert sum(isinstance(item, SetPumpSpeed) for item in delivery.calls) == sessions
    assert [item.active for item in delivery.calls if isinstance(item, SetBodyActive)] == [True, False] * sessions
    assert physical["pool_active"] is False and physical["pump_rpm"] == 0
    assert driver.cleanup_provenance is None and driver.cleanup_attempt is None
    assert orchestrator.ownership.residual_termination is None
