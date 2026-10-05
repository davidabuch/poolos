"""Filtration completion responsibility across native observation interleavings."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from poolos.external_change import (
    ExternalChangeBatch, ExternalChangeEvent, ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.filtration_automatic_execution import FiltrationExecutionStep
from poolos.filtration_policy import (
    FiltrationAccountingTracker, FiltrationDisposition, FiltrationObservation,
)
from poolos.integration import SetBodyActive, SetPumpSpeed
from poolos.ownership_evidence import OwnershipDomain, PositiveOperatorEvidence
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE
from tests.test_filtration_automatic_execution import (
    NOW,
    _enabled_driver,
    _frame,
    _verified_filtration_driver,
)


@pytest.mark.parametrize("missing", [("pump.rpm",), ("pool.active",)])
def test_suspended_body_off_keeps_completion_provenance_until_pump_zero(missing) -> None:
    driver, delivery, factory = _verified_filtration_driver()
    async def scenario():
        original = driver.ownership.filtration_lease
        assert original is not None and original.body_activation is not None
        await driver.process_epoch(
            _frame(NOW + timedelta(seconds=3), pool=True, rpm=2600,
                   configured=2600, satisfied=True), delivery_factory=factory,
        )
        assert driver.attempt is not None
        assert driver.attempt.step is FiltrationExecutionStep.BODY_OFF
        deadline = driver.attempt.deadline
        await driver.process_epoch(
            _frame(NOW + timedelta(seconds=4), pool=False, rpm=900,
                   configured=2600, satisfied=True, missing=missing),
            delivery_factory=factory,
        )
        await driver.process_epoch(
            _frame(NOW + timedelta(seconds=5), pool=False, rpm=900,
                   configured=2600, satisfied=True), delivery_factory=factory,
        )
        retained = driver.ownership.filtration_lease
        assert retained is not None, "Pool OFF with pump 900 discarded BODY completion authority"
        assert retained.body_activation == original.body_activation
        assert driver.attempt is not None and driver.attempt.deadline == deadline
        count = len(delivery.operations)
        # A delayed pre-OFF ON frame is published after the partial coastdown.
        late = _frame(NOW + timedelta(seconds=6), pool=True, rpm=2600,
                      configured=2600, satisfied=True, solar_active=False,
                      heater_active=False)
        late = replace(late, observations=tuple(
            replace(item, observed_at=NOW + timedelta(seconds=2))
            if item.observation_id in {"pool.active", "pump.rpm"} else item
            for item in late.observations
        ))
        await driver.process_epoch(late, delivery_factory=factory)
        assert len(delivery.operations) == count
        assert driver.attempt is not None and driver.attempt.step is FiltrationExecutionStep.BODY_OFF
        await driver.process_epoch(
            _frame(NOW + timedelta(seconds=7), pool=False, rpm=0,
                   configured=2600, satisfied=True), delivery_factory=factory,
        )
        assert driver.ownership.filtration_lease is None
        assert driver.attempt is None
    asyncio.run(scenario())


def test_partial_shutdown_then_old_on_callback_cannot_become_pump_only_acquisition() -> None:
    driver, delivery, factory = _verified_filtration_driver()

    async def scenario():
        for seconds, pool, rpm, missing in (
            (3, True, 2600, ()), (4, False, 900, ("pump.rpm",)),
            (5, False, 900, ()), (6, True, 2600, ()),
        ):
            frame = _frame(NOW + timedelta(seconds=seconds), pool=pool, rpm=rpm,
                configured=2600, satisfied=True, missing=missing,
                solar_active=False, heater_active=False)
            if seconds == 6:
                frame = replace(frame, observations=tuple(replace(item,
                    observed_at=NOW + timedelta(seconds=2))
                    if item.observation_id in {"pool.active", "pump.rpm"} else item
                    for item in frame.observations))
            await driver.process_epoch(frame, delivery_factory=factory)
        assert driver.attempt is not None
        assert driver.attempt.step is FiltrationExecutionStep.BODY_OFF, (
            "SATISFIED/ineligible session became pump-only acquiring from its own residue"
        )
        lease = driver.ownership.filtration_lease
        assert lease is not None and lease.body_activation is not None
        assert len(delivery.operations) == 3
    asyncio.run(scenario())


def test_real_tou_accounting_off_start_debt_zero_shutdown_idle_and_new_need() -> None:
    """Six hours of actual qualifying accounting, not a synthetic zero-debt frame."""
    driver, delivery, factory = _enabled_driver()
    tracker = FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)

    async def scenario():
        pool, rpm, configured = False, 0, 2600
        start = NOW + timedelta(hours=13, minutes=1)  # 22:01 PDT TOU opportunity
        original_body = None
        completed = False
        for epoch in range(1460):
            at = start + timedelta(seconds=15 * epoch)
            accounting = tracker.observe(FiltrationObservation(
                observed_at=at, pool_active=pool, spa_active=False, pump_rpm=rpm,
                water_temperature_f=65, circulation_evidence_usable=True,
                temperature_evidence_usable=True,
            ))
            assert accounting is not None
            frame = replace(_frame(at, pool=pool, rpm=rpm, configured=configured,
                solar_active=False, heater_active=False), filtration=accounting)
            before = len(delivery.operations)
            result = await driver.process_epoch(frame, delivery_factory=factory)
            for operation in delivery.operations[before:]:
                if isinstance(operation, SetBodyActive):
                    pool = operation.active
                    rpm = 3000 if pool else 900  # native startup and coastdown
                else:
                    assert isinstance(operation, SetPumpSpeed)
                    configured = rpm = operation.rpm
            lease = driver.ownership.filtration_lease
            if original_body is None and lease is not None:
                original_body = lease.body_activation
                assert original_body is not None
            if lease is not None:
                assert lease.body_activation == original_body
            if accounting.disposition is FiltrationDisposition.SATISFIED:
                assert accounting.total_remaining_runtime == timedelta(0)
                assert not accounting.immediate_circulation_required
                assert all(not isinstance(op, SetPumpSpeed) for op in delivery.operations[before:])
            if not pool and rpm == 900 and before == len(delivery.operations):
                assert driver.attempt is not None and driver.attempt.step is FiltrationExecutionStep.BODY_OFF
                rpm = 0
            if result.blocker == "automatic_filtration_pool_off_verified":
                completed = True
            if completed:
                assert not pool and rpm == 0
                assert driver.ownership.filtration_lease is None
                assert len(delivery.operations) == 3
        assert completed
        assert accounting.total_remaining_runtime == timedelta(0)
        # A later independent day's real debt is eligible again; no permanent latch.
        next_at = start + timedelta(days=1)
        accounting = tracker.observe(FiltrationObservation(
            observed_at=next_at, pool_active=False, spa_active=False, pump_rpm=0,
            water_temperature_f=65, circulation_evidence_usable=True,
            temperature_evidence_usable=True,
        ))
        assert accounting is not None and accounting.independent_disposition is FiltrationDisposition.RUN_NOW
        result = await driver.process_epoch(replace(_frame(next_at, pool=False,
            rpm=0, configured=2600), filtration=accounting), delivery_factory=factory)
        assert result.command_delivery_performed
        assert isinstance(delivery.operations[-1], SetBodyActive) and delivery.operations[-1].active
    asyncio.run(scenario())


def test_completed_shutdown_rejects_delayed_on_facts_without_pump_reacquisition() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    async def scenario():
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=4), pool=False,
            rpm=0, configured=2600, satisfied=True), delivery_factory=factory)
        count = len(delivery.operations)
        for offset in range(5, 185):
            late = _frame(NOW + timedelta(seconds=offset), pool=True, rpm=2600,
                configured=2600, satisfied=True, solar_active=False, heater_active=False)
            late = replace(late, observations=tuple(replace(item,
                observed_at=NOW + timedelta(seconds=2))
                if item.observation_id in {"pool.active", "pump.rpm"} else item
                for item in late.observations))
            await driver.process_epoch(late, delivery_factory=factory)
        assert len(delivery.operations) == count, "Completed session reacquired PUMP from old ON telemetry"
        assert driver.ownership.filtration_lease is None
    asyncio.run(scenario())


def test_independent_run_now_prospectively_adopts_manual_body_and_completes() -> None:
    async def scenario():
        driver, delivery, factory = _enabled_driver()
        await driver.process_epoch(_frame(NOW, pool=True, rpm=2600,
            configured=2600, solar_active=False, heater_active=False), delivery_factory=factory)
        lease = driver.ownership.filtration_lease
        assert lease is not None and lease.body_adoption is not None
        assert lease.body_activation is None
        assert all(not isinstance(op, SetBodyActive) for op in delivery.operations)
        assert isinstance(delivery.operations[-1], SetPumpSpeed)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=1), pool=True,
            rpm=2600, configured=2600), delivery_factory=factory)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=2), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        assert isinstance(delivery.operations[-1], SetBodyActive)
        assert delivery.operations[-1].active is False
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=False,
            rpm=0, configured=2600, satisfied=True), delivery_factory=factory)
        assert driver.ownership.filtration_lease is None
    asyncio.run(scenario())


@pytest.mark.parametrize("ordinary_session", [False, True])
def test_existing_manual_pump_only_session_new_debt_adopts_completion_prospectively(ordinary_session) -> None:
    async def scenario():
        driver, delivery, factory = _enabled_driver()
        for offset in (0, 1):
            await driver.process_epoch(_frame(NOW + timedelta(seconds=offset),
                pool=True, rpm=2600, configured=2600, satisfied=True,
                solar_active=False, heater_active=False), delivery_factory=factory)
        manual = driver.ownership.filtration_lease
        assert manual is not None and manual.verified
        assert manual.body_activation is None and manual.body_adoption is None
        await driver.process_epoch(_frame(NOW + timedelta(seconds=2), pool=True,
            rpm=2600, configured=2600, solar_active=False, heater_active=False,
            pump_session_id="ordinary-session" if ordinary_session else None,
            pump_session_effective_rpm=2600 if ordinary_session else None),
            delivery_factory=factory)
        adopted = driver.ownership.filtration_lease
        assert adopted is not None and adopted.body_adoption is not None
        assert adopted.generation > manual.generation
        assert adopted.body_activation is None
        assert adopted.body_adoption.adopted_at == NOW + timedelta(seconds=2)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600), delivery_factory=factory)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=4), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        assert isinstance(delivery.operations[-1], SetBodyActive)
        assert not delivery.operations[-1].active
    asyncio.run(scenario())


@pytest.mark.parametrize("thermal", [False, True])
def test_satisfied_manual_pool_stays_external_without_body_off(thermal) -> None:
    async def scenario():
        driver, delivery, factory = _enabled_driver()
        manual_on = ExternalChangeEvent(
            concept="pool.active", semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
            native_object_id="B1101", previous_value=False, new_value=True,
            observed_at=NOW, external_policy=ExternalChangePolicy.ACCEPT,
            action_taken="explicit_operator_request", notification_recommended=False,
            reconciliation_required=False, positive_operator_evidence=PositiveOperatorEvidence(
                request_id="manual-pool-on", authority_generation=1,
                body_session_id="external-manual-session", domain=OwnershipDomain.BODY,
                equipment_id="B1101", requested_at=NOW,
            ),
        )
        for offset in range(180):
            await driver.process_epoch(_frame(NOW + timedelta(seconds=offset),
                pool=True, rpm=2600, configured=2600, satisfied=True,
                solar_active=thermal, heater_active=False,
                changes=ExternalChangeBatch((manual_on,)) if offset == 0 else ExternalChangeBatch(())),
                delivery_factory=factory)
            lease = driver.ownership.filtration_lease
            if lease is not None:
                assert lease.body_activation is None and lease.body_adoption is None
        assert not any(isinstance(op, SetBodyActive) for op in delivery.operations)
        assert len(delivery.operations) <= 1
    asyncio.run(scenario())


def test_pump_operator_override_cannot_be_erased_by_prospective_body_upgrade() -> None:
    async def scenario():
        driver, delivery, factory = _enabled_driver()
        for offset in (0, 1):
            await driver.process_epoch(_frame(NOW + timedelta(seconds=offset),
                pool=True, rpm=2600, configured=2600, satisfied=True,
                solar_active=False, heater_active=False), delivery_factory=factory)
        lease = driver.ownership.filtration_lease
        assert lease is not None
        assert driver.ownership.record_operator_intent(PositiveOperatorEvidence(
            request_id="manual-pump", authority_generation=lease.generation,
            body_session_id=lease.body_session_id, domain=OwnershipDomain.PUMP,
            equipment_id=lease.pool_pump_circuit_id,
            requested_at=NOW + timedelta(seconds=2),
        ), evaluated_at=NOW + timedelta(seconds=2))
        count = len(delivery.operations)
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600, solar_active=False, heater_active=False),
            delivery_factory=factory)
        assert len(delivery.operations) == count
        retained = driver.ownership.filtration_lease
        assert retained is not None and retained.generation == lease.generation
        assert retained.body_adoption is None
        with pytest.raises(ValueError):
            driver.ownership.adopt_filtration_body(session_id="illegal-new-session",
                pool_pump_circuit_id=lease.pool_pump_circuit_id,
                adopted_at=NOW + timedelta(seconds=3), epoch_identity="new",
                reason_code="independent_current_filtration_purpose",
                predecessor_lease_id=lease.lease_id)
    asyncio.run(scenario())


def test_pending_shutdown_evidence_loss_keeps_original_deadline_and_never_reacquires() -> None:
    driver, delivery, factory = _verified_filtration_driver()

    async def scenario():
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        attempt = driver.attempt
        assert attempt is not None
        original = driver.ownership.filtration_lease
        count = len(delivery.operations)
        for offset in range(4, 184):
            await driver.process_epoch(_frame(NOW + timedelta(seconds=offset),
                pool=True, rpm=2600, configured=2600, satisfied=True,
                missing=("pump.rpm",)), delivery_factory=factory)
            assert len(delivery.operations) == count
            assert driver.ownership.filtration_lease.body_activation == original.body_activation
            if driver.attempt is not None:
                assert driver.attempt.deadline == attempt.deadline
        assert driver.attempt is None
        assert driver.ownership.filtration_lease is not None
        assert driver.ownership.filtration_lease.domain_state(OwnershipDomain.BODY).health.value == "faulted"
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["lease_id", "circuit", "chronology", "session", "suspended"])
def test_pump_only_adoption_upgrade_rejects_invalid_predecessor(invalid) -> None:
    driver, delivery, factory = _enabled_driver()
    for offset in (0, 1):
        asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=offset),
            pool=True, rpm=2600, configured=2600, satisfied=True,
            solar_active=False, heater_active=False), delivery_factory=factory))
    lease = driver.ownership.filtration_lease
    assert lease is not None and lease.verified
    if invalid == "suspended":
        driver.ownership.suspend_filtration(session_id=lease.session_id)
    with pytest.raises(ValueError):
        driver.ownership.adopt_filtration_body(
            session_id=lease.session_id if invalid == "session" else "new-purpose",
            pool_pump_circuit_id="p0999" if invalid == "circuit" else lease.pool_pump_circuit_id,
            adopted_at=lease.last_confirmed_at if invalid == "chronology" else NOW + timedelta(seconds=2),
            epoch_identity="new-purpose-epoch", reason_code="independent_current_filtration_purpose",
            predecessor_lease_id="obsolete-lease" if invalid == "lease_id" else lease.lease_id,
        )
    assert driver.ownership.filtration_lease.lease_id == lease.lease_id
    assert driver.ownership.filtration_lease.body_adoption is None


def test_body_off_matching_after_absolute_deadline_is_not_verified_as_timely() -> None:
    driver, delivery, factory = _verified_filtration_driver()

    async def scenario():
        await driver.process_epoch(_frame(NOW + timedelta(seconds=3), pool=True,
            rpm=2600, configured=2600, satisfied=True), delivery_factory=factory)
        original = driver.ownership.filtration_lease
        result = await driver.process_epoch(_frame(NOW + timedelta(seconds=49),
            pool=False, rpm=0, configured=2600, satisfied=True), delivery_factory=factory)
        assert result.blocker == "automatic_filtration_verification_timed_out"
        assert driver.attempt is None
        assert driver.ownership.filtration_lease.body_activation == original.body_activation
        assert len(delivery.operations) == 3
    asyncio.run(scenario())
