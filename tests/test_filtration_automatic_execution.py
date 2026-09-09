from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.filtration_automatic_execution import (
    FiltrationAutomaticDriverState,
    FiltrationAutomaticExecutionDriver,
    FiltrationAutomaticExecutionFrame,
)
from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationDisposition,
    FiltrationObservation,
)
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import PoolOperation, SetBodyActive, SetPumpSpeed
from poolos.intellicenter_readonly import POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation
from poolos.pool_circulation_ownership import (
    PoolCirculationOwner,
    PoolCirculationOwnershipRegistry,
)
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
)
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE

NOW = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)


def _item(concept: str, value: object, at: datetime) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )


def _accounting(at: datetime, *, satisfied: bool = False):
    tracker = FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)
    result = tracker.observe(
        FiltrationObservation(
            observed_at=at,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
            water_temperature_f=80,
            circulation_evidence_usable=True,
            temperature_evidence_usable=True,
        ),
        safely_deferrable=False,
    )
    if not satisfied:
        return result
    return replace(
        result,
        required_runtime=result.credited_runtime,
        remaining_runtime=timedelta(0),
        total_remaining_runtime=timedelta(0),
        disposition=FiltrationDisposition.SATISFIED,
        independent_disposition=FiltrationDisposition.SATISFIED,
        currently_earning_credit=False,
        reason_code="filtration_obligation_satisfied",
    )


def _frame(
    at: datetime,
    *,
    pool: bool,
    rpm: int,
    configured: int,
    satisfied: bool = False,
    thermal: bool = False,
    changes: ExternalChangeBatch = ExternalChangeBatch(()),
    spa: bool = False,
    missing: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
    degraded: tuple[str, ...] = (),
    suspect: tuple[str, ...] = (),
    low_confidence: tuple[str, ...] = (),
    non_live: tuple[str, ...] = (),
    grid_on: bool = True,
    physical_ready: bool = True,
    pump_circuit_id: str | None = "p0102",
) -> FiltrationAutomaticExecutionFrame:
    values = (
        ("pool.active", pool),
        ("spa.active", spa),
        ("pump.rpm", rpm),
        (POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT, configured),
        ("waterfall.active", False),
        ("jets.active", False),
        ("slide.active", False),
    )
    observations = tuple(
        PoolObservation(
            concept,
            value,
            observed_at=(at - timedelta(minutes=1) if concept in stale else at),
            source_kind=(
                ObservationSourceKind.DERIVED
                if concept in non_live
                else ObservationSourceKind.LIVE
            ),
            source_id=f"native:{concept}",
            quality=(
                ObservationQuality.SUSPECT
                if concept in suspect
                else (
                    ObservationQuality.DEGRADED
                    if concept in degraded
                    else ObservationQuality.GOOD
                )
            ),
            confidence=0.49 if concept in low_confidence else 1.0,
        )
        for concept, value in values
        if concept not in missing
    )
    return FiltrationAutomaticExecutionFrame(
        epoch_identity=f"epoch:{at.isoformat()}",
        observed_at=at,
        observations=observations,
        filtration=_accounting(at, satisfied=satisfied),
        pool_pump_circuit_id=pump_circuit_id,
        physical_authority_ready=physical_ready,
        physical_authority_blocker=(
            None if physical_ready else "physical_authority:maintenance_mode"
        ),
        grid_on=grid_on,
        thermal_candidate_ready=thermal,
        thermal_owned=False,
        external_changes=changes,
    )


@dataclass
class _Delivery:
    operations: list[PoolOperation]
    accepted: bool = True

    @property
    def available(self) -> bool:
        return True

    async def deliver(self, operation: PoolOperation, *, correlation_id: str) -> CommandReceipt:
        self.operations.append(operation)
        return CommandReceipt(
            status=(CommandStatus.ACKNOWLEDGED if self.accepted else CommandStatus.REJECTED),
            command_id=correlation_id,
            message="test",
            issued_at=NOW,
            verification_required=True,
        )


@dataclass
class _Factory:
    delivery: _Delivery

    def for_operation(self, **kwargs: object) -> _Delivery:
        del kwargs
        return self.delivery


def _enabled_driver() -> tuple[FiltrationAutomaticExecutionDriver, _Delivery, _Factory]:
    delivery = _Delivery([])
    driver = FiltrationAutomaticExecutionDriver(PoolCirculationOwnershipRegistry())
    driver.set_enabled(True, changed_at=NOW - timedelta(seconds=1), current_epoch_identity=None)
    return driver, delivery, _Factory(delivery)


def _verified_filtration_driver(
    *,
    at: datetime = NOW,
) -> tuple[FiltrationAutomaticExecutionDriver, _Delivery, _Factory]:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(
        driver.process_epoch(
            _frame(at, pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        driver.process_epoch(
            _frame(
                at + timedelta(seconds=1),
                pool=True,
                rpm=3000,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        driver.process_epoch(
            _frame(
                at + timedelta(seconds=2),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION
    assert driver.ownership.filtration_lease is not None
    assert driver.ownership.filtration_lease.verified
    return driver, delivery, factory


def test_verified_filtration_transient_pool_evidence_loss_retains_cleanup_provenance() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    lease = driver.ownership.filtration_lease
    assert lease is not None
    commands_before = len(delivery.operations)

    suspended = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                missing=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )

    assert suspended.state is FiltrationAutomaticDriverState.SUSPENDED
    assert suspended.blocker == "automatic_filtration_pool_activity_unusable"
    assert not suspended.command_delivery_performed
    assert len(delivery.operations) == commands_before
    assert driver.ownership.filtration_lease == lease
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION_SUSPENDED


def test_live_incident_suspends_until_satisfied_then_completes_owned_shutdown() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    lease = driver.ownership.filtration_lease
    assert lease is not None
    commands_before = len(delivery.operations)

    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                missing=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )
    still_suspended = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=True,
                rpm=2600,
                configured=2600,
                satisfied=True,
                stale=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )
    assert still_suspended.state is FiltrationAutomaticDriverState.SUSPENDED
    assert driver.ownership.filtration_lease == lease
    assert len(delivery.operations) == commands_before

    cleanup = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=5),
                pool=True,
                rpm=2600,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert cleanup.command_delivery_performed
    assert len(delivery.operations) == commands_before + 1
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False

    stopped = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=6),
                pool=False,
                rpm=0,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert stopped.blocker == "automatic_filtration_pool_off_verified"
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == commands_before + 1


def test_suspended_filtration_recovers_running_without_redundant_commands() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    commands_before = len(delivery.operations)
    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                degraded=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )

    recovered = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )

    assert recovered.state is FiltrationAutomaticDriverState.OWNED
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION
    assert len(delivery.operations) == commands_before


def test_verified_filtration_yields_to_spa_and_can_restart_fresh() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    commands_before = len(delivery.operations)

    yielded = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=False,
                spa=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )

    assert yielded.blocker == "automatic_filtration_yielded_to_spa"
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == commands_before

    restarted = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=False,
                spa=False,
                rpm=0,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )

    assert restarted.command_delivery_performed
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is True


def test_manual_pool_off_suppression_blocks_new_filtration_without_adoption() -> None:
    driver, delivery, factory = _enabled_driver()
    frame = replace(
        _frame(NOW + timedelta(seconds=1), pool=False, rpm=0, configured=2600),
        pool_automatic_control_suppressed=True,
    )

    result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    assert result.state is FiltrationAutomaticDriverState.BLOCKED
    assert result.blocker == "automatic_filtration_manual_pool_off_suppressed"
    assert delivery.operations == []
    assert driver.ownership.filtration_lease is None


def test_suspended_filtration_observes_pool_already_off_without_redundant_cleanup() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    commands_before = len(delivery.operations)
    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                low_confidence=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )

    recovered_off = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=False,
                rpm=0,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )

    assert (
        recovered_off.blocker
        == "automatic_filtration_pool_off_observed_after_suspension"
    )
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == commands_before


def test_suspended_filtration_external_takeover_invalidates_cleanup_entitlement() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                non_live=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )
    commands_before = len(delivery.operations)
    takeover = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="PMP01",
        previous_value=2600,
        new_value=2400,
        observed_at=NOW + timedelta(seconds=4),
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=True,
        reconciliation_required=False,
    )

    preempted = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=True,
                rpm=2400,
                configured=2600,
                changes=ExternalChangeBatch((takeover,)),
            ),
            delivery_factory=factory,
        )
    )

    assert preempted.state is FiltrationAutomaticDriverState.PREEMPTED
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == commands_before
    blocked = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=5),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    assert blocked.blocker == "automatic_filtration_reenable_required"


def test_suspended_filtration_identity_or_topology_conflict_remains_preemptive() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                missing=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )
    commands_before = len(delivery.operations)
    changed = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=4),
                pool=True,
                rpm=2600,
                configured=2600,
                pump_circuit_id="p0103",
            ),
            delivery_factory=factory,
        )
    )
    assert changed.blocker == "automatic_filtration_pump_circuit_identity_changed"
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert len(delivery.operations) == commands_before

    other, other_delivery, other_factory = _verified_filtration_driver(
        at=NOW + timedelta(minutes=1)
    )
    asyncio.run(
        other.process_epoch(
            _frame(
                NOW + timedelta(minutes=1, seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                stale=("pool.active",),
            ),
            delivery_factory=other_factory,
        )
    )
    topology = asyncio.run(
        other.process_epoch(
            _frame(
                NOW + timedelta(minutes=1, seconds=4),
                pool=True,
                rpm=2600,
                configured=2600,
                spa=True,
            ),
            delivery_factory=other_factory,
        )
    )
    assert topology.blocker == "automatic_filtration_spa_topology_blocked"
    assert other.ownership.owner is PoolCirculationOwner.NONE
    assert len(other_delivery.operations) == commands_before

    shared, shared_delivery, shared_factory = _verified_filtration_driver(
        at=NOW + timedelta(minutes=2)
    )
    asyncio.run(
        shared.process_epoch(
            _frame(
                NOW + timedelta(minutes=2, seconds=3),
                pool=True,
                rpm=2600,
                configured=2600,
                missing=("pool.active",),
            ),
            delivery_factory=shared_factory,
        )
    )
    shared_frame = _frame(
        NOW + timedelta(minutes=2, seconds=4),
        pool=True,
        rpm=2600,
        configured=2600,
    )
    shared_conflict = asyncio.run(
        shared.process_epoch(
            replace(
                shared_frame,
                observations=tuple(
                    replace(item, value=True)
                    if item.observation_id == "waterfall.active"
                    else item
                    for item in shared_frame.observations
                ),
            ),
            delivery_factory=shared_factory,
        )
    )
    assert (
        shared_conflict.blocker
        == "automatic_filtration_shared_hydraulic_conflict:waterfall.active"
    )
    assert shared.ownership.owner is PoolCirculationOwner.NONE
    assert len(shared_delivery.operations) == commands_before


def test_operator_disable_and_repeated_unusable_epochs_retain_one_bounded_lease() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    lease = driver.ownership.filtration_lease
    assert lease is not None
    commands_before = len(delivery.operations)
    for offset in (3, 60, 3600):
        suspended = asyncio.run(
            driver.process_epoch(
                _frame(
                    NOW + timedelta(seconds=offset),
                    pool=True,
                    rpm=2600,
                    configured=2600,
                    missing=("pool.active",),
                ),
                delivery_factory=factory,
            )
        )
        assert suspended.state is FiltrationAutomaticDriverState.SUSPENDED
        assert driver.ownership.filtration_lease == lease
        assert driver.ownership.owner is PoolCirculationOwner.FILTRATION_SUSPENDED
    driver.set_enabled(
        False,
        changed_at=NOW + timedelta(seconds=3601),
        current_epoch_identity="old",
    )
    still_suspended = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3602),
                pool=True,
                rpm=2600,
                configured=2600,
                missing=("pool.active",),
            ),
            delivery_factory=factory,
        )
    )
    assert still_suspended.state is FiltrationAutomaticDriverState.SUSPENDED
    assert driver.ownership.filtration_lease == lease
    assert len(delivery.operations) == commands_before

    cleanup = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3603),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    assert cleanup.command_delivery_performed
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False


def test_off_to_filtration_owned_to_off_is_closed_loop_and_provenance_based() -> None:
    driver, delivery, factory = _enabled_driver()

    started = asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    assert started.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is True
    assert driver.ownership.filtration_lease is not None
    assert driver.ownership.filtration_lease.body_activation is not None

    pump_requested = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600),
            delivery_factory=factory,
        )
    )
    assert pump_requested.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.operations[-1], SetPumpSpeed)
    assert delivery.operations[-1].rpm == 2600

    owned = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=2), pool=True, rpm=2600, configured=2600),
            delivery_factory=factory,
        )
    )
    assert owned.state is FiltrationAutomaticDriverState.OWNED
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION
    assert driver.ownership.filtration_lease is not None
    assert driver.ownership.filtration_lease.verified

    stopping = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=3), pool=True, rpm=2600, configured=2600, satisfied=True),
            delivery_factory=factory,
        )
    )
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False
    assert stopping.command_delivery_performed

    stopped = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=4), pool=False, rpm=0, configured=2600, satisfied=True),
            delivery_factory=factory,
        )
    )
    assert stopped.blocker == "automatic_filtration_pool_off_verified"
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None


def test_crediting_cannot_perpetuate_owned_filtration_when_independently_deferrable() -> None:
    driver, delivery, factory = _verified_filtration_driver()
    current = _frame(
        NOW + timedelta(seconds=3),
        pool=True,
        rpm=2600,
        configured=2600,
    )
    assert current.filtration is not None
    current = replace(
        current,
        filtration=replace(
            current.filtration,
            disposition=FiltrationDisposition.CREDITING,
            independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
            currently_earning_credit=True,
            reason_code="qualifying_filtration_credit_in_progress",
        ),
    )

    result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))

    assert result.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False


def test_complete_off_filtration_thermal_filtration_off_ownership_lifecycle() -> None:
    ownership = PoolCirculationOwnershipRegistry()
    delivery = _Delivery([])
    factory = _Factory(delivery)
    filtration = FiltrationAutomaticExecutionDriver(ownership)
    filtration.set_enabled(
        True,
        changed_at=NOW - timedelta(seconds=1),
        current_epoch_identity=None,
    )

    asyncio.run(
        filtration.process_epoch(
            _frame(NOW, pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        filtration.process_epoch(
            _frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        filtration.process_epoch(
            _frame(NOW + timedelta(seconds=2), pool=True, rpm=2600, configured=2600),
            delivery_factory=factory,
        )
    )
    assert ownership.owner is PoolCirculationOwner.FILTRATION
    original = ownership.filtration_lease
    assert original is not None and original.body_activation is not None

    thermal_epoch = _frame(
        NOW + timedelta(seconds=3),
        pool=True,
        rpm=2600,
        configured=2600,
        thermal=True,
    )
    ownership.begin_epoch(thermal_epoch.epoch_identity)
    assert ownership.reserve_thermal(thermal_epoch.epoch_identity)
    handoff = ownership.begin_filtration_to_thermal(
        thermal_purpose_id="gas-purpose",
        established_at=thermal_epoch.observed_at,
    )
    assert handoff is not None
    ownership.complete_filtration_to_thermal(
        token_id=handoff.token_id,
        thermal_lease_id="thermal-lease",
    )
    assert ownership.owner is PoolCirculationOwner.THERMAL
    assert ownership.filtration_lease is None

    ownership.accept_thermal_to_filtration(
        session_id="thermal-to-filtration",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW + timedelta(seconds=4),
        body_activation=handoff.body_activation,
        pump_setpoint=ThermalRuntimeConceptProvenance(
            concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
            operation_id="thermal-cleanup-pump-operation",
            receipt_id="thermal-cleanup-pump-receipt",
            correlation_id="thermal-cleanup-pump-correlation",
            intended_value=2600,
        ),
    )
    assert ownership.owner is PoolCirculationOwner.FILTRATION

    stopping = asyncio.run(
        filtration.process_epoch(
            _frame(
                NOW + timedelta(seconds=5),
                pool=True,
                rpm=2600,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert stopping.command_delivery_performed
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False
    asyncio.run(
        filtration.process_epoch(
            _frame(
                NOW + timedelta(seconds=6),
                pool=False,
                rpm=0,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert ownership.owner is PoolCirculationOwner.NONE
    assert ownership.filtration_lease is None


def test_preexisting_matching_pool_circulation_is_never_adopted() -> None:
    driver, delivery, factory = _enabled_driver()
    result = asyncio.run(
        driver.process_epoch(
            _frame(NOW, pool=True, rpm=2600, configured=2600),
            delivery_factory=factory,
        )
    )
    assert result.blocker == "automatic_filtration_preexisting_body_unowned"
    assert not delivery.operations
    assert driver.ownership.filtration_lease is None


def test_thermal_candidate_preempts_new_filtration_delivery() -> None:
    driver, delivery, factory = _enabled_driver()
    frame = _frame(NOW, pool=False, rpm=0, configured=2600, thermal=True)
    driver.ownership.begin_epoch(frame.epoch_identity)
    driver.ownership.reserve_thermal(frame.epoch_identity)
    result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
    assert result.blocker == "automatic_filtration_circulation_owner_conflict"
    assert not delivery.operations


def test_rejected_delivery_establishes_no_ownership_and_requires_reenable() -> None:
    driver, delivery, factory = _enabled_driver()
    delivery.accepted = False
    result = asyncio.run(
        driver.process_epoch(
            _frame(NOW, pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    assert result.state is FiltrationAutomaticDriverState.FAILED
    assert driver.ownership.filtration_lease is None
    later = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=1), pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    assert later.blocker == "automatic_filtration_reenable_required"
    assert len(delivery.operations) == 1


def test_restart_with_matching_hardware_reconstructs_no_ownership() -> None:
    restarted = FiltrationAutomaticExecutionDriver(PoolCirculationOwnershipRegistry())
    assert restarted.ownership.owner is PoolCirculationOwner.NONE
    assert restarted.ownership.filtration_lease is None


def test_non_immediate_spa_shared_hydraulic_and_missing_evidence_all_block() -> None:
    cases = (
        (_frame(NOW, pool=False, rpm=0, configured=2600, satisfied=True), "automatic_filtration_not_immediately_required"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, spa=True), "automatic_filtration_spa_topology_blocked"),
        (
            replace(
                _frame(NOW, pool=False, rpm=0, configured=2600),
                observations=tuple(
                    replace(item, value=True)
                    if item.observation_id == "waterfall.active"
                    else item
                    for item in _frame(NOW, pool=False, rpm=0, configured=2600).observations
                ),
            ),
            "automatic_filtration_shared_hydraulic_conflict:waterfall.active",
        ),
        (_frame(NOW, pool=False, rpm=0, configured=2600, missing=("jets.active",)), "automatic_filtration_shared_hydraulic_unusable:jets.active"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, stale=("slide.active",)), "automatic_filtration_shared_hydraulic_unusable:slide.active"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, missing=("pool.active",)), "automatic_filtration_pool_activity_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, stale=("spa.active",)), "automatic_filtration_spa_activity_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, degraded=("pool.active",)), "automatic_filtration_pool_activity_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, degraded=("jets.active",)), "automatic_filtration_shared_hydraulic_unusable:jets.active"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, missing=("pump.rpm",)), "automatic_filtration_pump_observation_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, missing=(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,)), "automatic_filtration_configured_speed_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, low_confidence=("pool.active",)), "automatic_filtration_pool_activity_unusable"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, non_live=("spa.active",)), "automatic_filtration_spa_activity_unusable"),
        (_frame(NOW, pool=False, rpm=1200, configured=2600), "automatic_filtration_preexisting_pump_unowned"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, suspect=("waterfall.active",)), "automatic_filtration_shared_hydraulic_unusable:waterfall.active"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, pump_circuit_id=None), "automatic_filtration_pool_pump_circuit_unresolved"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, grid_on=False), "automatic_filtration_grid_not_authoritatively_on"),
        (_frame(NOW, pool=False, rpm=0, configured=2600, physical_ready=False), "physical_authority:maintenance_mode"),
    )
    for frame, reason in cases:
        driver, delivery, factory = _enabled_driver()
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        assert result.blocker == reason
        assert delivery.operations == []
        assert driver.ownership.owner is PoolCirculationOwner.NONE


def test_verification_requires_later_exact_configured_speed_and_tolerant_actual_rpm() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600), delivery_factory=factory))

    pending = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=2), pool=True, rpm=2625, configured=2599),
            delivery_factory=factory,
        )
    )
    assert pending.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION_ACQUIRING

    owned = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=3), pool=True, rpm=2575, configured=2600),
            delivery_factory=factory,
        )
    )
    assert owned.state is FiltrationAutomaticDriverState.OWNED
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION


def test_verification_timeout_fails_closed_without_fabricated_ownership() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600),
            delivery_factory=factory,
        )
    )
    timed_out = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=47), pool=True, rpm=2000, configured=2500),
            delivery_factory=factory,
        )
    )
    assert timed_out.state is FiltrationAutomaticDriverState.FAILED
    assert timed_out.blocker == "automatic_filtration_verification_timed_out"
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == 2


def test_manual_pool_off_and_dynamic_pump_identity_change_preempt_without_restart() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=2), pool=True, rpm=2600, configured=2600), delivery_factory=factory))
    before = len(delivery.operations)

    stopped = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=3), pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    assert stopped.state is FiltrationAutomaticDriverState.PREEMPTED
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert len(delivery.operations) == before

    other, other_delivery, other_factory = _enabled_driver()
    asyncio.run(other.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=other_factory))
    changed = asyncio.run(
        other.process_epoch(
            _frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600, pump_circuit_id="p0103"),
            delivery_factory=other_factory,
        )
    )
    assert changed.blocker == "automatic_filtration_pump_circuit_identity_changed"
    assert other.ownership.owner is PoolCirculationOwner.NONE
    assert len(other_delivery.operations) == 1


def test_external_change_after_lease_preempts_but_prelease_event_does_not() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    prelease = ExternalChangeEvent(
        concept="pool.active",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="B1101",
        previous_value=False,
        new_value=True,
        observed_at=NOW - timedelta(seconds=1),
        external_policy=ExternalChangePolicy.OBSERVE,
        action_taken="observed",
        notification_recommended=True,
        reconciliation_required=False,
    )
    continued = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=1),
                pool=True,
                rpm=3000,
                configured=2600,
                changes=ExternalChangeBatch((prelease,)),
            ),
            delivery_factory=factory,
        )
    )
    assert continued.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    postlease = replace(prelease, observed_at=NOW + timedelta(seconds=2))
    preempted = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=2),
                pool=True,
                rpm=2600,
                configured=2600,
                changes=ExternalChangeBatch((postlease,)),
            ),
            delivery_factory=factory,
        )
    )
    assert preempted.state is FiltrationAutomaticDriverState.PREEMPTED
    assert driver.ownership.owner is PoolCirculationOwner.NONE


def test_normal_startup_prime_and_aligned_actual_rpm_do_not_self_preempt() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(
        driver.process_epoch(
            _frame(NOW, pool=False, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    rpm_event = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="PMP01",
        previous_value=0,
        new_value=3000,
        observed_at=NOW + timedelta(seconds=1),
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )
    asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=1),
                pool=True,
                rpm=3000,
                configured=2600,
                changes=ExternalChangeBatch((rpm_event,)),
            ),
            delivery_factory=factory,
        )
    )
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION_ACQUIRING
    aligned = replace(
        rpm_event,
        previous_value=3000,
        new_value=2625,
        observed_at=NOW + timedelta(seconds=2),
    )
    result = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=2),
                pool=True,
                rpm=2625,
                configured=2600,
                changes=ExternalChangeBatch((rpm_event, aligned)),
            ),
            delivery_factory=factory,
        )
    )
    assert result.state is FiltrationAutomaticDriverState.OWNED
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION


def test_material_actual_rpm_change_after_pump_provenance_preempts() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600), delivery_factory=factory))
    event = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="PMP01",
        previous_value=3000,
        new_value=2900,
        observed_at=NOW + timedelta(seconds=2),
        external_policy=ExternalChangePolicy.RECONCILE,
        action_taken="reconciliation_required",
        notification_recommended=True,
        reconciliation_required=True,
    )
    result = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=2),
                pool=True,
                rpm=2900,
                configured=2600,
                changes=ExternalChangeBatch((event,)),
            ),
            delivery_factory=factory,
        )
    )
    assert result.state is FiltrationAutomaticDriverState.PREEMPTED
    assert driver.ownership.owner is PoolCirculationOwner.NONE


def test_disable_owned_session_uses_fresh_provenance_bound_body_cleanup() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=1), pool=True, rpm=3000, configured=2600), delivery_factory=factory))
    asyncio.run(driver.process_epoch(_frame(NOW + timedelta(seconds=2), pool=True, rpm=2600, configured=2600), delivery_factory=factory))
    driver.set_enabled(False, changed_at=NOW + timedelta(seconds=3), current_epoch_identity="old")
    cleanup = asyncio.run(
        driver.process_epoch(
            _frame(NOW + timedelta(seconds=4), pool=True, rpm=2600, configured=2600),
            delivery_factory=factory,
        )
    )
    assert cleanup.command_delivery_performed
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False


def test_unload_clears_pending_and_verified_ownership_without_command() -> None:
    driver, delivery, factory = _enabled_driver()
    asyncio.run(driver.process_epoch(_frame(NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory))
    driver.unload(unloaded_at=NOW + timedelta(seconds=1))
    assert driver.ownership.owner is PoolCirculationOwner.NONE
    assert driver.ownership.filtration_lease is None
    assert len(delivery.operations) == 1
