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
from poolos.pool_circulation_ownership import (
    PoolCirculationOwner,
    PoolCirculationOwnershipRegistry,
)
from poolos.pump_speed_session import (
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionPurpose,
)
from poolos.thermal_execution_currentness import ThermalExecutionProgress
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
    ThermalLiveExecutionContext,
    ThermalLiveExecutionOwnership,
    ThermalLiveExecutionPolicy,
)
from poolos.thermal_runtime_assessment import (
    ThermalRequestedMode,
    ThermalRuntimeEvaluator,
    ThermalRuntimeEvidence,
)
from poolos.thermal_runtime_orchestration import (
    ThermalOrchestrationLifecycle,
    ThermalRuntimeOrchestrator,
)
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipStatus,
)
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE


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

    def for_operation(self, **kwargs: object) -> FakeDelivery:
        del kwargs
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
    spa_heater: str = "00000",
    configured_rpm: int = 2600,
    grid_outage_active: bool = False,
    solar_active: bool = False,
    solar_temperature: float = 110.0,
    pool_temperature: float = 80.0,
    spa_temperature: float = 98.0,
    spa_target: float = 101.0,
    heater_active: bool = False,
    spa_heating_demand_active: bool = False,
) -> dict[str, object]:
    return {
        "pool.active": pool_active,
        "pool.temperature": pool_temperature,
        "pool.target_temperature": 90.0,
        "pool.raw_heater_id": pool_heater,
        "pool.raw_htmode": "0",
        "spa.active": spa_active,
        "spa.temperature": spa_temperature,
        "spa.target_temperature": spa_target,
        "spa.raw_heater_id": spa_heater,
        "spa.raw_htmode": "0",
        "heater.active": heater_active,
        "spa.heating_demand_active": spa_heating_demand_active,
        "pump.rpm": pump_rpm,
        "pool.pump_circuit.configured_speed_rpm": configured_rpm,
        "spa.pump_circuit.configured_speed_rpm": configured_rpm,
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
    pool_temperature: float = 80.0,
    spa_active: bool | None = None,
    spa_heater: str = "00000",
    spa_temperature: float = 98.0,
    spa_target: float = 101.0,
    heater_active: bool = False,
    spa_heating_demand_active: bool = False,
    native_observation_at: datetime | None = None,
    body: ThermalBody = ThermalBody.POOL,
    filtration_remaining: timedelta | None = None,
    filtration_disposition: FiltrationDisposition | None = None,
    filtration_independent_disposition: FiltrationDisposition | None = None,
    spa_pump_circuit_id: str = "p0198",
    driver: ThermalAutomaticExecutionDriver | None = None,
    external_changes: ExternalChangeBatch = ExternalChangeBatch(()),
    verification_timeout: timedelta = timedelta(seconds=30),
    pump_session_id: str | None = None,
    pump_session_purpose: PumpSpeedSessionPurpose | None = None,
    pump_session_effective_rpm: int | None = None,
    pump_session_override_state: PumpSpeedOverrideState = PumpSpeedOverrideState.NONE,
) -> ThermalAutomaticExecutionFrame:
    evidence_at = at if native_observation_at is None else native_observation_at
    values = _values(
        pool_active=pool_active,
        spa_active=(body is ThermalBody.HOT_TUB if spa_active is None else spa_active),
        pump_rpm=pump_rpm,
        pool_heater=pool_heater,
        configured_rpm=configured_rpm,
        grid_outage_active=grid_outage_active,
        solar_active=solar_active,
        solar_temperature=solar_temperature,
        pool_temperature=pool_temperature,
        spa_heater=spa_heater,
        spa_temperature=spa_temperature,
        spa_target=spa_target,
        heater_active=heater_active,
        spa_heating_demand_active=spa_heating_demand_active,
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
                else evidence_at
            ),
        )
        for concept, value in values.items()
        if concept
        in {
            "pool.active",
            "spa.active",
            "pump.rpm",
            "pool.pump_circuit.configured_speed_rpm",
            "spa.pump_circuit.configured_speed_rpm",
            "pool.raw_heater_id",
            "spa.raw_heater_id",
            "heater.active",
            "spa.heating_demand_active",
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
        verification_timeout=verification_timeout,
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
            native_observed_at={concept: evidence_at for concept in values},
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
            spa_pump_circuit_id=spa_pump_circuit_id,
            filtration_debt=filtration_remaining,
            filtration_immediate_circulation_required=(
                None
                if filtration_disposition is None
                else (
                    filtration_independent_disposition or filtration_disposition
                )
                is FiltrationDisposition.RUN_NOW
            ),
            spa_session_kind=(None if driver is None else driver.spa_session_kind()),
            pool_temperature_probe_execution=probe_execution,
            pool_temperature_probe_continuity=(
                PoolTemperatureProbeContinuityEvidence(evaluated_at=at, valid=True)
                if probe_execution is not None
                and probe_execution.phase
                is PoolTemperatureProbeExecutionPhase.ACQUIRING
                else None
            ),
            pump_session_body=(
                PumpSpeedSessionBody.POOL
                if pump_session_id is not None
                else None
            ),
            pump_session_id=pump_session_id,
            pump_session_purpose=pump_session_purpose,
            pump_session_pump_circuit_id=(
                "p0102" if pump_session_id is not None else None
            ),
            pump_session_effective_rpm=pump_session_effective_rpm,
            pump_session_override_state=pump_session_override_state,
        ),
        live_policy=policy,
    )
    orchestration = orchestrator.refresh(
        generated_at=at,
        observations=observations,
        thermal=thermal,
        external_changes=external_changes,
    )
    return ThermalAutomaticExecutionFrame(
        epoch_identity=orchestration.snapshot_identity,
        observed_at=at,
        observations=observations,
        thermal=thermal,
        orchestration=orchestration,
        live_policy=policy,
        physical_authority_ready=True,
        external_changes=external_changes,
        filtration_successor=(
            None
            if filtration_remaining is None
            else FiltrationSuccessorEvidence(
                evaluated_at=at,
                disposition=(filtration_disposition or (
                    FiltrationDisposition.RUN_NOW
                    if filtration_remaining > timedelta(0)
                    else FiltrationDisposition.SATISFIED
                )),
                independent_disposition=(
                    filtration_independent_disposition
                    or filtration_disposition
                    or (
                        FiltrationDisposition.RUN_NOW
                        if filtration_remaining > timedelta(0)
                        else FiltrationDisposition.SATISFIED
                    )
                ),
                total_remaining_runtime=filtration_remaining,
                currently_earning_credit=(
                    filtration_disposition is FiltrationDisposition.CREDITING
                ),
                immediate_circulation_required=(
                    (
                        filtration_independent_disposition
                        or filtration_disposition
                        or FiltrationDisposition.RUN_NOW
                    )
                    is FiltrationDisposition.RUN_NOW
                    and filtration_remaining > timedelta(0)
                ),
                successor_target_rpm=(
                    2600
                    if filtration_remaining > timedelta(0)
                    and (
                        filtration_independent_disposition
                        or filtration_disposition
                        or FiltrationDisposition.RUN_NOW
                    )
                    is FiltrationDisposition.RUN_NOW
                    else None
                ),
                target_semantics=(
                    FiltrationTargetSemantics.ORDINARY_POLICY_BASELINE
                    if filtration_remaining > timedelta(0)
                    and (
                        filtration_independent_disposition
                        or filtration_disposition
                        or FiltrationDisposition.RUN_NOW
                    )
                    is FiltrationDisposition.RUN_NOW
                    else FiltrationTargetSemantics.NONE
                ),
            )
        ),
    )


def _filtration_frame(
    at: datetime,
    *,
    pool_active: bool,
    pump_rpm: int,
    configured_rpm: int,
    satisfied: bool,
    spa_active: bool = False,
) -> FiltrationAutomaticExecutionFrame:
    tracker = FiltrationAccountingTracker(tou_profile=LADWP_INITIAL_PROFILE)
    accounting = tracker.observe(
        FiltrationObservation(
            observed_at=at,
            pool_active=pool_active,
            spa_active=spa_active,
            pump_rpm=pump_rpm,
            water_temperature_f=90.0,
            circulation_evidence_usable=True,
            temperature_evidence_usable=True,
        ),
        safely_deferrable=False,
    )
    if satisfied:
        accounting = replace(
            accounting,
            required_runtime=accounting.credited_runtime,
            remaining_runtime=timedelta(0),
            total_remaining_runtime=timedelta(0),
            disposition=FiltrationDisposition.SATISFIED,
            independent_disposition=FiltrationDisposition.SATISFIED,
            currently_earning_credit=False,
            reason_code="filtration_obligation_satisfied",
        )
    observations = tuple(
        _observation(concept, value, at)
        for concept, value in (
            ("pool.active", pool_active),
            ("spa.active", spa_active),
            ("pump.rpm", pump_rpm),
            ("pool.pump_circuit.configured_speed_rpm", configured_rpm),
            ("waterfall.active", False),
            ("jets.active", False),
            ("slide.active", False),
        )
    )
    return FiltrationAutomaticExecutionFrame(
        epoch_identity=f"filtration:{at.isoformat()}",
        observed_at=at,
        observations=observations,
        filtration=accounting,
        pool_pump_circuit_id="p0102",
        physical_authority_ready=True,
        physical_authority_blocker=None,
        grid_on=True,
        thermal_candidate_ready=False,
        thermal_owned=False,
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
    for seconds, active, heater in (
        (1.0, False, "00000"),
        (2.0, True, "00000"),
        (3.0, True, "00000"),
        (63.0, True, "00000"),
        (64.0, True, "H0001"),
        (64.5, True, "H0001"),
    ):
        item = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=active,
            pump_rpm=3000 if seconds >= 3 else 0,
            configured_rpm=3000 if seconds >= 3 else 2600,
            pool_heater=heater,
        )
        asyncio.run(driver.process_epoch(item, delivery_factory=factory))
    ending = _frame(
        orchestrator,
        NOW + timedelta(seconds=65),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        heater_active=True,
        mode=ThermalRequestedMode.OFF,
    )
    requested = asyncio.run(driver.process_epoch(ending, delivery_factory=factory))
    assert (
        requested.state
        is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    ), (requested.blocker, requested.runtime_ownership_summary)
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


def test_manual_pool_off_suppression_preempts_inflight_cold_start_without_retry() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    first = _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False)
    asyncio.run(driver.process_epoch(first, delivery_factory=factory))
    commands_before = len(delivery.calls)
    suppressed = replace(
        _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=False),
        pool_automatic_control_suppressed=True,
    )

    result = asyncio.run(driver.process_epoch(suppressed, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert result.blocker == "automatic_thermal_manual_pool_off_preempted"
    assert len(delivery.calls) == commands_before
    assert driver.active_session is None


@pytest.mark.parametrize(
    ("body", "pool_suppressed", "spa_suppressed", "forbidden_blocker"),
    (
        (
            ThermalBody.HOT_TUB,
            True,
            False,
            "automatic_thermal_manual_pool_off_preempted",
        ),
        (
            ThermalBody.POOL,
            False,
            True,
            "automatic_thermal_manual_spa_off_preempted",
        ),
    ),
)
def test_manual_off_suppression_is_scoped_to_its_body(
    body: ThermalBody,
    pool_suppressed: bool,
    spa_suppressed: bool,
    forbidden_blocker: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    baseline = _frame(orchestrator, NOW, pool_active=False, body=body)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    frame = replace(
        _frame(
            orchestrator,
            NOW + timedelta(seconds=1),
            pool_active=False,
            body=body,
        ),
        pool_automatic_control_suppressed=pool_suppressed,
        spa_automatic_control_suppressed=spa_suppressed,
    )

    result = asyncio.run(
        driver.process_epoch(frame, delivery_factory=FakeDeliveryFactory(FakeDelivery()))
    )

    assert result.blocker != forbidden_blocker

def test_warmed_collector_exposes_command_free_probe_candidate_at_native_cadence() -> None:
    """Model the v0.10.6 Pool-off commissioning sequence without delivery."""

    orchestrator = ThermalRuntimeOrchestrator()
    evaluator = ThermalRuntimeEvaluator()
    initial_at = NOW - timedelta(seconds=60)
    initial = _frame(
        orchestrator,
        initial_at,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=82.0,
        evaluator=evaluator,
    )
    evaluated_at = NOW + timedelta(seconds=30, milliseconds=940)
    warmed = _frame(
        orchestrator,
        evaluated_at,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=97.0,
        native_observation_at=NOW,
        evaluator=evaluator,
    )

    assert initial.orchestration.candidate_body is None
    assert warmed.thermal is not None
    assert warmed.thermal.pool.plan.desired.reason_code == "pool_temperature_probe_required"
    assert warmed.thermal.pool.plan.desired.required_pump_rpm == 1500
    assert warmed.orchestration.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert warmed.orchestration.candidate_body is ThermalBody.POOL
    assert not warmed.orchestration.command_delivery_performed


def test_native_cadence_probe_candidate_can_start_bounded_fake_cold_start() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline_at = NOW - timedelta(seconds=60)
    baseline = _frame(
        orchestrator,
        baseline_at,
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=82.0,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=baseline_at,
        current_epoch_identity=baseline.epoch_identity,
    )
    evaluated_at = NOW + timedelta(seconds=30, milliseconds=940)
    warmed = _frame(
        orchestrator,
        evaluated_at,
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=97.0,
        native_observation_at=NOW,
        evaluator=evaluator,
    )

    result = asyncio.run(driver.process_epoch(warmed, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert result.accepted_delivery_count == 1
    assert result.command_delivery_performed
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetBodyActive)
    assert delivery.calls[0].equipment_id == ThermalBody.POOL.value
    assert delivery.calls[0].active is True


@pytest.mark.parametrize(
    "missing_concept",
    ("jets.active", "waterfall.active", "slide.active"),
)
def test_incomplete_shared_hydraulic_inventory_never_reaches_delivery(
    missing_concept: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        missing=(missing_concept,),
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    current = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
        missing=(missing_concept,),
    )

    result = asyncio.run(driver.process_epoch(current, delivery_factory=factory))

    assert result.state is ThermalAutomaticDriverState.BLOCKED
    assert (
        result.blocker
        == "thermal_orchestration_shared_hydraulic_inventory_incomplete"
    )
    assert result.accepted_delivery_count == 0
    assert not result.command_delivery_performed
    assert delivery.calls == []


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
    assert (
        driver.active_pump_session_purpose()
        is PumpSpeedSessionPurpose.PRIMING
    )

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


def test_accepted_body_activation_waits_for_authoritative_consequence() -> None:
    """A newer pre-consequence frame must not self-preempt accepted body ON."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    accepted = asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )
    pending = asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=False),
            delivery_factory=factory,
        )
    )

    assert accepted.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert (
        pending.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
    ), pending.blocker
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert pending.accepted_delivery_count == 1
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetBodyActive)


def test_owned_thermal_session_respects_verified_pump_override_without_delivery() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    original = _frame(
        orchestrator,
        NOW,
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        heater_active=True,
        mode=ThermalRequestedMode.GAS,
    )
    body = original.thermal.pool
    currentness = body.execution_currentness
    established = orchestrator.ownership.establish(
        ThermalLiveExecutionOwnership(
            evaluation_id=body.evaluation_id,
            thermal_plan_id=body.plan.plan_id,
            execution_plan_id="owned-gas-session",
            target_body=ThermalBody.POOL,
            body_activation_operation_id="body-operation",
            body_activation_receipt_id="body-receipt",
            body_activation_correlation_id="body-correlation",
            pump_operation_id="pump-operation",
            pump_receipt_id="pump-receipt",
            pump_correlation_id="pump-correlation",
            commanded_pump_rpm=3000,
            heat_source_operation_id="source-operation",
            heat_source_receipt_id="source-receipt",
            heat_source_correlation_id="source-correlation",
            commanded_heat_source=PhysicalHeatMode.GAS,
        ),
        established_at=NOW,
        requested_mode="Gas",
        current_context=ThermalLiveExecutionContext(
            body.evaluation_id,
            body.plan.plan_id,
            currentness,
        ),
        execution_progress=ThermalExecutionProgress(),
    )
    assert established.current_state.status is ThermalRuntimeOwnershipStatus.OWNED
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=original.epoch_identity,
    )

    overridden = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=3200,
        configured_rpm=3200,
        pool_heater="H0001",
        heater_active=True,
        mode=ThermalRequestedMode.GAS,
        pump_session_id="pool-gas-session",
        pump_session_purpose=PumpSpeedSessionPurpose.GAS,
        pump_session_effective_rpm=3200,
        pump_session_override_state=PumpSpeedOverrideState.VERIFIED,
    )
    result = asyncio.run(driver.process_epoch(overridden, delivery_factory=factory))

    lease = orchestrator.ownership.state.lease
    assert result.state is ThermalAutomaticDriverState.CONVERGED, result.blocker
    assert result.command_delivery_performed is False
    assert delivery.calls == []
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.heat_source is not None
    assert lease.pump_setpoint is None

    returned = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        pump_rpm=3000,
        configured_rpm=3000,
        pool_heater="H0001",
        heater_active=True,
        mode=ThermalRequestedMode.GAS,
        pump_session_id="pool-gas-session",
        pump_session_purpose=PumpSpeedSessionPurpose.GAS,
        pump_session_effective_rpm=3000,
        pump_session_override_state=PumpSpeedOverrideState.NONE,
    )
    result = asyncio.run(driver.process_epoch(returned, delivery_factory=factory))
    lease = orchestrator.ownership.state.lease
    assert result.state is ThermalAutomaticDriverState.CONVERGED, result.blocker
    assert result.command_delivery_performed is False
    assert delivery.calls == []
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.heat_source is not None
    assert lease.pump_setpoint is None


@pytest.mark.parametrize(
    ("first_actual_rpm", "first_configured_rpm"),
    ((2816, 3000), (3000, 2600)),
)
def test_accepted_pump_step_allows_bounded_controller_settling(
    first_actual_rpm: int,
    first_configured_rpm: int,
) -> None:
    """Old configured speed and transient actual RPM remain verifier-owned."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    for seconds, active in ((1, False), (2, True)):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=active,
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 3000

    pending = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=True,
                pump_rpm=first_actual_rpm,
                configured_rpm=first_configured_rpm,
            ),
            delivery_factory=factory,
        )
    )

    assert (
        pending.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
    ), pending.blocker
    converged = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=4),
                pool_active=True,
                pump_rpm=3000,
                configured_rpm=3000,
            ),
            delivery_factory=factory,
        )
    )
    duplicate = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=4),
                pool_active=True,
                pump_rpm=3000,
                configured_rpm=3000,
            ),
            delivery_factory=factory,
        )
    )

    assert converged.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
    assert duplicate == converged
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
    assert pending.accepted_delivery_count == 2
    assert len(delivery.calls) == 2
    assert pending.runtime_ownership_summary["verified_owned_concepts"] == [
        "body_activation"
    ]
    assert (
        pending.runtime_ownership_summary["accepted_consequence_pending_role"]
        == "priming"
    )


def test_quiescent_solar_cold_start_verifies_h0002_before_engagement() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()

    # Establish bounded trusted-water reuse before the Pool becomes quiescent.
    trusted = _frame(
        ThermalRuntimeOrchestrator(),
        NOW - timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
    )
    assert trusted.thermal is not None
    assert trusted.thermal.pool.plan.desired.selected_source is PhysicalHeatMode.SOLAR
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
        (65, True, 2900, 2900, "00000"),
        (66, True, 2900, 2900, "H0002"),
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
                    verification_timeout=timedelta(seconds=120),
                ),
                delivery_factory=factory,
            )
        )

    assert result is not None
    assert (
        result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    ), (result.blocker, result.runtime_ownership_summary)
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
                NOW + timedelta(seconds=67),
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
                NOW + timedelta(seconds=68),
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


def test_poolos_started_solar_session_terminates_body_without_restart() -> None:
    """Prove the complete live no-successor cleanup path from accepted origin."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=90.0,
        evaluator=evaluator,
        driver=driver,
    )
    assert baseline.thermal is not None
    assert baseline.thermal.pool.plan.desired.reason_code == (
        "pool_temperature_probe_required"
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    for seconds, active, rpm, configured, heater, temperature_missing in (
        (1.0, False, 0, 1500, "00000", True),
        (2.0, True, 0, 1500, "00000", True),
        (3.0, True, 1500, 1500, "00000", True),
        (34.0, True, 1500, 1500, "00000", False),
        (64.0, True, 1500, 1500, "00000", False),
        (124.0, True, 1500, 1500, "00000", False),
        (125.0, True, 2900, 2900, "00000", False),
        (126.0, True, 2900, 2900, "00000", False),
        (127.0, True, 2900, 2900, "H0002", False),
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
                    mode=ThermalRequestedMode.SOLAR,
                    missing=("pool.temperature",) if temperature_missing else (),
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT
    for seconds in (128, 158):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="H0002",
                    solar_active=True,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result.blocker == "automatic_thermal_solar_engaged"

    for seconds in (279, 879):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="H0002",
                    pool_temperature=90.0,
                    solar_active=True,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    filtration_remaining=timedelta(hours=2),
                    filtration_disposition=FiltrationDisposition.CREDITING,
                    filtration_independent_disposition=(
                        FiltrationDisposition.DEFERRED_OPTIMIZATION
                    ),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.OFF

    source_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=880),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert source_off.state is ThermalAutomaticDriverState.CONVERGED
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is not None

    cleanup_frame = _frame(
                orchestrator,
                NOW + timedelta(seconds=881),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            )
    assert cleanup_frame.filtration_successor is not None
    assert cleanup_frame.filtration_successor.total_remaining_runtime > timedelta(0)
    assert cleanup_frame.filtration_successor.currently_earning_credit
    assert cleanup_frame.filtration_successor.independent_disposition is (
        FiltrationDisposition.DEFERRED_OPTIMIZATION
    )
    assert cleanup_frame.filtration_successor.immediate_circulation_required is False
    assert cleanup_frame.filtration_successor.successor_target_rpm is None
    assert cleanup_frame.filtration_successor.target_semantics is (
        FiltrationTargetSemantics.NONE
    )
    requested_off = asyncio.run(
        driver.process_epoch(
            cleanup_frame,
            delivery_factory=factory,
        )
    )
    assert requested_off.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].equipment_id == ThermalBody.POOL.value
    assert delivery.calls[-1].active is False
    cleanup_attempt = driver.cleanup_attempt
    assert cleanup_attempt is not None
    cleanup_provenance = driver.cleanup_provenance
    assert cleanup_provenance is not None
    assert cleanup_attempt.candidate.operation == delivery.calls[-1]
    assert cleanup_attempt.candidate.provenance_id == cleanup_provenance.provenance_id
    assert cleanup_attempt.receipt_id == cleanup_attempt.correlation_id
    assert requested_off.last_accepted_correlation_id == (
        cleanup_attempt.correlation_id
    )

    pending_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=882),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert pending_off.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert sum(
        isinstance(operation, SetBodyActive) and not operation.active
        for operation in delivery.calls
    ) == 1

    verified_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=883),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert verified_off.state is ThermalAutomaticDriverState.CONVERGED
    assert verified_off.blocker == "thermal_cleanup_pool_body_off_verified"
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE
    assert sum(
        isinstance(operation, SetBodyActive) and not operation.active
        for operation in delivery.calls
    ) == 1
    assert not any(
        isinstance(operation, SetPumpSpeed) and operation.rpm == 2600
        for operation in delivery.calls
    )


def test_identical_external_pool_state_never_gains_body_cleanup_authority() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    for seconds in (1, 601):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="00000",
                    pool_temperature=90.0,
                    solar_active=False,
                    mode=ThermalRequestedMode.SOLAR,
                    filtration_remaining=timedelta(hours=2),
                    filtration_disposition=FiltrationDisposition.CREDITING,
                    filtration_independent_disposition=(
                        FiltrationDisposition.DEFERRED_OPTIMIZATION
                    ),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    assert result.blocker == "thermal_orchestration_no_authorized_candidate"
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    assert not any(
        isinstance(operation, SetBodyActive) and not operation.active
        for operation in delivery.calls
    )


def test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
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
    for seconds, active, rpm, configured, heater, temperature_missing in (
        (1.0, False, 0, 1500, "00000", True),
        (2.0, True, 0, 1500, "00000", True),
        (3.0, True, 1500, 1500, "00000", True),
        (34.0, True, 1500, 1500, "00000", False),
        (64.0, True, 1500, 1500, "00000", False),
        (124.0, True, 1500, 1500, "00000", False),
        (125.0, True, 2900, 2900, "00000", False),
        (126.0, True, 2900, 2900, "00000", False),
        (127.0, True, 2900, 2900, "H0002", False),
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
                    missing=("pool.temperature",) if temperature_missing else (),
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    unknown = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=128),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=427),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                omit_solar_observation=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=428),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=429),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=430),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=431),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                solar_temperature=91.0,
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
                NOW + timedelta(seconds=432),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
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
    assert (
        driver.active_pump_session_purpose()
        is PumpSpeedSessionPurpose.TEMPERATURE_PROBE
    )
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
        (2, True, 2600, 2600),
        (3, True, 1500, 1500),
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
    assert probe.acquisition_started_at == NOW + timedelta(seconds=3)
    assert [type(operation).__name__ for operation in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
    ]
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 1500

    final = None
    for seconds in (33, 63, 123):
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

    assert evaluator.pool_temperature_probe.started_at == NOW + timedelta(seconds=3)
    assert evaluator.pool_temperature_probe.last_assessment is not None
    assert evaluator.pool_temperature_probe.last_assessment.reason_code == "probe_settled"
    assert final is not None
    assert driver.probe_execution_evidence() is None
    assert len(delivery.calls) == 3
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == successor_rpm

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=124),
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
                NOW + timedelta(seconds=125),
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


def test_normal_day_pool_and_spa_complete_lifecycle() -> None:
    """Exercise Pool acquisition/Solar/filtration and external Spa Gas."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    filtration_driver = FiltrationAutomaticExecutionDriver(
        driver.circulation_ownership
    )
    filtration_driver.set_enabled(
        True,
        changed_at=NOW - timedelta(seconds=1),
        current_epoch_identity=None,
    )
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=1500,
        pool_heater="H0002",
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=89.0,
        evaluator=evaluator,
        driver=driver,
    )
    assert baseline.orchestration.candidate_body is None
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    probe_epochs = (
        (1, False, 0, 1500, "H0002"),
        (2, False, 0, 1500, "00000"),
        (3, True, 2600, 2600, "00000"),
        (4, True, 1500, 1500, "00000"),
    )
    result = None
    for seconds, active, rpm, configured, heater in probe_epochs:
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
                    missing=("pool.temperature",),
                    solar_temperature=90.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result is not None
    assert driver.probe_execution_evidence() is not None
    assert [type(operation).__name__ for operation in delivery.calls] == [
        "SetHeatMode",
        "SetBodyActive",
        "SetPumpSpeed",
    ]
    assert isinstance(delivery.calls[0], SetHeatMode)
    assert delivery.calls[0].mode is PhysicalHeatMode.OFF
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 1500

    for seconds in (34, 64, 124):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=1500,
                    configured_rpm=1500,
                    pool_heater="00000",
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result is not None
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2900

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=125),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    for seconds in (126, 127, 157):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="H0002",
                    solar_active=seconds >= 127,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    assert result is not None
    assert result.state is ThermalAutomaticDriverState.CONVERGED
    assert result.blocker == "automatic_thermal_solar_engaged"
    assert [type(operation).__name__ for operation in delivery.calls] == [
        "SetHeatMode",
        "SetBodyActive",
        "SetPumpSpeed",
        "SetPumpSpeed",
        "SetHeatMode",
    ]
    assert [
        operation.rpm
        for operation in delivery.calls
        if isinstance(operation, SetPumpSpeed)
    ] == [1500, 2900]
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert lease.owns_pump_setpoint
    assert lease.owns_heat_source

    calls_before_termination = len(delivery.calls)
    holding_target = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=219),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                pool_temperature=90.0,
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert holding_target.blocker == "automatic_thermal_owned_successor_requires_explicit_handoff"
    assert len(delivery.calls) == calls_before_termination

    terminating = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=819),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                pool_temperature=90.0,
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert terminating.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.OFF

    awaiting_native_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=820),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                pool_temperature=90.0,
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert awaiting_native_off.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert len(delivery.calls) == calls_before_termination + 1

    source_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=821),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert source_off.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is not None

    cleanup = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=822),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert cleanup.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    handoff_complete = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=823),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="00000",
                pool_temperature=90.0,
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert handoff_complete.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert driver.circulation_ownership.owner is PoolCirculationOwner.FILTRATION

    owned_filtration = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=824),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                satisfied=False,
            ),
            delivery_factory=factory,
        )
    )
    assert owned_filtration.state is FiltrationAutomaticDriverState.OWNED

    yielded = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=900),
                pool_active=False,
                spa_active=True,
                pump_rpm=2500,
                configured_rpm=2600,
                satisfied=False,
            ),
            delivery_factory=factory,
        )
    )
    assert yielded.blocker == "automatic_filtration_yielded_to_spa"
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE

    _assert_external_hot_tub_gas_lifecycle(
        orchestrator=orchestrator,
        driver=driver,
        evaluator=evaluator,
        start_at=NOW + timedelta(seconds=900),
    )

    pool_restart = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=911),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2600,
                satisfied=False,
            ),
            delivery_factory=factory,
        )
    )
    assert pool_restart.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is True

    pump_restart = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=912),
                pool_active=True,
                pump_rpm=3000,
                configured_rpm=2600,
                satisfied=False,
            ),
            delivery_factory=factory,
        )
    )
    assert pump_restart.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    resumed = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=913),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                satisfied=False,
            ),
            delivery_factory=factory,
        )
    )
    assert resumed.state is FiltrationAutomaticDriverState.OWNED

    filtration_complete = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=914),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert filtration_complete.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is False

    complete = asyncio.run(
        filtration_driver.process_epoch(
            _filtration_frame(
                NOW + timedelta(seconds=915),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2600,
                satisfied=True,
            ),
            delivery_factory=factory,
        )
    )
    assert complete.state is FiltrationAutomaticDriverState.BLOCKED
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE
    assert orchestrator.ownership.residual_termination is None
    assert [
        item.rpm for item in delivery.calls if isinstance(item, SetPumpSpeed)
    ] == [1500, 2900, 2600, 2600]


@pytest.mark.parametrize(
    ("pool_temperature", "post_probe_collector"),
    (
        (86.0, 92.0),
        (84.0, 87.0),
        (90.0, 110.0),
    ),
)
def test_negative_probe_outcomes_handoff_to_safe_filtration_without_solar(
    pool_temperature: float,
    post_probe_collector: float,
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
        pump_rpm=0,
        configured_rpm=1500,
        pool_heater="H0002",
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=89.0,
        filtration_remaining=timedelta(hours=2),
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    for seconds, active, rpm, configured, heater in (
        (1, False, 0, 1500, "H0002"),
        (2, False, 0, 1500, "00000"),
        (3, True, 2600, 2600, "00000"),
        (4, True, 1500, 1500, "00000"),
    ):
        asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    pool_heater=heater,
                    mode=ThermalRequestedMode.SOLAR,
                    missing=("pool.temperature",),
                    solar_temperature=92.0,
                    filtration_remaining=timedelta(hours=2),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    for seconds in (34, 64, 124):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=1500,
                    configured_rpm=1500,
                    pool_heater="00000",
                    pool_temperature=pool_temperature,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=post_probe_collector,
                    filtration_remaining=timedelta(hours=2),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
    assert result.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.probe_execution_evidence() is None
    assert driver.cleanup_provenance is not None

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=125),
                pool_active=True,
                pump_rpm=1500,
                configured_rpm=1500,
                pool_heater="00000",
                pool_temperature=pool_temperature,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=post_probe_collector,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600
    assert not any(
        isinstance(item, SetHeatMode) and item.mode is PhysicalHeatMode.SOLAR
        for item in delivery.calls
    )

    verified = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=126),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="00000",
                pool_temperature=pool_temperature,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=post_probe_collector,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert verified.blocker == "thermal_cleanup_filtration_handoff_verified"
    assert driver.cleanup_provenance is None
    assert driver.circulation_ownership.owner is PoolCirculationOwner.FILTRATION
    calls_after_handoff = len(delivery.calls)

    no_repeat = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=127),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="00000",
                pool_temperature=pool_temperature,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=post_probe_collector,
                filtration_remaining=timedelta(hours=2),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert not no_repeat.command_delivery_performed
    assert driver.probe_execution_evidence() is None
    assert len(delivery.calls) == calls_after_handoff
    assert [
        item.rpm for item in delivery.calls if isinstance(item, SetPumpSpeed)
    ][-1] == 2600


def test_external_pool_no_heat_does_not_adopt_deferrable_filtration() -> None:
    pool_orchestrator = ThermalRuntimeOrchestrator()
    pool_driver = ThermalAutomaticExecutionDriver(pool_orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        pool_orchestrator,
        NOW,
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=80.0,
        evaluator=evaluator,
        driver=pool_driver,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
    )
    pool_driver.note_disabled_epoch(baseline)
    pool_driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    pool = _frame(
        pool_orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=80.0,
        evaluator=evaluator,
        driver=pool_driver,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
    )
    delivery = FakeDelivery()
    result = asyncio.run(
        pool_driver.process_epoch(pool, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert not result.command_delivery_performed
    assert delivery.calls == []
    assert pool_driver.active_session is None
    assert pool_orchestrator.ownership.state.lease is None


def test_external_pool_no_heat_serves_canonical_run_now_filtration() -> None:
    """Urgent filtration remains a valid 2600-RPM current successor."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=80.0,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.RUN_NOW,
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    current = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=80.0,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.RUN_NOW,
        evaluator=evaluator,
        driver=driver,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(current, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.command_delivery_performed
    assert len(delivery.calls) == 1
    operation = delivery.calls[0]
    assert isinstance(operation, SetPumpSpeed)
    assert operation.rpm == 2600
    assert driver.active_session is not None
    assert driver.active_session.ownership.body_activation_operation_id is None


def test_external_hot_tub_without_proven_circulation_fails_closed() -> None:

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

    assert (
        blocked.blocker
        == "automatic_thermal_external_hot_tub_circulation_not_established"
    )
    assert hot_tub_delivery.calls == []


def _assert_external_hot_tub_gas_lifecycle(
    *,
    orchestrator: ThermalRuntimeOrchestrator | None = None,
    driver: ThermalAutomaticExecutionDriver | None = None,
    evaluator: ThermalRuntimeEvaluator | None = None,
    start_at: datetime = NOW,
) -> None:
    standalone = orchestrator is None
    orchestrator = orchestrator or ThermalRuntimeOrchestrator()
    driver = driver or ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = evaluator or ThermalRuntimeEvaluator()
    if standalone:
        baseline = _frame(
            orchestrator,
            start_at,
            pool_active=False,
            body=ThermalBody.HOT_TUB,
            spa_active=False,
            pump_rpm=0,
            configured_rpm=2900,
            driver=driver,
            evaluator=evaluator,
        )
        driver.note_disabled_epoch(baseline)
        driver.set_enabled(
            True,
            changed_at=start_at,
            current_epoch_identity=baseline.epoch_identity,
        )
    frame = _frame(
        orchestrator,
        start_at + timedelta(seconds=1),
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        pump_rpm=2500,
        configured_rpm=2500,
        spa_temperature=80.0,
        spa_target=97.0,
        driver=driver,
        evaluator=evaluator,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(frame, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.command_delivery_performed
    assert len(delivery.calls) == 1
    operation = delivery.calls[0]
    assert isinstance(operation, SetPumpSpeed)
    assert operation.equipment_id == "p0198"
    assert operation.rpm == 2600
    assert driver.active_session is not None, (
        result,
        orchestrator.ownership.state,
        orchestrator.ownership.residual_termination,
    )
    assert driver.active_session.ownership.body_activation_operation_id is None

    normalized = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=2),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=2600,
                configured_rpm=2600,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert normalized.state is ThermalAutomaticDriverState.TERMINATING

    relinquished = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=3),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=2600,
                configured_rpm=2600,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert relinquished.state is ThermalAutomaticDriverState.CONVERGED

    preparing = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=4),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=2600,
                configured_rpm=2600,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert preparing.command_delivery_performed
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 3000
    assert driver.active_session is not None
    assert driver.active_session.ownership.body_activation_operation_id is None

    gas_selected = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=5),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert gas_selected.command_delivery_performed
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.GAS

    gas_active = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=6),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert gas_active.state is ThermalAutomaticDriverState.CONVERGED

    target_transition = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=7),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_heater="H0001",
                spa_temperature=97.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert not target_transition.command_delivery_performed

    downshift = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=8),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_heater="H0001",
                spa_temperature=97.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert downshift.command_delivery_performed
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    settled = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=9),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=2600,
                configured_rpm=2600,
                spa_heater="H0001",
                spa_temperature=97.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert settled.state is ThermalAutomaticDriverState.CONVERGED
    assert all(not isinstance(item, SetBodyActive) for item in delivery.calls)

    calls_before_user_off = len(delivery.calls)
    user_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                start_at + timedelta(seconds=10),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=False,
                pump_rpm=0,
                configured_rpm=2600,
                spa_heater="H0001",
                spa_temperature=97.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert not user_off.command_delivery_performed
    assert len(delivery.calls) == calls_before_user_off
    assert all(not isinstance(item, SetBodyActive) for item in delivery.calls)


def test_external_hot_tub_session_governs_dynamic_spa_pump_without_body_ownership() -> None:
    _assert_external_hot_tub_gas_lifecycle()


def test_external_hot_tub_already_gas_active_reconciles_directly_to_3000() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        spa_active=False,
        pump_rpm=0,
        configured_rpm=2900,
        driver=driver,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                pump_rpm=2900,
                configured_rpm=2900,
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert result.command_delivery_performed
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetPumpSpeed)
    assert delivery.calls[0].rpm == 3000
    assert driver.active_session is not None
    assert driver.active_session.ownership.body_activation_operation_id is None


def test_live_external_spa_gas_uses_exact_dynamic_pump_without_body_ownership() -> None:
    """Reproduce the commissioned external Spa Gas frame at the core lifecycle."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        spa_active=False,
        pump_rpm=0,
        configured_rpm=2600,
        spa_pump_circuit_id="p0102",
        driver=driver,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=True,
                pump_rpm=2816,
                configured_rpm=2816,
                spa_pump_circuit_id="p0102",
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert result.command_delivery_performed
    assert len(delivery.calls) == 1
    operation = delivery.calls[0]
    assert isinstance(operation, SetPumpSpeed)
    assert operation.equipment_id == "p0102"
    assert operation.rpm == 3000
    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert driver.active_session is not None
    assert driver.active_session.ownership.body_activation_operation_id is None
    accepted_lease = orchestrator.ownership.state.lease
    assert accepted_lease is not None
    assert accepted_lease.body_activation is None
    assert accepted_lease.pump_setpoint is not None

    verified = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=True,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_pump_circuit_id="p0102",
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert verified.state is ThermalAutomaticDriverState.TERMINATING
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.body_activation is None
    assert lease.pump_setpoint is not None
    assert driver.active_session is None


def test_external_spa_already_at_gas_rpm_creates_no_operation_or_ownership() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        spa_active=False,
        pump_rpm=0,
        configured_rpm=2600,
        spa_pump_circuit_id="p0102",
        driver=driver,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=True,
                pump_rpm=3000,
                configured_rpm=3000,
                spa_pump_circuit_id="p0102",
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert not result.command_delivery_performed
    assert delivery.calls == []
    assert driver.active_session is None
    assert orchestrator.ownership.state.lease is None


def test_external_spa_off_preempts_accepted_pump_work_without_retry() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        spa_active=False,
        pump_rpm=0,
        configured_rpm=2600,
        spa_pump_circuit_id="p0102",
        driver=driver,
        evaluator=evaluator,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    delivery = FakeDelivery()
    accepted = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=True,
                pump_rpm=2816,
                configured_rpm=2816,
                spa_pump_circuit_id="p0102",
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
                spa_temperature=80.0,
                spa_target=97.0,
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert accepted.command_delivery_performed
    assert len(delivery.calls) == 1

    stopped = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=False,
        body=ThermalBody.HOT_TUB,
        spa_active=False,
        pump_rpm=0,
        configured_rpm=3000,
        spa_pump_circuit_id="p0102",
        driver=driver,
        evaluator=evaluator,
    )
    preempted = asyncio.run(
        driver.process_epoch(
            stopped,
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    repeated = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=False,
                body=ThermalBody.HOT_TUB,
                spa_active=False,
                pump_rpm=0,
                configured_rpm=3000,
                spa_pump_circuit_id="p0102",
                driver=driver,
                evaluator=evaluator,
            ),
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )

    assert preempted.state is ThermalAutomaticDriverState.SUPERSEDED
    assert not repeated.command_delivery_performed
    assert len(delivery.calls) == 1
    assert all(not isinstance(item, SetBodyActive) for item in delivery.calls)
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.SUPERSEDED
    )
    assert orchestrator.ownership.state.lease is not None
    assert orchestrator.ownership.state.lease.body_activation is None


@pytest.mark.parametrize(
    ("mode", "expected_rpm", "expected_heater"),
    (
        (ThermalRequestedMode.SOLAR, 2900, "H0002"),
        (ThermalRequestedMode.GAS, 3000, "H0001"),
    ),
)
def test_verified_filtration_owner_hands_pool_body_to_thermal_without_state_adoption(
    mode: ThermalRequestedMode,
    expected_rpm: int,
    expected_heater: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    circulation = PoolCirculationOwnershipRegistry()
    driver = ThermalAutomaticExecutionDriver(
        orchestrator,
        circulation_ownership=circulation,
    )
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)
    circulation.begin_epoch("filtration-epoch")
    circulation.record_filtration_delivery(
        session_id="filtration-session",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW,
        provenance=ThermalRuntimeConceptProvenance(
            concept=ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
            operation_id="filtration-body-operation",
            receipt_id="filtration-body-receipt",
            correlation_id="filtration-body-correlation",
            intended_value=True,
        ),
    )
    circulation.record_filtration_delivery(
        session_id="filtration-session",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW,
        provenance=ThermalRuntimeConceptProvenance(
            concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
            operation_id="filtration-pump-operation",
            receipt_id="filtration-pump-receipt",
            correlation_id="filtration-pump-correlation",
            intended_value=2600,
        ),
    )
    circulation.confirm_filtration_body(
        session_id="filtration-session",
        confirmed_at=NOW,
    )
    circulation.confirm_filtration(
        session_id="filtration-session",
        confirmed_at=NOW,
    )
    frame = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        mode=mode,
    )
    circulation.begin_epoch(frame.epoch_identity)
    driver.reserve_circulation_candidate(frame)
    delivery = FakeDelivery()

    result = asyncio.run(
        driver.process_epoch(frame, delivery_factory=FakeDeliveryFactory(delivery))
    )

    assert result.blocker is None
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == expected_rpm
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.body_activation is not None
    assert lease.body_activation.receipt_id == "filtration-body-receipt"
    assert lease.pump_setpoint is not None
    assert lease.pump_setpoint.receipt_id != "filtration-pump-receipt"
    assert circulation.filtration_lease is None

    pump_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        pump_rpm=expected_rpm,
        configured_rpm=expected_rpm,
        mode=mode,
    )
    asyncio.run(
        driver.process_epoch(
            pump_verified,
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    assert isinstance(delivery.calls[-1], SetHeatMode)

    source_verified = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
        pump_rpm=expected_rpm,
        configured_rpm=expected_rpm,
        pool_heater=expected_heater,
        mode=mode,
    )
    asyncio.run(
        driver.process_epoch(
            source_verified,
            delivery_factory=FakeDeliveryFactory(delivery),
        )
    )
    thermal_lease = orchestrator.ownership.state.lease
    assert thermal_lease is not None
    assert thermal_lease.owns_body_activation
    assert thermal_lease.owns_pump_setpoint
    assert thermal_lease.owns_heat_source


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


def test_outage_preemption_relinquishes_shared_thermal_command_ownership() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    circulation = PoolCirculationOwnershipRegistry()
    driver = ThermalAutomaticExecutionDriver(
        orchestrator,
        circulation_ownership=circulation,
    )
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )
    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )
    assert circulation.owner is PoolCirculationOwner.THERMAL

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=True,
                grid_outage_active=True,
            ),
            delivery_factory=factory,
        )
    )
    assert result.state is ThermalAutomaticDriverState.PREEMPTED
    assert circulation.owner is PoolCirculationOwner.NONE


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
    assert orchestrator.ownership.residual_termination is not None


def test_accepted_unverified_body_activation_creates_no_cleanup_proof() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=False,
                mode=ThermalRequestedMode.OFF,
            ),
            delivery_factory=factory,
        )
    )

    assert result.state is ThermalAutomaticDriverState.SUPERSEDED
    assert orchestrator.ownership.residual_termination is None
    assert len(delivery.calls) == 1


def test_verified_body_origin_survives_pump_takeover_as_cleanup_only_proof() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=True),
            delivery_factory=factory,
        )
    )
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    takeover = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type="native_value_changed",
        native_object_id="PMP01",
        previous_value=0,
        new_value=2600,
        observed_at=NOW + timedelta(seconds=3),
        external_policy="accept",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=True,
    )
    frame = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        external_changes=ExternalChangeBatch((takeover,)),
    )

    result = asyncio.run(
        driver.process_epoch(frame, delivery_factory=factory)
    )

    assert result.state is ThermalAutomaticDriverState.TERMINATING
    entitlement = orchestrator.ownership.residual_termination
    assert entitlement is not None
    assert entitlement.body_activation is not None
    assert entitlement.pump_setpoint is None
    assert entitlement.heat_source is None
    assert result.runtime_ownership_summary["terminal_transition_prior_status"] == (
        "owned"
    )
    assert result.runtime_ownership_summary["terminal_transition_current_status"] == (
        "preempted"
    )
    assert result.runtime_ownership_summary["terminal_transition_affected_concept"] == (
        "pump_setpoint"
    )
    assert result.runtime_ownership_summary["terminal_transition_expected_value"] == (
        3000
    )
    assert result.runtime_ownership_summary["terminal_transition_observed_value"] == (
        2600
    )
    assert result.runtime_ownership_summary["terminal_transition_operation_id"] == (
        delivery.calls[-1].operation_id
    )
    assert result.runtime_ownership_summary[
        "terminal_transition_external_event_id"
    ] == takeover.event_id
    assert result.runtime_ownership_summary[
        "terminal_transition_accepted_at"
    ] == (NOW + timedelta(seconds=2)).isoformat()
    assert result.runtime_ownership_summary[
        "terminal_transition_observed_at"
    ] == (NOW + timedelta(seconds=3)).isoformat()
    assert result.runtime_ownership_summary[
        "terminal_transition_execution_purpose_id"
    ] is not None
    assert result.runtime_ownership_summary[
        "terminal_transition_currentness_disposition"
    ] is not None
    assert result.runtime_ownership_summary[
        "terminal_transition_external_event_concept"
    ] == "pump.rpm"


def test_manual_pool_off_consumes_origin_and_later_external_on_is_never_adopted() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        driver.process_epoch(
            _frame(orchestrator, NOW + timedelta(seconds=2), pool_active=True),
            delivery_factory=factory,
        )
    )
    assert ThermalRuntimeOwnedConcept.BODY_ACTIVATION in (
        orchestrator.ownership.state.lease.verified_concepts  # type: ignore[union-attr]
    )

    manually_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=3000,
            ),
            delivery_factory=factory,
        )
    )
    call_count = len(delivery.calls)
    externally_on = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=4),
                pool_active=True,
                pump_rpm=3000,
                configured_rpm=3000,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
            ),
            delivery_factory=factory,
        )
    )

    assert manually_off.state is ThermalAutomaticDriverState.PREEMPTED
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.PREEMPTED
    )
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    assert not externally_on.command_delivery_performed
    assert len(delivery.calls) == call_count
    assert not any(
        isinstance(operation, SetBodyActive) and not operation.active
        for operation in delivery.calls
    )


def test_owned_gas_source_is_deselected_then_verified_without_stopping_pool() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)

    for seconds, active, heater in (
        (1.0, False, "00000"),
        (2.0, True, "00000"),
        (3.0, True, "00000"),
        (63.0, True, "00000"),
        (64.0, True, "H0001"),
        (64.5, True, "H0001"),
    ):
        item = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=active,
            pump_rpm=3000 if seconds >= 3 else 0,
            configured_rpm=3000 if seconds >= 3 else 2600,
            pool_heater=heater,
        )
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
    assert complete.state is ThermalAutomaticDriverState.CONVERGED
    assert complete.blocker == "thermal_cleanup_filtration_handoff_verified"
    assert driver.cleanup_provenance is None
    assert driver.circulation_ownership.filtration_lease is not None
    assert driver.circulation_ownership.filtration_lease.verified
    assert driver.circulation_ownership.filtration_lease.body_activation is not None
    assert driver.circulation_ownership.filtration_lease.pump_setpoint is not None
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
    assert waiting.state is ThermalAutomaticDriverState.BLOCKED
    assert len(factory.delivery.calls) == command_count


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
    assert driver.cleanup_provenance is not None
    driver.circulation_ownership.mark_thermal_owned(
        driver.cleanup_provenance.lease_id,
    )
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
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE


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
    assert driver.cleanup_provenance is not None
    driver.circulation_ownership.mark_thermal_owned(
        driver.cleanup_provenance.lease_id,
    )

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
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE
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
    driver.circulation_ownership.mark_thermal_owned(
        driver.cleanup_provenance.lease_id,
    )
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
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE
    assert len(factory.delivery.calls) == calls_before


def test_stale_body_evidence_blocks_cleanup_without_destroying_provenance() -> None:
    """Uncertainty suspends use of verified origin; it does not prove takeover."""

    orchestrator, driver, factory = _driver_with_residual_body_entitlement()
    entitlement = orchestrator.ownership.residual_termination
    assert entitlement is not None
    calls_before = len(factory.delivery.calls)

    stale = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=40),
                pool_active=True,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(0),
                native_observation_at=NOW + timedelta(seconds=2),
            ),
            delivery_factory=factory,
        )
    )

    assert stale.state is ThermalAutomaticDriverState.BLOCKED
    assert stale.blocker == "thermal_termination_pool_activity_unusable"
    assert orchestrator.ownership.residual_termination == entitlement
    assert driver.cleanup_provenance is None
    assert len(factory.delivery.calls) == calls_before

    fresh = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=41),
                pool_active=True,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(0),
            ),
            delivery_factory=factory,
        )
    )
    assert fresh.state is ThermalAutomaticDriverState.CONVERGED
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is not None

    requested = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=42),
                pool_active=True,
                mode=ThermalRequestedMode.OFF,
                filtration_remaining=timedelta(0),
            ),
            delivery_factory=factory,
        )
    )
    assert requested.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert isinstance(factory.delivery.calls[-1], SetBodyActive)
    assert factory.delivery.calls[-1].active is False
    assert len(factory.delivery.calls) == calls_before + 1


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


def test_driver_gate_loss_does_not_promote_unverified_cleanup_proof() -> None:
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
    assert orchestrator.ownership.residual_termination is None
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


def test_accepted_unverified_body_times_out_without_cleanup_or_retry() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        verification_timeout=timedelta(seconds=10),
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
    asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                verification_timeout=timedelta(seconds=10),
            ),
            delivery_factory=factory,
        )
    )

    timed_out = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=12),
                pool_active=False,
                verification_timeout=timedelta(seconds=10),
            ),
            delivery_factory=factory,
        )
    )
    later = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=13),
                pool_active=False,
                verification_timeout=timedelta(seconds=10),
            ),
            delivery_factory=factory,
        )
    )

    assert timed_out.state is ThermalAutomaticDriverState.BLOCKED
    assert timed_out.blocker == "verification_deadline_reached"
    assert later.state is ThermalAutomaticDriverState.BLOCKED
    assert len(delivery.calls) == 1
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    assert timed_out.runtime_ownership_summary[
        "terminal_transition_current_status"
    ] == "relinquished"
    assert timed_out.runtime_ownership_summary[
        "terminal_transition_affected_concept"
    ] == "body_activation"

    driver.set_enabled(
        False,
        changed_at=NOW + timedelta(seconds=14),
        current_epoch_identity=driver.last_epoch_identity,
    )
    driver.set_enabled(
        True,
        changed_at=NOW + timedelta(seconds=15),
        current_epoch_identity=driver.last_epoch_identity,
    )
    fresh = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=16),
                pool_active=False,
                verification_timeout=timedelta(seconds=10),
            ),
            delivery_factory=factory,
        )
    )
    assert fresh.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert len(delivery.calls) == 2

def test_preempted_thermal_session_allows_genuinely_fresh_successor_session() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)

    baseline = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    # Session A: PoolOS accepts a body activation and begins an owned lifecycle.
    first = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=False,
    )
    started = asyncio.run(
        driver.process_epoch(first, delivery_factory=factory)
    )
    assert started.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is True

    confirmed = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
    )
    asyncio.run(driver.process_epoch(confirmed, delivery_factory=factory))

    first_lease = orchestrator.ownership.state.lease
    assert first_lease is not None
    first_generation = first_lease.generation
    first_lease_id = first_lease.lease_id

    # Session A is preempted through the real automatic-driver path:
    # authoritative native Pool OFF appears after PoolOS established ownership.
    native_off = ExternalChangeEvent(
        concept="pool.active",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value=True,
        new_value=False,
        observed_at=NOW + timedelta(seconds=3),
        external_policy="accept",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=False,
    )

    preempted_frame = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=False,
    )

    preempted_result = asyncio.run(
        driver.process_epoch(
            replace(
                preempted_frame,
                external_changes=ExternalChangeBatch((native_off,)),
            ),
            delivery_factory=factory,
        )
    )

    assert preempted_result.state is ThermalAutomaticDriverState.PREEMPTED
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.PREEMPTED
    )

    first_terminal_lease = orchestrator.ownership.state.lease
    assert first_terminal_lease is not None
    assert first_terminal_lease.lease_id == first_lease_id

    # Do NOT disable/re-enable the thermal execution driver here.
    # Production remains enabled. The old execution has ended physically;
    # a later authoritative epoch presents a genuinely fresh opportunity.
    # Session B begins on the very next fresh authoritative Pool-OFF epoch.
    calls_before = len(delivery.calls)

    off_epoch = _frame(
        orchestrator,
        NOW + timedelta(seconds=4),
        pool_active=False,
    )

    result = asyncio.run(
        driver.process_epoch(
            off_epoch,
            delivery_factory=factory,
        )
    )

    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert result.blocker != "runtime_ownership_promotion_denied:ownership_terminal"
    assert len(delivery.calls) == calls_before + 1
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is True

    # Fresh Session B must immediately own a new generation derived only from
    # its newly accepted delivery.
    second_lease = orchestrator.ownership.state.lease
    assert second_lease is not None
    assert second_lease.lease_id != first_lease_id
    assert second_lease.generation > first_generation
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.OWNED
    )

    successor_confirmed = _frame(
        orchestrator,
        NOW + timedelta(seconds=5),
        pool_active=True,
    )
    asyncio.run(
        driver.process_epoch(successor_confirmed, delivery_factory=factory)
    )

    second_lease = orchestrator.ownership.state.lease
    assert second_lease is not None
    assert second_lease.lease_id != first_lease_id
    assert second_lease.generation > first_generation
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.OWNED
    )


def test_preempted_session_successor_completes_solar_and_defers_filtration() -> None:
    """A fresh successor generation must complete the full Pool Solar lifecycle."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()

    #
    # SESSION A
    #
    # Establish real PoolOS ownership, then terminate it as PREEMPTED through
    # the same automatic-driver/native-event path exercised by production.
    #
    baseline_a = _frame(orchestrator, NOW, pool_active=False)
    driver.note_disabled_epoch(baseline_a)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline_a.epoch_identity,
    )

    started_a = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
            ),
            delivery_factory=factory,
        )
    )
    assert started_a.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].active is True

    asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=True,
            ),
            delivery_factory=factory,
        )
    )

    lease_a = orchestrator.ownership.state.lease
    assert lease_a is not None
    lease_a_id = lease_a.lease_id
    generation_a = lease_a.generation

    native_off = ExternalChangeEvent(
        concept="pool.active",
        semantic_event_type="native_value_changed",
        native_object_id="B1101",
        previous_value=True,
        new_value=False,
        observed_at=NOW + timedelta(seconds=3),
        external_policy="accept",
        action_taken="observe",
        notification_recommended=True,
        reconciliation_required=False,
    )

    preempted_a = asyncio.run(
        driver.process_epoch(
            replace(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=3),
                    pool_active=False,
                ),
                external_changes=ExternalChangeBatch((native_off,)),
            ),
            delivery_factory=factory,
        )
    )

    assert preempted_a.state is ThermalAutomaticDriverState.PREEMPTED
    assert (
        orchestrator.ownership.state.status
        is ThermalRuntimeOwnershipStatus.PREEMPTED
    )

    #
    # SESSION B
    #
    # Start a genuinely new PoolOS-controlled Solar lifecycle on the same
    # continuously-enabled driver. Use the already-proven probe sequence.
    #
    session_b = NOW + timedelta(seconds=10)

    probe_baseline = _frame(
        orchestrator,
        session_b,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=1500,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        solar_temperature=90.0,
        evaluator=evaluator,
        driver=driver,
    )

    assert probe_baseline.thermal is not None
    assert probe_baseline.thermal.pool.plan.desired.reason_code == (
        "pool_temperature_probe_required"
    )

    results = []

    for seconds, active, rpm, configured, heater, temperature_missing in (
        (1.0, False, 0, 1500, "00000", True),
        (2.0, True, 0, 1500, "00000", True),
        (3.0, True, 1500, 1500, "00000", True),
        (34.0, True, 1500, 1500, "00000", False),
        (64.0, True, 1500, 1500, "00000", False),
        (124.0, True, 1500, 1500, "00000", False),
        (125.0, True, 2900, 2900, "00000", False),
        (126.0, True, 2900, 2900, "00000", False),
        (127.0, True, 2900, 2900, "H0002", False),
    ):
        results.append(
            asyncio.run(
                driver.process_epoch(
                    _frame(
                        orchestrator,
                        session_b + timedelta(seconds=seconds),
                        pool_active=active,
                        pump_rpm=rpm,
                        configured_rpm=configured,
                        pool_heater=heater,
                        mode=ThermalRequestedMode.SOLAR,
                        missing=("pool.temperature",) if temperature_missing else (),
                        solar_temperature=91.0,
                        evaluator=evaluator,
                        driver=driver,
                        verification_timeout=timedelta(seconds=300),
                    ),
                    delivery_factory=factory,
                )
            )
        )

    assert all(
        result.blocker != "runtime_ownership_promotion_denied:ownership_terminal"
        for result in results
    )

    lease_b = orchestrator.ownership.state.lease
    assert lease_b is not None
    assert lease_b.lease_id != lease_a_id
    assert lease_b.generation > generation_a

    result = results[-1]
    assert result.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    for seconds in (128, 158):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    session_b + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="H0002",
                    solar_active=True,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    assert result.blocker == "automatic_thermal_solar_engaged"

    #
    # TARGET SATISFIED
    #
    # Remaining filtration exists but is explicitly deferrable. Thermal
    # cleanup must therefore choose NO immediate 2600 RPM successor.
    #
    for seconds in (279, 879):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    session_b + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2900,
                    configured_rpm=2900,
                    pool_heater="H0002",
                    pool_temperature=90.0,
                    solar_active=True,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=91.0,
                    filtration_remaining=timedelta(hours=2),
                    filtration_disposition=FiltrationDisposition.CREDITING,
                    filtration_independent_disposition=(
                        FiltrationDisposition.DEFERRED_OPTIMIZATION
                    ),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    assert result.state is ThermalAutomaticDriverState.AWAITING_TERMINATION_VERIFICATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.OFF

    source_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                session_b + timedelta(seconds=880),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )

    assert source_off.state is ThermalAutomaticDriverState.CONVERGED
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is not None

    cleanup_frame = _frame(
        orchestrator,
        session_b + timedelta(seconds=881),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        pool_temperature=90.0,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=91.0,
        filtration_remaining=timedelta(hours=2),
        filtration_disposition=FiltrationDisposition.CREDITING,
        filtration_independent_disposition=(
            FiltrationDisposition.DEFERRED_OPTIMIZATION
        ),
        evaluator=evaluator,
        driver=driver,
    )

    assert cleanup_frame.filtration_successor is not None
    assert cleanup_frame.filtration_successor.total_remaining_runtime > timedelta(0)
    assert cleanup_frame.filtration_successor.independent_disposition is (
        FiltrationDisposition.DEFERRED_OPTIMIZATION
    )
    assert cleanup_frame.filtration_successor.immediate_circulation_required is False
    assert cleanup_frame.filtration_successor.successor_target_rpm is None
    assert cleanup_frame.filtration_successor.target_semantics is (
        FiltrationTargetSemantics.NONE
    )

    calls_before_pool_off = len(delivery.calls)

    requested_off = asyncio.run(
        driver.process_epoch(
            cleanup_frame,
            delivery_factory=factory,
        )
    )

    assert requested_off.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
    assert len(delivery.calls) == calls_before_pool_off + 1
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].equipment_id == ThermalBody.POOL.value
    assert delivery.calls[-1].active is False

    pending_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                session_b + timedelta(seconds=882),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )

    assert pending_off.state is ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION

    verified_off = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                session_b + timedelta(seconds=883),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                pool_temperature=90.0,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=91.0,
                filtration_remaining=timedelta(hours=2),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=(
                    FiltrationDisposition.DEFERRED_OPTIMIZATION
                ),
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )

    assert verified_off.state is ThermalAutomaticDriverState.CONVERGED
    assert verified_off.blocker == "thermal_cleanup_pool_body_off_verified"
    assert driver.cleanup_provenance is None
    assert driver.cleanup_attempt is None
    assert driver.circulation_ownership.owner is PoolCirculationOwner.NONE

    # The remaining filtration obligation must NOT trigger immediate ordinary
    # filtration during this thermal cleanup.
    assert not any(
        isinstance(operation, SetPumpSpeed) and operation.rpm == 2600
        for operation in delivery.calls
    )


def test_owned_body_activation_survives_native_exact_solar_convergence() -> None:
    """Native controller convergence to the exact live plan must not preempt ownership."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()

    # Match the live 2026-09-10 precondition: Pool water was recently
    # authoritatively observed at 87 F during valid Solar circulation.
    # Two chronological observations establish/stabilize the reusable
    # circulating water temperature before the operator turns Pool OFF.
    _frame(
        orchestrator,
        NOW - timedelta(seconds=130),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        mode=ThermalRequestedMode.SOLAR,
        pool_temperature=87.0,
        solar_temperature=145.0,
        missing=(),
        filtration_remaining=timedelta(hours=6),
        filtration_disposition=FiltrationDisposition.CREDITING,
        filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        evaluator=evaluator,
    )

    _frame(
        orchestrator,
        NOW - timedelta(seconds=5),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        mode=ThermalRequestedMode.SOLAR,
        pool_temperature=87.0,
        solar_temperature=145.0,
        missing=(),
        filtration_remaining=timedelta(hours=6),
        filtration_disposition=FiltrationDisposition.CREDITING,
        filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        evaluator=evaluator,
    )

    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=2900,
        pool_heater="00000",
        solar_active=False,
        mode=ThermalRequestedMode.SOLAR,
        pool_temperature=87.0,
        solar_temperature=145.0,
        missing=(),
        filtration_remaining=timedelta(hours=6),
        filtration_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        evaluator=evaluator,
    )

    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    # PoolOS begins a fresh Solar execution from Pool OFF.
    started = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=False,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=87.0,
                solar_temperature=145.0,
                missing=(),
                filtration_remaining=timedelta(hours=6),
                filtration_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
                filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
                evaluator=evaluator,
            ),
            delivery_factory=factory,
        )
    )

    assert started.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetBodyActive)
    assert delivery.calls[-1].equipment_id == ThermalBody.POOL.value
    assert delivery.calls[-1].active is True

    first_lease = orchestrator.ownership.state.lease
    assert first_lease is not None
    first_lease_id = first_lease.lease_id
    first_generation = first_lease.generation
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED

    # Authoritative native evidence verifies the body activation.
    verified_body = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=True,
                pump_rpm=0,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=87.0,
                solar_temperature=145.0,
                missing=(),
                filtration_remaining=timedelta(hours=6),
                filtration_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
                filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
                evaluator=evaluator,
            ),
            delivery_factory=factory,
        )
    )

    assert verified_body.runtime_ownership_summary[
        "owns_body_activation"
    ] is True
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED

    # IntelliCenter now performs its coupled native behavior after Pool activation:
    # Solar becomes active and pump converges to the exact PoolOS Solar baseline.
    # There is no contradictory external-change event and the observed state
    # exactly matches the still-current live Solar plan.
    converged = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=20),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                pool_temperature=87.0,
                solar_temperature=145.0,
                missing=(),
                filtration_remaining=timedelta(hours=6),
                filtration_disposition=FiltrationDisposition.CREDITING,
                filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
                evaluator=evaluator,
            ),
            delivery_factory=factory,
        )
    )

    # This is the production regression from 2026-09-10.
    # Before the fix this becomes PREEMPTED with:
    # runtime_ownership_preempted:execution_currentness_unprovable:
    # thermal_execution_convergence_not_attributed
    assert converged.runtime_ownership_status == "owned"
    assert converged.state is not ThermalAutomaticDriverState.PREEMPTED
    assert (
        converged.runtime_ownership_summary["terminal_transition_current_status"]
        is None
    )
    assert (
        converged.runtime_ownership_summary["terminal_transition_reason_code"]
        is None
    )

    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.lease_id == first_lease_id
    assert lease.generation == first_generation
    assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.OWNED
