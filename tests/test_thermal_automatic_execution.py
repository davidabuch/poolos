from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import PoolOperation, ThermalBody
from poolos.native_configuration_policy import (
    NativeConfigurationGuard,
    NativeConfigurationInput,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
    ThermalAutomaticExecutionFrame,
)
from poolos.thermal_live_execution import (
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionPolicy,
)
from poolos.thermal_runtime_assessment import (
    ThermalRequestedMode,
    ThermalRuntimeEvaluator,
    ThermalRuntimeEvidence,
)
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus


NOW = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)


@dataclass
class FakeDelivery:
    available: bool = True
    calls: list[PoolOperation] = field(default_factory=list)

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        self.calls.append(operation)
        return CommandReceipt(
            status=CommandStatus.ACKNOWLEDGED,
            command_id=correlation_id,
            issued_at=NOW,
            acknowledged_at=NOW,
            verification_required=True,
        )


@dataclass
class FakeDeliveryFactory:
    delivery: FakeDelivery
    bindings: list[tuple[str, str]] = field(default_factory=list)

    def for_session(self, session, *, epoch_identity: str):
        self.bindings.append((session.execution_plan.plan_id, epoch_identity))
        return self.delivery


def _observation(concept: str, value: object, at: datetime) -> PoolObservation:
    return PoolObservation(
        observation_id=concept,
        value=value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"native:{concept}",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )


def _values(
    *,
    pool_active: bool,
    spa_active: bool = False,
    pump_rpm: int = 0,
    pool_heater: str = "00000",
    configured_rpm: int = 2600,
    grid_outage_active: bool = False,
) -> dict[str, object]:
    return {
        "pool.active": pool_active,
        "pool.temperature": 80.0,
        "pool.target_temperature": 90.0,
        "pool.raw_heater_id": pool_heater,
        "pool.raw_htmode": "0",
        "spa.active": spa_active,
        "spa.temperature": 98.0,
        "spa.target_temperature": 101.0,
        "spa.raw_heater_id": "00000",
        "spa.raw_htmode": "0",
        "pump.rpm": pump_rpm,
        "pump_circuit.p0102.configured_speed_rpm": configured_rpm,
        "solar.temperature": 110.0,
        "solar.active": False,
        "grid.outage_active": grid_outage_active,
        "waterfall.active": False,
        "jets.active": False,
        "slide.active": False,
    }


def _frame(
    orchestrator: ThermalRuntimeOrchestrator,
    at: datetime,
    *,
    pool_active: bool,
    pump_rpm: int = 0,
    pool_heater: str = "00000",
    configured_rpm: int = 2600,
    mode: ThermalRequestedMode = ThermalRequestedMode.GAS,
    missing: tuple[str, ...] = (),
    evaluator: ThermalRuntimeEvaluator | None = None,
    grid_outage_active: bool = False,
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalAutomaticExecutionFrame:
    values = _values(
        pool_active=pool_active,
        spa_active=body is ThermalBody.HOT_TUB,
        pump_rpm=pump_rpm,
        pool_heater=pool_heater,
        configured_rpm=configured_rpm,
        grid_outage_active=grid_outage_active,
    )
    for concept in missing:
        values.pop(concept, None)
    observations = tuple(
        _observation(concept, value, at)
        for concept, value in values.items()
        if concept
        in {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pump_circuit.p0102.configured_speed_rpm",
            "pool.raw_heater_id",
            "spa.raw_heater_id",
            "grid.outage_active",
            "waterfall.active",
            "jets.active",
            "slide.active",
        }
    )
    policy = ThermalLiveExecutionPolicy(
        thermal_live_execution_enabled=True,
        commissioning_scope=(
            ThermalLiveCommissioningScope.POOL
            if body is ThermalBody.POOL
            else ThermalLiveCommissioningScope.HOT_TUB
        ),
    )
    thermal = (evaluator or ThermalRuntimeEvaluator()).evaluate(
        ThermalRuntimeEvidence(
            evaluated_at=at,
            native_values=values,
            native_observed_at={concept: at for concept in values},
            pool_requested_mode=(
                mode if body is ThermalBody.POOL else ThermalRequestedMode.OFF
            ),
            hot_tub_requested_mode=(
                mode if body is ThermalBody.HOT_TUB else ThermalRequestedMode.OFF
            ),
            native_transport_available=True,
            manual_transport_available=True,
            immediate_observation_healthy=True,
            stale_native_concepts=(),
            missing_native_concepts=missing,
            native_configuration=NativeConfigurationGuard().evaluate(
                NativeConfigurationInput()
            ),
        ),
        live_policy=policy,
    )
    orchestration = orchestrator.refresh(
        generated_at=at,
        observations=observations,
        thermal=thermal,
    )
    return ThermalAutomaticExecutionFrame(
        epoch_identity=orchestration.snapshot_identity,
        observed_at=at,
        observations=observations,
        thermal=thermal,
        orchestration=orchestration,
        live_policy=policy,
        physical_authority_ready=True,
    )


def test_driver_defaults_off_and_enable_requires_a_new_epoch() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    cached = _frame(orchestrator, NOW, pool_active=False)

    disabled = driver.note_disabled_epoch(cached)
    enabled = driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=cached.epoch_identity,
    )
    replay = asyncio.run(driver.process_epoch(cached, delivery_factory=factory))

    assert disabled.state is ThermalAutomaticDriverState.DISABLED
    assert enabled.state is ThermalAutomaticDriverState.BLOCKED
    assert replay is enabled
    assert delivery.calls == []


def test_cold_start_delivers_at_most_one_command_per_authoritative_epoch() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    first = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(first)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=first.epoch_identity,
    )
    second = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)

    waiting_body = asyncio.run(
        driver.process_epoch(second, delivery_factory=factory)
    )
    duplicate = asyncio.run(
        driver.process_epoch(second, delivery_factory=factory)
    )

    assert waiting_body.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert duplicate is waiting_body
    assert [type(item).__name__ for item in delivery.calls] == ["SetBodyActive"]

    third = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        pump_rpm=0,
    )
    waiting_prime = asyncio.run(
        driver.process_epoch(third, delivery_factory=factory)
    )
    assert waiting_prime.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert [type(item).__name__ for item in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
    ]


def test_priming_hold_uses_later_epochs_and_never_chains_delivery() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    first = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(first)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=first.epoch_identity)
    for frame in (
        _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
        _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=True),
    ):
        asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    holding = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
    )
    result = asyncio.run(driver.process_epoch(holding, delivery_factory=factory))
    assert result.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
    assert len(delivery.calls) == 2

    held = _frame(
        orchestrator,
        NOW + timedelta(seconds=63),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
    )
    result = asyncio.run(driver.process_epoch(held, delivery_factory=factory))
    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert [type(item).__name__ for item in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
        "SetHeatMode",
    ]


def test_probe_plan_is_rejected_whole_before_body_activation() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    first = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(first)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=first.epoch_identity)
    probe = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        evaluator=evaluator,
    )

    result = asyncio.run(driver.process_epoch(probe, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert result.blocker is not None
    assert "nonthermal_or_uncommissioned_pump_rpm" in result.blocker
    assert delivery.calls == []


def test_preexisting_pool_circulation_and_hot_tub_fail_closed() -> None:
    pool_orchestrator = ThermalRuntimeOrchestrator()
    pool_driver = ThermalAutomaticExecutionDriver(pool_orchestrator)
    pool_driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    pool = _frame(
        pool_orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
    )
    delivery = FakeDelivery()
    result = asyncio.run(
        pool_driver.process_epoch(pool, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.blocker == "automatic_thermal_preexisting_body_unowned"
    assert delivery.calls == []

    hot_tub_orchestrator = ThermalRuntimeOrchestrator()
    hot_tub_driver = ThermalAutomaticExecutionDriver(hot_tub_orchestrator)
    hot_tub_driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    hot_tub = _frame(
        hot_tub_orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
        body=ThermalBody.HOT_TUB,
    )
    hot_tub_delivery = FakeDelivery()

    blocked = asyncio.run(
        hot_tub_driver.process_epoch(
            hot_tub,
            delivery_factory=FakeDeliveryFactory(hot_tub_delivery),
        )
    )

    assert blocked.blocker == "automatic_thermal_hot_tub_pump_ownership_unproven"
    assert hot_tub_delivery.calls == []


def test_physical_authority_and_thermal_live_gates_fail_closed() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    frame = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    delivery = FakeDelivery()

    physical_blocked = asyncio.run(
        driver.process_epoch(
            replace(
                frame,
                physical_authority_ready=False,
                physical_authority_blocker="physical_authority:maintenance_mode",
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert physical_blocked.blocker == "physical_authority:maintenance_mode"
    assert delivery.calls == []

    other_orchestrator = ThermalRuntimeOrchestrator()
    other_driver = ThermalAutomaticExecutionDriver(other_orchestrator)
    other_driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    other_frame = _frame(
        other_orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
    )
    live_blocked = asyncio.run(
        other_driver.process_epoch(
            replace(
                other_frame,
                live_policy=replace(
                    other_frame.live_policy,
                    thermal_live_execution_enabled=False,
                ),
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert live_blocked.state is ThermalAutomaticDriverState.BLOCKED
    assert delivery.calls == []


def test_pending_outage_blocks_before_session_or_delivery() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    pending = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
        grid_outage_active=True,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(pending, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert result.blocker == "automatic_thermal_grid_not_authoritatively_on"
    assert delivery.calls == []


def test_true_requested_mode_supersession_terminates_without_next_delivery() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    active = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    asyncio.run(driver.process_epoch(active, delivery_factory=factory))

    superseding = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        mode=ThermalRequestedMode.OFF,
    )
    result = asyncio.run(driver.process_epoch(superseding, delivery_factory=factory))

    assert result.state in {
        ThermalAutomaticDriverState.SUPERSEDED,
        ThermalAutomaticDriverState.BLOCKED,
    }
    assert len(delivery.calls) == 1
    assert driver.active_session is None
    assert orchestrator.ownership.state.status is not ThermalRuntimeOwnershipStatus.OWNED


def test_disable_relinquishes_session_and_never_replays_it() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    active = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    asyncio.run(driver.process_epoch(active, delivery_factory=factory))

    disabled = driver.set_enabled(
        False,
        changed_at=NOW + timedelta(seconds=2),
        current_epoch_identity=active.epoch_identity,
    )
    later = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
    )
    replay = asyncio.run(driver.process_epoch(later, delivery_factory=factory))

    assert disabled.state is ThermalAutomaticDriverState.DISABLED
    assert replay.state is ThermalAutomaticDriverState.DISABLED
    assert len(delivery.calls) == 1
    assert driver.active_session is None
    assert orchestrator.ownership.state.status is not ThermalRuntimeOwnershipStatus.OWNED


@dataclass
class RejectingDelivery(FakeDelivery):
    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        self.calls.append(operation)
        return CommandReceipt(
            status=CommandStatus.REJECTED,
            command_id=correlation_id,
            issued_at=NOW,
            acknowledged_at=NOW,
            verification_required=False,
            detail="rejected by test boundary",
        )


def test_rejected_delivery_fails_closed_without_retry_or_ownership() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = RejectingDelivery()
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    active = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)

    result = asyncio.run(
        driver.process_epoch(
            active,
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert len(delivery.calls) == 1
    assert driver.active_session is None
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
