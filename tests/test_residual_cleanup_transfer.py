"""Residual-to-cleanup transfer must not discard accepted body provenance."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from test_thermal_automatic_execution import (
    FakeDelivery,
    FakeDeliveryFactory,
    FiltrationDisposition,
    NOW,
    SetBodyActive,
    SetPumpSpeed,
    ThermalAutomaticExecutionDriver,
    ThermalRequestedMode,
    ThermalRuntimeEvaluator,
    ThermalRuntimeOrchestrator,
    ThermalRuntimeOwnershipStatus,
    ExternalChangeBatch,
    _frame,
    _driver_awaiting_source_off_verification,
)
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnedConcept
from poolos.integration import ThermalBody, SetHeatMode


@pytest.mark.parametrize("verified_off", (False, True), ids=("relinquish", "verified_off"))
@pytest.mark.parametrize("body,pump_owned", ((ThermalBody.POOL, False),), ids=("pool_source_only",))
def test_no_circulation_capability_disposes_once_through_runtime(
    monkeypatch,
    verified_off,
    body,
    pump_owned,
):
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)

    def frame(seconds, *, rpm=3000, heater="00000", mode=ThermalRequestedMode.GAS):
        return _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            body=body,
            pool_active=body is ThermalBody.POOL,
            pump_rpm=rpm,
            configured_rpm=rpm,
            pool_heater=heater,
            spa_heater=heater,
            spa_temperature=80.0,
            mode=mode,
        )

    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    seconds = 1
    asyncio.run(
        driver.process_epoch(
            frame(seconds, rpm=2600 if pump_owned else 3000), delivery_factory=factory
        )
    )
    if pump_owned:
        assert isinstance(delivery.calls[-1], SetPumpSpeed)
        seconds += 1
        asyncio.run(driver.process_epoch(frame(seconds), delivery_factory=factory))
    assert isinstance(delivery.calls[-1], SetHeatMode)
    seconds += 1
    asyncio.run(driver.process_epoch(frame(seconds, heater="H0001"), delivery_factory=factory))
    lease = orchestrator.ownership.state.lease
    assert lease.body_activation is None
    assert lease.owns_heat_source
    assert lease.owns_pump_setpoint is pump_owned
    assert ThermalRuntimeOwnedConcept.HEAT_SOURCE in lease.verified_concepts

    captures, consumed = [], []
    capture = type(driver)._capture_cleanup_provenance
    consume = type(orchestrator.ownership).consume_residual_termination

    def record_capture(self, entitlement, **kwargs):
        result = capture(self, entitlement, **kwargs)
        captures.append((entitlement, result.value))
        return result

    def record_consume(self, *, entitlement_id):
        result = consume(self, entitlement_id=entitlement_id)
        consumed.append((entitlement_id, result))
        return result

    monkeypatch.setattr(type(driver), "_capture_cleanup_provenance", record_capture)
    monkeypatch.setattr(
        type(orchestrator.ownership), "consume_residual_termination", record_consume
    )
    seconds += 1
    ending = frame(
        seconds, heater="H0001" if verified_off else "00000", mode=ThermalRequestedMode.OFF
    )
    residual = orchestrator.ownership.residual_termination
    assert residual is not None
    assert residual.body_activation is None
    assert (residual.pump_setpoint is not None) is pump_owned
    assert residual.heat_source is not None
    before = len(delivery.calls)
    asyncio.run(driver.process_epoch(ending, delivery_factory=factory))
    if verified_off:
        assert len(delivery.calls) == before + 1
        assert isinstance(delivery.calls[-1], SetHeatMode)
        assert delivery.calls[-1].mode.value == "off"
        assert driver.termination_attempt is not None
        assert captures == []
        seconds += 1
        asyncio.run(
            driver.process_epoch(
                frame(seconds, mode=ThermalRequestedMode.OFF), delivery_factory=factory
            )
        )
    assert captures == [(residual, "no_circulation_capability")]
    assert consumed == [(residual.entitlement_id, True)]
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert driver.termination_attempt is None
    assert len(delivery.calls) == before + int(verified_off)
    assert not any(isinstance(op, SetBodyActive) for op in delivery.calls)
    count = len(delivery.calls)
    for offset in (1, 2, 3):
        current = frame(seconds + offset, mode=ThermalRequestedMode.OFF)
        for _ in range(2):
            result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
            assert not result.command_delivery_performed
            assert driver.cleanup_provenance is None
            assert driver.cleanup_attempt is None
            assert not result.runtime_ownership_summary["body_deactivation_authorized"]
            assert not result.runtime_ownership_summary["filtration_pump_normalization_authorized"]
            assert not result.runtime_ownership_summary["stop_pump_authorized"]
    assert len(delivery.calls) == count
    assert consumed == [(residual.entitlement_id, True)]
    assert len(captures) == 1


def test_hot_tub_pump_residual_without_body_origin_disposes_once(monkeypatch):
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    def frame(seconds, rpm=2600):
        return _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=False,
            body=ThermalBody.HOT_TUB,
            pump_rpm=rpm,
            configured_rpm=rpm,
            spa_temperature=80.0,
            spa_target=97.0,
            driver=driver,
            evaluator=evaluator,
            mode=ThermalRequestedMode.OFF if seconds >= 3 else ThermalRequestedMode.GAS,
        )

    captures, consumed = [], []
    capture = type(driver)._capture_cleanup_provenance
    consume = type(orchestrator.ownership).consume_residual_termination

    def record_capture(self, entitlement, **kwargs):
        result = capture(self, entitlement, **kwargs)
        captures.append((entitlement, result.value))
        return result

    def record_consume(self, *, entitlement_id):
        result = consume(self, entitlement_id=entitlement_id)
        consumed.append((entitlement_id, result))
        return result

    monkeypatch.setattr(type(driver), "_capture_cleanup_provenance", record_capture)
    monkeypatch.setattr(
        type(orchestrator.ownership), "consume_residual_termination", record_consume
    )
    asyncio.run(driver.process_epoch(frame(1, 2500), delivery_factory=factory))
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600
    asyncio.run(driver.process_epoch(frame(2), delivery_factory=factory))
    residual = orchestrator.ownership.residual_termination
    assert residual is not None
    assert residual.body is ThermalBody.HOT_TUB
    assert residual.body_activation is None
    assert residual.pump_setpoint is not None
    assert residual.heat_source is None
    asyncio.run(driver.process_epoch(frame(3), delivery_factory=factory))
    assert captures == [(residual, "no_circulation_capability")]
    assert consumed == [(residual.entitlement_id, True)]
    for seconds in (4, 5, 6):
        current = frame(seconds)
        for _ in range(2):
            result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
            assert not result.command_delivery_performed
            assert driver.cleanup_provenance is None
            assert driver.cleanup_attempt is None
            assert not result.runtime_ownership_summary["body_deactivation_authorized"]
            assert not result.runtime_ownership_summary["filtration_pump_normalization_authorized"]
    assert len(delivery.calls) == 1  # Original accepted normalization only.
    assert orchestrator.ownership.residual_termination is None
    assert len(captures) == 1
    assert consumed == [(residual.entitlement_id, True)]


@pytest.mark.parametrize("verified_off", (False, True), ids=("relinquish", "verified_off"))
@pytest.mark.parametrize("disposition", ("captured", "waiting_for_evidence", "invalidated"))
def test_both_capture_callers_handle_each_transfer_disposition(
    monkeypatch, verified_off, disposition
):
    if verified_off:
        orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
        current = _frame(
            orchestrator,
            NOW + timedelta(seconds=66),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
            mode=ThermalRequestedMode.OFF,
        )
    else:
        orchestrator, driver, _, factory, frame, _ = completed_probe(process_supersession=False)
        current = frame(123)
    residual = orchestrator.ownership.residual_termination
    assert residual is not None and residual.body_activation is not None
    assert (driver.termination_attempt is not None) is verified_off
    real_arbitration = type(driver)._circulation_assessment
    real_capture = type(driver)._capture_cleanup_provenance
    observed = []

    def arbitration(self, frame):
        assessment = real_arbitration(self, frame)
        # Isolate the caller contract with injected arbitration outcomes;
        # execute the real capture method and real residual disposal logic.
        if disposition == "waiting_for_evidence":
            return None
        if disposition == "invalidated" and assessment is not None:
            return replace(assessment, external_takeover=True)
        return assessment

    def capture(self, entitlement, **kwargs):
        result = real_capture(self, entitlement, **kwargs)
        observed.append(result.value)
        return result

    monkeypatch.setattr(type(driver), "_circulation_assessment", arbitration)
    monkeypatch.setattr(type(driver), "_capture_cleanup_provenance", capture)
    count = len(factory.delivery.calls)
    result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    assert observed == [disposition]
    assert len(factory.delivery.calls) == count
    assert not result.command_delivery_performed
    assert driver.termination_attempt is None
    if disposition == "captured":
        assert driver.cleanup_provenance.body_activation == residual.body_activation
        assert orchestrator.ownership.residual_termination is None
    elif disposition == "waiting_for_evidence":
        assert result.state.value == "cleanup_waiting"
        assert driver.cleanup_provenance is None
        assert orchestrator.ownership.residual_termination is residual
    else:
        assert driver.cleanup_provenance is None
        assert orchestrator.ownership.residual_termination is None


def completed_probe(*, source_age_at_supersession=0, process_supersession=True):
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)

    def frame(
        seconds,
        *,
        active=True,
        roof=90.0,
        missing=(),
        rpm=1500,
        heater="00000",
        solar_active=False,
        temperature=86.0,
        immediate_filtration=False,
        source_at=None,
        spa_active=False,
        external_changes=ExternalChangeBatch(()),
    ):
        return _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=active,
            pump_rpm=rpm if active else 0,
            configured_rpm=rpm or 1500,
            mode=ThermalRequestedMode.SOLAR,
            pool_temperature=temperature,
            solar_temperature=roof,
            pool_heater=heater,
            solar_active=solar_active,
            spa_active=spa_active,
            external_changes=external_changes,
            observation_times={
                "pool.raw_heater_id": source_at
                or NOW
                + timedelta(
                    seconds=seconds - (source_age_at_supersession if seconds == 123 else 0)
                ),
            },
            missing=missing,
            evaluator=evaluator,
            driver=driver,
            filtration_remaining=timedelta(hours=2),
            filtration_disposition=FiltrationDisposition.CREDITING,
            filtration_independent_disposition=(
                FiltrationDisposition.RUN_NOW
                if immediate_filtration
                else FiltrationDisposition.DEFERRED_OPTIMIZATION
            ),
        )

    baseline = frame(0, active=False, missing=("pool.temperature",))
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    for seconds in (1, 2, 3, 33, 63):
        current = frame(
            seconds,
            active=seconds >= 2,
            missing=("pool.temperature",) if seconds <= 3 else (),
        )
        asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    predecessor = orchestrator.ownership.state.lease
    assert predecessor is not None
    assert predecessor.status is ThermalRuntimeOwnershipStatus.OWNED
    assert predecessor.owns_body_activation and predecessor.owns_pump_setpoint
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in predecessor.verified_concepts
    assert ThermalRuntimeOwnedConcept.PUMP_SETPOINT in predecessor.verified_concepts
    assert len(delivery.calls) == 2
    assert isinstance(delivery.calls[0], SetBodyActive)
    assert delivery.calls[0].active is True
    assert isinstance(delivery.calls[1], SetPumpSpeed)
    assert delivery.calls[1].rpm == 1500
    current = frame(123)
    assert current.thermal is not None
    assert not current.thermal.pool.actual_authorization.authorized
    assert current.thermal.pool.execution_currentness.purpose.kind.value == "thermal_control"
    assert evaluator.pool_temperature_probe.last_assessment.reason_code == "probe_settled"
    if process_supersession:
        asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    return orchestrator, driver, delivery, factory, frame, predecessor


@pytest.mark.parametrize("collector_becomes_eligible", (False, True))
def test_baseline_supersession_preserves_cleanup_and_delivers_body_off(
    collector_becomes_eligible,
):
    orchestrator, driver, delivery, factory, frame, predecessor = completed_probe()
    assert orchestrator.ownership.state.reason_code == (
        "runtime_ownership_superseded:execution_purpose"
    )
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation == predecessor.body_activation
    assert driver.cleanup_provenance.generation == predecessor.generation
    current = frame(124, roof=97.0 if collector_becomes_eligible else 90.0)
    assert current.thermal.pool.actual_authorization.authorized is collector_becomes_eligible
    result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    assert result.state.value == "awaiting_cleanup_verification"
    assert len(delivery.calls) == 3
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is False
    result = asyncio.run(driver.process_epoch(frame(125, active=False), delivery_factory=factory))
    assert result.blocker == "thermal_cleanup_pool_body_off_verified"
    assert driver.cleanup_provenance is None
    assert len(delivery.calls) == 3


@pytest.mark.parametrize("source_age", (1, 29, 119))
@pytest.mark.parametrize("immediate_filtration", (False, True))
def test_async_source_observation_preserves_body_through_later_solar(
    source_age,
    immediate_filtration,
):
    """Full bad-state reproducer: no external changes or ignored commands."""
    orchestrator, driver, delivery, factory, frame, predecessor = completed_probe(
        source_age_at_supersession=source_age, process_supersession=False
    )
    entitlement = orchestrator.ownership.residual_termination
    assert entitlement is not None
    assert entitlement.body_activation == predecessor.body_activation
    assert entitlement.pump_setpoint == predecessor.pump_setpoint
    assert entitlement.heat_source is None
    assert entitlement.lease_id == predecessor.lease_id
    assert entitlement.generation == predecessor.generation
    superseded = frame(123)
    termination = driver._termination_assessment(superseded)
    circulation = driver._circulation_assessment(superseded)
    assert termination.reason_code == "thermal_termination_no_owned_active_source"
    assert circulation.reason_code == "circulation_source_cleanup_not_complete"
    assert not circulation.source_cleanup_complete
    waiting = asyncio.run(driver.process_epoch(superseded, delivery_factory=factory))
    assert waiting.state.value == "cleanup_waiting"
    assert not waiting.command_delivery_performed

    assert orchestrator.ownership.residual_termination is entitlement
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert len(delivery.calls) == 2

    # Solar becomes eligible before the residual has transferred. Cleanup must
    # take priority; a new generation cannot bypass the old body obligation.
    for seconds in (124, 125):
        current = frame(seconds, roof=93.0)
        driver.circulation_ownership.begin_epoch(current.epoch_identity)
        driver.reserve_circulation_candidate(current)
        result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
        count = len(delivery.calls)
        assert asyncio.run(driver.process_epoch(current, delivery_factory=factory)) == result
        assert len(delivery.calls) == count
        if seconds == 124:
            assert driver.cleanup_provenance.body_activation == predecessor.body_activation
            assert orchestrator.ownership.residual_termination is None
            assert len(delivery.calls) == 2
        else:
            assert isinstance(delivery.calls[-1], SetBodyActive)
            assert delivery.calls[-1].active is False
            assert result.state.value == "awaiting_cleanup_verification"

    result = asyncio.run(
        driver.process_epoch(frame(126, active=False, roof=93.0), delivery_factory=factory)
    )
    assert result.blocker == "thermal_cleanup_pool_body_off_verified"
    assert driver.cleanup_provenance is None
    assert len(delivery.calls) == 3

    for seconds, rpm, heater, solar_active in (
        (127, 0, "00000", False),
        (128, 0, "00000", False),
        (129, 3000, "00000", False),
        (159, 3000, "00000", False),
        (189, 3000, "00000", False),
        (190, 2900, "00000", False),
        (191, 2900, "H0002", False),
        (192, 2900, "H0002", True),
        (222, 2900, "H0002", True),
    ):
        current = frame(
            seconds,
            active=seconds != 127,
            roof=93.0,
            rpm=rpm,
            heater=heater,
            solar_active=solar_active,
        )
        driver.circulation_ownership.begin_epoch(current.epoch_identity)
        driver.reserve_circulation_candidate(current)
        result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    assert result.state.value == "converged"
    assert isinstance(delivery.calls[3], SetBodyActive)
    assert delivery.calls[3].active is True
    successor = orchestrator.ownership.state.lease
    assert successor.status is ThermalRuntimeOwnershipStatus.OWNED
    assert successor.generation > predecessor.generation
    assert successor.owns_pump_setpoint and successor.owns_heat_source
    assert ThermalRuntimeOwnedConcept.PUMP_SETPOINT in successor.verified_concepts
    assert ThermalRuntimeOwnedConcept.HEAT_SOURCE in successor.verified_concepts
    assert driver.cleanup_provenance is None
    assert orchestrator.ownership.residual_termination is None
    assert successor.owns_body_activation
    assert successor.body_activation != predecessor.body_activation

    # Normal target hysteresis expires with fresh observations. Observe each
    # real accepted source/cleanup operation before advancing its dependent step.
    for seconds in range(252, 883, 30):
        result = asyncio.run(
            driver.process_epoch(
                frame(
                    seconds,
                    roof=100.0,
                    rpm=2900,
                    heater="H0002",
                    solar_active=True,
                    temperature=90.0,
                    immediate_filtration=immediate_filtration,
                ),
                delivery_factory=factory,
            )
        )
        if (
            getattr(delivery.calls[-1], "mode", None) is not None
            and delivery.calls[-1].mode.value == "off"
        ):
            break
    assert delivery.calls[-1].mode.value == "off"
    source_off_at = seconds + 1
    result = asyncio.run(
        driver.process_epoch(
            frame(
                source_off_at,
                roof=100.0,
                rpm=2900,
                temperature=90.0,
                immediate_filtration=immediate_filtration,
            ),
            delivery_factory=factory,
        )
    )
    assert driver.cleanup_provenance.body_activation == successor.body_activation
    result = asyncio.run(
        driver.process_epoch(
            frame(
                source_off_at + 1,
                roof=100.0,
                rpm=2900,
                temperature=90.0,
                immediate_filtration=immediate_filtration,
            ),
            delivery_factory=factory,
        )
    )
    assert result.state.value == "awaiting_cleanup_verification"
    if immediate_filtration:
        assert isinstance(delivery.calls[-1], SetPumpSpeed)
        assert delivery.calls[-1].rpm == 2600
    else:
        assert isinstance(delivery.calls[-1], SetBodyActive)
        assert delivery.calls[-1].active is False
    final = frame(
        source_off_at + 2,
        active=immediate_filtration,
        rpm=2600 if immediate_filtration else 0,
        roof=100.0,
        temperature=90.0,
        immediate_filtration=immediate_filtration,
    )
    result = asyncio.run(driver.process_epoch(final, delivery_factory=factory))
    assert result.blocker == (
        "thermal_cleanup_filtration_handoff_verified"
        if immediate_filtration
        else "thermal_cleanup_pool_body_off_verified"
    )
    assert driver.cleanup_provenance is None
    if immediate_filtration:
        assert driver.circulation_ownership.filtration_lease.verified
        assert (
            driver.circulation_ownership.filtration_lease.body_activation
            == successor.body_activation
        )


@pytest.mark.parametrize("takeover", ("body_off", "pump", "spa"))
def test_retained_capture_wait_rechecks_takeover_before_any_cleanup(takeover):
    orchestrator, driver, delivery, factory, frame, _ = completed_probe(
        source_age_at_supersession=1,
    )
    assert orchestrator.ownership.residual_termination is not None
    changed = frame(
        124,
        active=takeover != "body_off",
        rpm=2200 if takeover == "pump" else 1500,
        spa_active=takeover == "spa",
    )
    asyncio.run(driver.process_epoch(changed, delivery_factory=factory))
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    asyncio.run(driver.process_epoch(frame(125), delivery_factory=factory))
    assert len(delivery.calls) == 2


def test_retained_probe_cleanup_transfers_to_immediate_filtration():
    orchestrator, driver, delivery, factory, frame, predecessor = completed_probe(
        source_age_at_supersession=29,
    )
    assert orchestrator.ownership.residual_termination is not None
    for seconds, rpm in ((124, 1500), (125, 1500), (126, 2600)):
        result = asyncio.run(
            driver.process_epoch(
                frame(seconds, rpm=rpm, immediate_filtration=True),
                delivery_factory=factory,
            )
        )
    assert result.blocker == "thermal_cleanup_filtration_handoff_verified"
    assert len(delivery.calls) == 3
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600
    assert driver.circulation_ownership.filtration_lease.verified
    assert (
        driver.circulation_ownership.filtration_lease.body_activation == predecessor.body_activation
    )
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None


def test_retained_capture_wait_does_not_refresh_entitlement_or_authorize_stale_evidence():
    orchestrator, driver, delivery, factory, frame, _ = completed_probe(
        source_age_at_supersession=1,
    )
    residual = orchestrator.ownership.residual_termination
    for seconds in (124, 153, 243, 363):
        result = asyncio.run(
            driver.process_epoch(
                frame(seconds, source_at=NOW + timedelta(seconds=122)), delivery_factory=factory
            )
        )
        assert result.state.value == "cleanup_waiting"
        assert orchestrator.ownership.residual_termination is residual
        assert driver.cleanup_provenance is None
        assert len(delivery.calls) == 2
    asyncio.run(driver.process_epoch(frame(364), delivery_factory=factory))
    assert driver.cleanup_provenance.source_entitlement_id == residual.entitlement_id
    assert orchestrator.ownership.residual_termination is None


def test_verified_gas_off_does_not_consume_residual_when_capture_is_unavailable(monkeypatch):
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    residual = orchestrator.ownership.residual_termination
    accepted_count = len(factory.delivery.calls)
    real_assessment = driver._circulation_assessment
    # Fault injection at the shared capture contract: verification must not
    # silently consume circulation proof if its next stage cannot accept it.
    monkeypatch.setattr(type(driver), "_circulation_assessment", lambda self, frame: None)
    source_off = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
    )
    result = asyncio.run(driver.process_epoch(source_off, delivery_factory=factory))
    assert result.state.value == "cleanup_waiting"
    assert orchestrator.ownership.residual_termination is residual
    assert driver.termination_attempt is None
    assert driver.cleanup_provenance is None
    assert len(factory.delivery.calls) == accepted_count
    monkeypatch.setattr(
        type(driver), "_circulation_assessment", lambda self, frame: real_assessment(frame)
    )
    current = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
    )
    asyncio.run(driver.process_epoch(current, delivery_factory=factory))
    assert driver.cleanup_provenance.source_entitlement_id == residual.entitlement_id
    assert orchestrator.ownership.residual_termination is None
    assert len(factory.delivery.calls) == accepted_count


def test_new_accepted_generation_invalidates_retained_capture_token():
    orchestrator, driver, delivery, factory, frame, _ = completed_probe(
        source_age_at_supersession=1,
    )
    residual = orchestrator.ownership.residual_termination
    # Obtain a genuinely accepted pump operation from an independent driver;
    # exercise the manager's explicit new-generation boundary, not adoption.
    other = ThermalRuntimeOrchestrator()
    other_driver = ThermalAutomaticExecutionDriver(other)
    other_delivery = FakeDelivery()
    other_factory = FakeDeliveryFactory(other_delivery)
    other_driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    accepted = _frame(
        other,
        NOW + timedelta(seconds=124),
        pool_active=True,
        pump_rpm=1500,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
    )
    asyncio.run(other_driver.process_epoch(accepted, delivery_factory=other_factory))
    session = other_driver.active_session
    assert session is not None
    assert isinstance(other_delivery.calls[-1], SetPumpSpeed)
    decision = orchestrator.ownership.establish(
        session.ownership,
        established_at=accepted.observed_at,
        requested_mode=ThermalRequestedMode.SOLAR.value,
        current_context=session.originating_context,
        execution_progress=session.execution_progress,
    )
    assert decision.current_state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert decision.current_state.lease.generation > residual.generation
    assert orchestrator.ownership.residual_termination is None
    assert driver._termination_assessment(accepted) is None
    assert asyncio.run(driver._process_cleanup(accepted, delivery_factory=factory)) is None
    orchestrator.ownership.consume_residual_termination(entitlement_id=residual.entitlement_id)
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert len(delivery.calls) == 2


def test_unload_and_restart_discard_retained_capture_without_commands():
    orchestrator, driver, delivery, _, _, _ = completed_probe(source_age_at_supersession=1)
    assert orchestrator.ownership.residual_termination is not None
    driver.unload(unloaded_at=NOW + timedelta(seconds=124))
    orchestrator.unload(unloaded_at=NOW + timedelta(seconds=124))
    assert orchestrator.ownership.residual_termination is None
    restarted = ThermalRuntimeOrchestrator()
    fresh = ThermalAutomaticExecutionDriver(restarted)
    frame = _frame(
        restarted,
        NOW + timedelta(seconds=125),
        pool_active=True,
        pump_rpm=1500,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
    )
    assert fresh._termination_assessment(frame) is None
    assert fresh.cleanup_provenance is None
    assert restarted.ownership.state.lease is None
    assert len(delivery.calls) == 2
