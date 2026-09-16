from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from poolos.external_change import ExternalChangeBatch
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
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE

NOW = datetime(2026, 9, 16, 6, 17, tzinfo=UTC)


def _accounting(at: datetime, *, satisfied: bool = False):
    tracker = FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)
    result = tracker.observe(
        FiltrationObservation(
            observed_at=at,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
            water_temperature_f=85,
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


def _observation(concept: str, value: object, at: datetime) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )


def _frame(
    at: datetime,
    *,
    pool: bool,
    rpm: int,
    configured: int,
    satisfied: bool = False,
) -> FiltrationAutomaticExecutionFrame:
    return FiltrationAutomaticExecutionFrame(
        epoch_identity=f"epoch:{at.isoformat()}",
        observed_at=at,
        observations=(
            _observation("pool.active", pool, at),
            _observation("spa.active", False, at),
            _observation("pump.rpm", rpm, at),
            _observation(
                POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
                configured,
                at,
            ),
            _observation("waterfall.active", False, at),
            _observation("jets.active", False, at),
            _observation("slide.active", False, at),
        ),
        filtration=_accounting(at, satisfied=satisfied),
        pool_pump_circuit_id="p0102",
        physical_authority_ready=True,
        physical_authority_blocker=None,
        grid_on=True,
        thermal_candidate_ready=False,
        thermal_owned=False,
        external_changes=ExternalChangeBatch(()),
    )


@dataclass
class _Delivery:
    operations: list[PoolOperation]

    @property
    def available(self) -> bool:
        return True

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        self.operations.append(operation)
        return CommandReceipt(
            status=CommandStatus.ACKNOWLEDGED,
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


def _restarted_enabled_driver():
    delivery = _Delivery([])
    driver = FiltrationAutomaticExecutionDriver(PoolCirculationOwnershipRegistry())
    driver.set_enabled(
        True,
        changed_at=NOW - timedelta(seconds=1),
        current_epoch_identity=None,
    )
    return driver, delivery, _Factory(delivery)


def test_restart_with_current_filtration_need_adopts_body_then_owns_shutdown() -> None:
    """Scenario 52: restart recovery must not strand a valid filtration session."""

    driver, delivery, factory = _restarted_enabled_driver()

    adopting = asyncio.run(
        driver.process_epoch(
            _frame(NOW, pool=True, rpm=2600, configured=2600),
            delivery_factory=factory,
        )
    )

    # Recovery must not cycle the Pool body OFF/ON just to manufacture command
    # provenance.  It explicitly adopts the already-running body and establishes
    # Pump provenance through the normal current 2600-RPM command path.
    assert adopting.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert adopting.blocker is None
    assert len(delivery.operations) == 1
    assert isinstance(delivery.operations[0], SetPumpSpeed)
    assert delivery.operations[0].rpm == 2600
    lease = driver.ownership.filtration_lease
    assert lease is not None
    assert lease.body_activation is None
    assert lease.body_adoption is not None
    assert not lease.verified

    owned = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=1),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    assert owned.state is FiltrationAutomaticDriverState.OWNED
    assert driver.ownership.owner is PoolCirculationOwner.FILTRATION
    lease = driver.ownership.filtration_lease
    assert lease is not None and lease.verified
    assert lease.body_activation is None
    assert lease.body_adoption is not None

    stopping = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=2),
                pool=True,
                rpm=2600,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert stopping.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.operations[-1], SetBodyActive)
    assert delivery.operations[-1].active is False

    stopped = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=3),
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


def test_matching_preexisting_pool_is_not_adopted_after_recovery_boundary() -> None:
    """Matching physical state alone remains insufficient after startup recovery."""

    driver, delivery, factory = _restarted_enabled_driver()

    baseline = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW,
                pool=False,
                rpm=0,
                configured=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert baseline.blocker == "automatic_filtration_not_immediately_required"
    assert not delivery.operations

    later = asyncio.run(
        driver.process_epoch(
            _frame(
                NOW + timedelta(seconds=1),
                pool=True,
                rpm=2600,
                configured=2600,
            ),
            delivery_factory=factory,
        )
    )
    assert later.blocker == "automatic_filtration_preexisting_body_unowned"
    assert not delivery.operations
    assert driver.ownership.owner is PoolCirculationOwner.NONE
