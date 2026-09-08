from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from poolos.circulation_successor import (
    FiltrationSuccessorEvidence,
    FiltrationTargetSemantics,
)
from poolos.hal import CommandReceipt, CommandStatus
from poolos.external_change import ExternalChangeBatch, ExternalChangeEvent
from poolos.filtration_policy import FiltrationDisposition
from poolos.integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from poolos.native_configuration_policy import (
    NativeConfigurationGuard,
    NativeConfigurationInput,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from poolos.pool_temperature_probe_execution import (
    PoolTemperatureProbeContinuityEvidence,
    PoolTemperatureProbeExecutionPhase,
)
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
    ThermalAutomaticExecutionFrame,
)
from poolos.thermal_circulation_cleanup import (
    ThermalCirculationCleanupCandidate,
    ThermalCirculationCleanupProvenance,
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

    def for_termination(self, *, body, entitlement_id: str, epoch_identity: str):
        self.bindings.append((f"termination:{entitlement_id}", epoch_identity))
        return self.delivery

    def for_cleanup(
        self,
        candidate: ThermalCirculationCleanupCandidate,
        *,
        epoch_identity: str,
    ):
        self.bindings.append((f"cleanup:{candidate.candidate_id}", epoch_identity))
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
    solar_active: bool = False,
    solar_temperature: float = 110.0,
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
        "pool.pump_circuit.configured_speed_rpm": configured_rpm,
        "solar.temperature": solar_temperature,
        "solar.active": solar_active,
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
    solar_active: bool = False,
    solar_observation_observed_at: datetime | None = None,
    omit_solar_observation: bool = False,
    solar_temperature: float = 110.0,
    body: ThermalBody = ThermalBody.POOL,
    filtration_remaining: timedelta | None = None,
    driver: ThermalAutomaticExecutionDriver | None = None,
) -> ThermalAutomaticExecutionFrame:
    values = _values(
        pool_active=pool_active,
        spa_active=body is ThermalBody.HOT_TUB,
        pump_rpm=pump_rpm,
        pool_heater=pool_heater,
        configured_rpm=configured_rpm,
        grid_outage_active=grid_outage_active,
        solar_active=solar_active,
        solar_temperature=solar_temperature,
    )
    for concept in missing:
        values.pop(concept, None)
    observations = tuple(
        _observation(
            concept,
            value,
            (
                solar_observation_observed_at
                if concept == "solar.active"
                and solar_observation_observed_at is not None
                else at
            ),
        )
        for concept, value in values.items()
        if concept
        in {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.pump_circuit.configured_speed_rpm",
            "pool.raw_heater_id",
            "spa.raw_heater_id",
            "solar.active",
            "grid.outage_active",
            "waterfall.active",
            "jets.active",
            "slide.active",
        }
        and not (omit_solar_observation and concept == "solar.active")
    )
    policy = ThermalLiveExecutionPolicy(
        thermal_live_execution_enabled=True,
        commissioning_scope=(
            ThermalLiveCommissioningScope.POOL
            if body is ThermalBody.POOL
            else ThermalLiveCommissioningScope.HOT_TUB
        ),
    )
    probe_execution = None if driver is None else driver.probe_execution_evidence()
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
            pool_pump_circuit_id="p0102",
            pool_temperature_probe_execution=probe_execution,
            pool_temperature_probe_continuity=(
                PoolTemperatureProbeContinuityEvidence(evaluated_at=at, valid=True)
                if probe_execution is not None
                and probe_execution.phase
                is PoolTemperatureProbeExecutionPhase.ACQUIRING
                else None
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
        filtration_successor=(
            None
            if filtration_remaining is None
            else FiltrationSuccessorEvidence(
                evaluated_at=at,
                disposition=(
                    FiltrationDisposition.RUN_NOW
                    if filtration_remaining > timedelta(0)
                    else FiltrationDisposition.SATISFIED
                ),
                total_remaining_runtime=filtration_remaining,
                currently_earning_credit=False,
                immediate_circulation_required=filtration_remaining > timedelta(0),
                successor_target_rpm=(
                    2600 if filtration_remaining > timedelta(0) else None
                ),
                target_semantics=(
                    FiltrationTargetSemantics.ORDINARY_POLICY_BASELINE
                    if filtration_remaining > timedelta(0)
                    else FiltrationTargetSemantics.NONE
                ),
            )
        ),
    )


def _driver_with_residual_body_entitlement():
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    active = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    asyncio.run(driver.process_epoch(active, delivery_factory=factory))
    ending = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        mode=ThermalRequestedMode.OFF,
    )
    asyncio.run(driver.process_epoch(ending, delivery_factory=factory))
    assert orchestrator.ownership.residual_termination is not None
    return orchestrator, driver, factory


def _driver_awaiting_source_off_verification():
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    for item in (
        _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
        _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=True),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=3),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=63),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=64),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
            pool_heater="H0001",
        ),
    ):
        asyncio.run(driver.process_epoch(item, delivery_factory=factory))
    ending = _frame(
        orchestrator,
        NOW + timedelta(seconds=65),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        mode=ThermalRequestedMode.OFF,
    )
    requested = asyncio.run(driver.process_epoch(ending, delivery_factory=factory))
    assert requested.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert driver.termination_attempt is not None
    return orchestrator, driver, factory, ending, requested


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


def test_quiescent_solar_cold_start_verifies_h0002_before_engagement() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()

    # Establish bounded trusted-water reuse before the Pool becomes quiescent.
    _frame(
        ThermalRuntimeOrchestrator(),
        NOW - timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
    )
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=2900,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
    )
    assert baseline.thermal is not None
    assert baseline.thermal.pool.plan.desired.selected_source.value == "solar"
    assert baseline.orchestration.candidate_body is ThermalBody.POOL
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    sequence = (
        (1, False, 0, 2900, "00000"),
        (2, True, 0, 2900, "00000"),
        (3, True, 3000, 3000, "00000"),
        (63, True, 3000, 3000, "00000"),
        (64, True, 2900, 2900, "00000"),
        (65, True, 2900, 2900, "H0002"),
    )
    result = None
    for seconds, active, rpm, configured, heater in sequence:
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    pool_heater=heater,
                    mode=ThermalRequestedMode.SOLAR,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    assert result is not None
    assert result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert driver.solar_engagement_attempt is not None
    assert [type(item).__name__ for item in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
        "SetPumpSpeed",
        "SetHeatMode",
    ]
    assert [
        item.rpm for item in delivery.calls if isinstance(item, SetPumpSpeed)
    ] == [3000, 2900]
    assert delivery.calls[-1].mode.value == "solar"
    assert result.runtime_ownership_summary["owns_body_activation"] is True
    assert result.runtime_ownership_summary["owns_pump_setpoint"] is True
    assert result.runtime_ownership_summary["owns_heat_source"] is True
    calls_before_observation = len(delivery.calls)
    missing = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=66),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert missing.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert missing.blocker == "automatic_thermal_solar_engagement_evidence_unusable_pending"
    assert driver.solar_engagement_attempt is not None
    assert driver.solar_engagement_attempt.engaged_since is None
    assert driver.cleanup_attempt is None
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert driver.diagnostics()["solar_retry_suppressed_until"] is None
    assert len(delivery.calls) == calls_before_observation

    stale = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=67),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                solar_observation_observed_at=NOW,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert stale.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert stale.blocker == "automatic_thermal_solar_engagement_evidence_unusable_pending"
    assert driver.solar_engagement_attempt is not None
    assert driver.solar_engagement_attempt.engaged_since is None
    assert driver.cleanup_attempt is None
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED

    first_engaged = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=70),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert first_engaged.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert driver.solar_engagement_attempt is not None
    assert driver.solar_engagement_attempt.engaged_since == NOW + timedelta(seconds=70)

    interrupted = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=80),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert interrupted.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert driver.solar_engagement_attempt is not None
    assert driver.solar_engagement_attempt.engaged_since is None

    restarted_hold = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=90),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert restarted_hold.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    confirmed = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=120),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert confirmed.state is ThermalAutomaticDriverState.CONVERGED
    assert confirmed.blocker == "automatic_thermal_solar_engaged"


def test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    _frame(
        ThermalRuntimeOrchestrator(),
        NOW - timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
    )
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=2900,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    for seconds, active, rpm, configured, heater in (
        (1, False, 0, 2900, "00000"),
        (2, True, 0, 2900, "00000"),
        (3, True, 3000, 3000, "00000"),
        (63, True, 3000, 3000, "00000"),
        (64, True, 2900, 2900, "00000"),
        (65, True, 2900, 2900, "H0002"),
    ):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    pool_heater=heater,
                    solar_active=False,
                    mode=ThermalRequestedMode.SOLAR,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    unknown = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=66),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert unknown.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    assert unknown.blocker == "automatic_thermal_solar_engagement_evidence_unusable_pending"
    assert driver.solar_engagement_attempt is not None
    assert driver.cleanup_attempt is None
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert driver.diagnostics()["solar_retry_suppressed_until"] is None

    timed_out = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=365),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert timed_out.state is ThermalAutomaticDriverState.TERMINATING
    assert timed_out.blocker == "automatic_thermal_solar_not_engaged"
    assert driver.solar_engagement_attempt is None
    assert driver.diagnostics()["solar_retry_suppressed_until"] is not None

    source_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=366),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert source_off.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.OFF
    relinquished = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=367),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert relinquished.state is ThermalAutomaticDriverState.CONVERGED
    cleanup = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=368),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert cleanup.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION, (
        cleanup.state,
        cleanup.blocker,
    )
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is False

    stopped = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=369),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert stopped.state is ThermalAutomaticDriverState.CONVERGED
    retry = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=370),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert retry.state is ThermalAutomaticDriverState.BLOCKED
    assert retry.blocker == "automatic_thermal_solar_opportunity_retry_suppressed"


def test_probe_plan_can_begin_with_exact_pool_body_activation() -> None:
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

    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetBodyActive)


@pytest.mark.parametrize(
    ("mode", "solar_temperature", "successor_rpm", "successor_source"),
    (
        (ThermalRequestedMode.SOLAR, 110.0, 2900, PhysicalHeatMode.SOLAR),
        (
            ThermalRequestedMode.SOLAR_PREFERRED,
            70.0,
            3000,
            PhysicalHeatMode.GAS,
        ),
    ),
)
def test_cold_start_probe_hands_off_to_fresh_thermal_provenance(
    mode: ThermalRequestedMode,
    solar_temperature: float,
    successor_rpm: int,
    successor_source: PhysicalHeatMode,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        mode=mode,
        solar_temperature=110.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    sequence = (
        (1, False, 0, 2600),
        (2, True, 0, 2600),
        (3, True, 3000, 3000),
        (63, True, 3000, 3000),
        (64, True, 1500, 1500),
    )
    for seconds, active, rpm, configured in sequence:
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=active,
            pump_rpm=rpm,
            configured_rpm=configured,
            mode=mode,
            solar_temperature=110.0,
            missing=("pool.temperature",),
            evaluator=evaluator,
            driver=driver,
        )
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        assert result.blocker is None, (seconds, result.state, result.blocker)

    probe = driver.probe_execution_evidence()
    assert probe is not None
    assert probe.phase.value == "acquiring"
    assert probe.acquisition_started_at == NOW + timedelta(seconds=64)
    assert [type(operation).__name__ for operation in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
        "SetPumpSpeed",
    ]
    assert [
        operation.rpm for operation in delivery.calls if isinstance(operation, SetPumpSpeed)
    ] == [3000, 1500]

    final = None
    for seconds in (94, 124, 184):
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=True,
            pump_rpm=1500,
            configured_rpm=1500,
            mode=mode,
            solar_temperature=solar_temperature,
            evaluator=evaluator,
            driver=driver,
        )
        final = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    assert evaluator.pool_temperature_probe.started_at == NOW + timedelta(seconds=64)
    assert evaluator.pool_temperature_probe.last_assessment is not None
    assert evaluator.pool_temperature_probe.last_assessment.reason_code == "probe_settled"
    assert final is not None
    assert driver.probe_execution_evidence() is None
    assert len(delivery.calls) == 4
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == successor_rpm

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=185),
                pool_active=True,
                pump_rpm=successor_rpm,
                configured_rpm=successor_rpm,
                mode=mode,
                solar_temperature=solar_temperature,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is successor_source
    completed = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=186),
                pool_active=True,
                pump_rpm=successor_rpm,
                configured_rpm=successor_rpm,
                pool_heater=(
                    "H0002"
                    if successor_source is PhysicalHeatMode.SOLAR
                    else "H0001"
                ),
                mode=mode,
                solar_temperature=solar_temperature,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert completed.state is (
        ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
        if successor_source is PhysicalHeatMode.SOLAR
        else ThermalAutomaticDriverState.CONVERGED
    )
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation is True
    assert lease.owns_pump_setpoint is True
    assert lease.pump_setpoint is not None
    assert lease.pump_setpoint.intended_value == successor_rpm
    assert lease.owns_heat_source is True


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

    assert result.state is ThermalAutomaticDriverState.TERMINATING
    assert len(delivery.calls) == 1
    assert driver.active_session is None
    assert orchestrator.ownership.state.status is not ThermalRuntimeOwnershipStatus.OWNED


def test_owned_gas_source_is_deselected_then_verified_without_stopping_pool() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    epochs = (
        _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
        _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=True),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=3),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=63),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
        _frame(
            orchestrator,
            NOW + timedelta(seconds=64),
            pool_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
            pool_heater="H0001",
        ),
    )
    for item in epochs:
        asyncio.run(driver.process_epoch(item, delivery_factory=factory))

    ending = _frame(
        orchestrator,
        NOW + timedelta(seconds=65),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    requested = asyncio.run(driver.process_epoch(ending, delivery_factory=factory))

    assert requested.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert [type(item).__name__ for item in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
        "SetHeatMode",
        "SetHeatMode",
    ]
    assert delivery.calls[-1].mode.value == "off"
    assert not any(
        getattr(item, "active", True) is False for item in delivery.calls
    )

    confirmed = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    result = asyncio.run(driver.process_epoch(confirmed, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.CONVERGED
    assert len(delivery.calls) == 4
    assert driver.termination_attempt is None
    assert orchestrator.ownership.residual_termination is None
    assert result.runtime_ownership_summary["circulation_successor_kind"] == (
        "filtration"
    )
    assert result.runtime_ownership_summary[
        "filtration_immediate_successor_need"
    ] is True
    assert result.runtime_ownership_summary["body_deactivation_eligible"] is False
    assert result.runtime_ownership_summary["pump_handoff_eligible"] is True
    assert result.runtime_ownership_summary[
        "circulation_command_delivery_enabled"
    ] is False


def test_diagnostic_publication_cannot_invalidate_residual_entitlement() -> None:
    orchestrator, driver, _ = _driver_with_residual_body_entitlement()
    invalid = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=False,
        mode=ThermalRequestedMode.OFF,
    )
    residual = orchestrator.ownership.residual_termination
    assert residual is not None

    first = driver.note_disabled_epoch(invalid)
    second = driver._termination_assessment(invalid)
    third = driver._termination_assessment(invalid)

    assert first.runtime_ownership_summary["termination_disposition"] == "invalidated"
    assert second == third
    assert orchestrator.ownership.residual_termination is residual
    driver._circulation_assessment(invalid)
    driver._circulation_assessment(invalid)
    assert orchestrator.ownership.residual_termination is residual


def test_explicit_invalidated_termination_processing_discards_entitlement() -> None:
    orchestrator, driver, factory = _driver_with_residual_body_entitlement()
    invalid = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=False,
        mode=ThermalRequestedMode.OFF,
    )

    result = asyncio.run(driver.process_epoch(invalid, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert result.blocker == "thermal_termination_pool_topology_lost"
    assert orchestrator.ownership.residual_termination is None
    assert len(factory.delivery.calls) == 1


def test_accepted_termination_delivery_needs_a_later_authoritative_epoch() -> None:
    orchestrator, driver, factory, ending, requested = (
        _driver_awaiting_source_off_verification()
    )
    residual = orchestrator.ownership.residual_termination

    duplicate = asyncio.run(driver.process_epoch(ending, delivery_factory=factory))

    assert duplicate is requested
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is residual
    assert len(factory.delivery.calls) == 4


def test_native_gas_does_not_verify_accepted_source_off_delivery() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    still_gas = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        mode=ThermalRequestedMode.OFF,
    )

    result = asyncio.run(driver.process_epoch(still_gas, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is not None
    assert len(factory.delivery.calls) == 4


def test_native_solar_takeover_cannot_verify_gas_source_off_delivery() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    solar = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0002",
        mode=ThermalRequestedMode.OFF,
    )

    result = asyncio.run(driver.process_epoch(solar, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert result.blocker == "thermal_termination_verification_preempted"
    assert driver.termination_attempt is None
    assert orchestrator.ownership.residual_termination is None
    assert len(factory.delivery.calls) == 4


def test_unusable_native_source_cannot_verify_source_off_delivery() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    missing_source = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        missing=("pool.raw_heater_id",),
    )

    result = asyncio.run(
        driver.process_epoch(missing_source, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is not None
    assert len(factory.delivery.calls) == 4


def test_stale_native_source_cannot_verify_source_off_delivery() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    fresh_off = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
    )
    stale_observations = tuple(
        replace(item, observed_at=NOW)
        if item.observation_id == "pool.raw_heater_id"
        else item
        for item in fresh_off.observations
    )
    stale_off = replace(
        fresh_off,
        observations=stale_observations,
    )

    result = asyncio.run(driver.process_epoch(stale_off, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is not None
    assert len(factory.delivery.calls) == 4


def test_fresh_but_predelivery_native_off_cannot_verify_termination() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    fresh_off = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
    )
    predelivery_observations = tuple(
        replace(item, observed_at=NOW + timedelta(seconds=64))
        if item.observation_id == "pool.raw_heater_id"
        else item
        for item in fresh_off.observations
    )
    predelivery_off = replace(fresh_off, observations=predelivery_observations)

    result = asyncio.run(
        driver.process_epoch(predelivery_off, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert result.runtime_ownership_summary["termination_reason_code"] == (
        "thermal_termination_source_observation_not_post_delivery"
    )
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is not None
    assert len(factory.delivery.calls) == 4


def test_same_timestamp_command_callback_cannot_verify_termination() -> None:
    orchestrator, driver, factory, ending, _ = (
        _driver_awaiting_source_off_verification()
    )
    same_timestamp_off = _frame(
        orchestrator,
        ending.observed_at,
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
    )

    result = asyncio.run(
        driver.process_epoch(same_timestamp_off, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert result.runtime_ownership_summary["termination_reason_code"] == (
        "thermal_termination_source_observation_not_post_delivery"
    )
    assert driver.termination_attempt is not None
    assert orchestrator.ownership.residual_termination is not None
    assert len(factory.delivery.calls) == 4


def test_verified_source_off_then_normalizes_filtration_once_and_later_stops_body(
) -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()

    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    verified = asyncio.run(
        driver.process_epoch(source_verified, delivery_factory=factory)
    )
    assert verified.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is not None
    assert driver.cleanup_provenance.pump_setpoint is not None

    normalize = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    requested = asyncio.run(driver.process_epoch(normalize, delivery_factory=factory))
    assert requested.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(factory.delivery.calls[-1], SetPumpSpeed)
    assert factory.delivery.calls[-1].equipment_id == "p0102"
    assert factory.delivery.calls[-1].rpm == 2600

    normalized = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    complete = asyncio.run(driver.process_epoch(normalized, delivery_factory=factory))
    assert complete.state is ThermalAutomaticDriverState.CLEANUP_WAITING
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is not None
    assert driver.cleanup_provenance.pump_setpoint is None
    command_count = len(factory.delivery.calls)

    still_needed = _frame(
        orchestrator,
        NOW + timedelta(seconds=69),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=1),
    )
    waiting = asyncio.run(driver.process_epoch(still_needed, delivery_factory=factory))
    assert waiting.state is ThermalAutomaticDriverState.CLEANUP_WAITING
    assert len(factory.delivery.calls) == command_count

    satisfied = _frame(
        orchestrator,
        NOW + timedelta(seconds=70),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    body_requested = asyncio.run(
        driver.process_epoch(satisfied, delivery_factory=factory)
    )
    assert body_requested.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(factory.delivery.calls[-1], SetBodyActive)
    assert factory.delivery.calls[-1].equipment_id == ThermalBody.POOL.value
    assert factory.delivery.calls[-1].active is False

    body_off = _frame(
        orchestrator,
        NOW + timedelta(seconds=71),
        pool_active=False,
        pump_rpm=0,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    body_verified = asyncio.run(
        driver.process_epoch(body_off, delivery_factory=factory)
    )
    assert body_verified.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None


def test_body_cleanup_receipt_is_not_verification() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    next_epoch = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )

    requested = asyncio.run(driver.process_epoch(next_epoch, delivery_factory=factory))

    assert requested.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert driver.cleanup_attempt is not None
    assert driver.cleanup_provenance is not None


@pytest.mark.parametrize(
    ("pump_rpm", "configured_rpm"),
    ((2600, 3000), (3000, 2600)),
)
def test_pump_cleanup_requires_later_configured_and_actual_native_truth(
    pump_rpm: int,
    configured_rpm: int,
) -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    normalize = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    asyncio.run(driver.process_epoch(normalize, delivery_factory=factory))
    incomplete = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=pump_rpm,
        configured_rpm=configured_rpm,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )

    result = asyncio.run(driver.process_epoch(incomplete, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert driver.cleanup_attempt is not None
    assert len(factory.delivery.calls) == 5


def test_source_no_longer_off_preempts_cleanup_verification() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    body_request = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(body_request, delivery_factory=factory))
    source_returned = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )

    result = asyncio.run(
        driver.process_epoch(source_returned, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert result.blocker == "thermal_cleanup_source_off_not_current"
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None


def test_new_immediate_filtration_preempts_pending_body_cleanup() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    body_request = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(body_request, delivery_factory=factory))
    calls_before = len(factory.delivery.calls)
    filtration_now = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=1),
    )

    result = asyncio.run(
        driver.process_epoch(filtration_now, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert result.blocker == "thermal_cleanup_circulation_successor_changed"
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert len(factory.delivery.calls) == calls_before


def test_transient_spa_takeover_preempts_pending_cleanup_verification() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()

    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))

    body_request = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    requested = asyncio.run(
        driver.process_epoch(body_request, delivery_factory=factory)
    )

    assert (
        requested.state
        is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    )
    assert driver.cleanup_attempt is not None
    calls_before = len(factory.delivery.calls)

    transient_spa_takeover = ExternalChangeEvent(
        concept="spa.active",
        semantic_event_type="native_value_changed",
        native_object_id="B1202",
        previous_value=False,
        new_value=True,
        observed_at=NOW + timedelta(seconds=67, milliseconds=500),
        external_policy="accept",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=False,
    )

    returned_to_pool_topology = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )

    result = asyncio.run(
        driver.process_epoch(
            replace(
                returned_to_pool_topology,
                external_changes=ExternalChangeBatch(
                    (transient_spa_takeover,)
                ),
            ),
            delivery_factory=factory,
        )
    )

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert result.blocker == "thermal_cleanup_external_takeover"
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert len(factory.delivery.calls) == calls_before


def test_cleanup_takeover_invalidates_provenance_without_command() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    assert driver.cleanup_provenance is not None
    calls_before = len(factory.delivery.calls)
    takeover_frame = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=2),
    )
    takeover = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type="native_value_changed",
        native_object_id="PMP01",
        previous_value=3000,
        new_value=2600,
        observed_at=takeover_frame.observed_at,
        external_policy="accept",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=False,
    )

    result = asyncio.run(
        driver.process_epoch(
            replace(
                takeover_frame,
                external_changes=ExternalChangeBatch((takeover,)),
            ),
            delivery_factory=factory,
        )
    )

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert driver.cleanup_provenance is None
    assert len(factory.delivery.calls) == calls_before


def test_preexisting_body_with_owned_pump_can_normalize_but_never_stop_body() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    residual = orchestrator.ownership.residual_termination
    assert residual is not None and residual.pump_setpoint is not None
    pump_only = replace(residual, body_activation=None, heat_source=None)
    provenance = ThermalCirculationCleanupProvenance.from_residual(
        pump_only,
        established_at=NOW + timedelta(seconds=66),
    )
    assert provenance is not None
    driver.cleanup_provenance = provenance
    driver.termination_attempt = None
    orchestrator.ownership.invalidate_residual_termination()
    calls_before = len(factory.delivery.calls)
    normalize = _frame(
        orchestrator,
        NOW + timedelta(seconds=67),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=1),
    )

    requested = asyncio.run(driver.process_epoch(normalize, delivery_factory=factory))

    assert requested.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(factory.delivery.calls[-1], SetPumpSpeed)
    assert len(factory.delivery.calls) == calls_before + 1

    verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=68),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(hours=1),
    )
    asyncio.run(driver.process_epoch(verified, delivery_factory=factory))
    assert driver.cleanup_provenance is None

    satisfied = _frame(
        orchestrator,
        NOW + timedelta(seconds=69),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )
    result = asyncio.run(driver.process_epoch(satisfied, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert not any(
        isinstance(operation, SetBodyActive) and operation.active is False
        for operation in factory.delivery.calls
    )


def test_restart_with_matching_pool_state_reconstructs_no_cleanup_authority() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    running = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.OFF,
        filtration_remaining=timedelta(0),
    )

    result = asyncio.run(
        driver.process_epoch(running, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert driver.cleanup_provenance is None
    assert delivery.calls == []


def test_unload_discards_cleanup_provenance_without_compensating_command() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="00000",
        mode=ThermalRequestedMode.OFF,
    )
    asyncio.run(driver.process_epoch(source_verified, delivery_factory=factory))
    assert driver.cleanup_provenance is not None
    calls_before = len(factory.delivery.calls)

    driver.unload(unloaded_at=NOW + timedelta(seconds=67))

    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert len(factory.delivery.calls) == calls_before


def test_external_source_takeover_explicitly_invalidates_termination_attempt() -> None:
    orchestrator, driver, factory, _, _ = _driver_awaiting_source_off_verification()
    current = _frame(
        orchestrator,
        NOW + timedelta(seconds=66),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        mode=ThermalRequestedMode.OFF,
    )
    takeover = ExternalChangeEvent(
        concept="pool.raw_heater_id",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value="H0001",
        new_value="H0002",
        observed_at=current.observed_at,
        external_policy="reconcile",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=True,
    )
    current = replace(
        current,
        external_changes=ExternalChangeBatch((takeover,)),
    )

    result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert result.blocker == "thermal_termination_verification_preempted"
    assert driver.termination_attempt is None
    assert orchestrator.ownership.residual_termination is None
    assert len(factory.delivery.calls) == 4


def test_driver_gate_loss_retains_diagnostics_but_performs_no_termination() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    first = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    asyncio.run(driver.process_epoch(first, delivery_factory=factory))

    driver.set_enabled(
        False,
        changed_at=NOW + timedelta(seconds=2),
        current_epoch_identity=first.epoch_identity,
    )
    assert orchestrator.ownership.residual_termination is not None
    later = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
        mode=ThermalRequestedMode.OFF,
    )
    result = asyncio.run(driver.process_epoch(later, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.DISABLED
    assert len(delivery.calls) == 1


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
