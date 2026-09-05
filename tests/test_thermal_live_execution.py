from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_flight_recorder import (
    ExecutionRecordType,
    InMemoryExecutionFlightRecorder,
)
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetBodyActive,
    SetHeatMode,
    SetHydraulicRoute,
    SetPumpSpeed,
    StartPump,
    StopPump,
    ThermalBody,
)
from poolos.native_configuration_policy import (
    NativeConfigurationGuard,
    NativeConfigurationInput,
    NativeRpmAssignment,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
)
from poolos.thermal_execution_planning import (
    ThermalCurrentState,
    ThermalDesiredState,
    ThermalExecutionPlanAssessment,
    ThermalExecutionPlanBuilder,
)
from poolos.thermal_execution_currentness import (
    ThermalExecutionCurrentness,
    ThermalExecutionProgress,
)
from poolos.thermal_live_execution import (
    COMMISSIONED_THERMAL_PUMP_ID,
    ThermalLiveAuthorizationDisposition,
    ThermalLiveAuthorizationEngine,
    ThermalLiveAuthorizationResult,
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionContext,
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
    ThermalLiveExecutionStatus,
    ThermalHydraulicSafetyEvidence,
    ThermalLiveSafetyEvidence,
)


NOW = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)


def desired(
    source: PhysicalHeatMode,
    rpm: int | None,
    *,
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalDesiredState:
    return ThermalDesiredState(
        evaluated_at=NOW,
        body=body,
        requested_mode="solar_preferred",
        selected_source=source,
        required_pump_rpm=rpm,
        reason_code=f"selected_{source.value}",
        rpm_reason_code=None if rpm is None else f"baseline:{rpm}",
        rationale=("Thermal policy selected the commissioned physical state.",),
        criteria=("fresh_authoritative_native_evidence",),
        evidence={"temperature_f": 86.0, "target_f": 90.0},
    )


def thermal_plan(
    current_source: PhysicalHeatMode,
    current_rpm: int | None,
    desired_source: PhysicalHeatMode,
    desired_rpm: int | None,
    *,
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalExecutionPlanAssessment:
    return ThermalExecutionPlanBuilder().build(
        desired(desired_source, desired_rpm, body=body),
        ThermalCurrentState(
            observed_at=NOW,
            body=body,
            selected_source=current_source,
            pump_rpm=current_rpm,
        ),
    )


def policy(
    scope: ThermalLiveCommissioningScope = ThermalLiveCommissioningScope.POOL,
    *,
    enabled: bool = True,
) -> ThermalLiveExecutionPolicy:
    return ThermalLiveExecutionPolicy(
        thermal_live_execution_enabled=enabled,
        commissioning_scope=scope,
    )


def evidence(
    plan: ThermalExecutionPlanAssessment,
    *,
    at: datetime = NOW,
    evaluation_id: str = "evaluation-1",
    current_evaluation_id: str = "evaluation-1",
    current_plan_id: str | None = None,
    body_active: bool = True,
    native_available: bool = True,
    manual_available: bool = True,
    fresh: bool = True,
    health: bool = True,
    hydraulic_safe: bool = True,
    hydraulic: ThermalHydraulicSafetyEvidence | None = None,
    configuration: NativeConfigurationInput = NativeConfigurationInput(),
    contradictions: tuple[str, ...] = (),
    interrupted: bool = False,
    execution_currentness: ThermalExecutionCurrentness | None = None,
) -> ThermalLiveSafetyEvidence:
    if hydraulic is None:
        hydraulic = ThermalHydraulicSafetyEvidence(
            target_body=plan.desired.body,
            pool_active=(
                body_active
                if plan.desired.body is ThermalBody.POOL
                else False
            ),
            spa_active=(
                body_active
                if plan.desired.body is ThermalBody.HOT_TUB
                else False
            ),
            pool_activity_fresh=True,
            spa_activity_fresh=True,
            pool_activity_usable=True,
            spa_activity_usable=True,
        )
    return ThermalLiveSafetyEvidence(
        evaluated_at=at,
        evaluation_id=evaluation_id,
        current_evaluation_id=current_evaluation_id,
        current_plan_id=current_plan_id or plan.plan_id,
        native_transport_available=native_available,
        manual_transport_available=manual_available,
        required_observations_fresh=fresh,
        observation_health_acceptable=health,
        body_active=body_active,
        hydraulic_safety_acceptable=hydraulic_safe,
        hydraulic=hydraulic,
        native_configuration=NativeConfigurationGuard().evaluate(configuration),
        contradictory_evidence=contradictions,
        interrupted_execution_present=interrupted,
        execution_currentness=execution_currentness,
    )


@dataclass
class FakeThermalDelivery:
    available: bool = True
    statuses: list[CommandStatus] = field(default_factory=list)
    calls: list[tuple[PoolOperation, str]] = field(default_factory=list)

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt:
        self.calls.append((operation, correlation_id))
        status = self.statuses.pop(0) if self.statuses else CommandStatus.ACKNOWLEDGED
        return CommandReceipt(
            status=status,
            command_id=f"receipt-{len(self.calls)}",
            issued_at=NOW,
            acknowledged_at=NOW if status is CommandStatus.ACKNOWLEDGED else None,
            verification_required=True,
        )


def store(
    observation_id: str,
    value: object,
    *,
    at: datetime,
    body: ThermalBody = ThermalBody.POOL,
    hydraulics_at: datetime | None = None,
) -> ObservationStore:
    observations = ObservationStore()
    hydraulic_timestamp = hydraulics_at or at
    values = {
        observation_id: (value, at),
        "pool.active": (
            body is ThermalBody.POOL,
            hydraulic_timestamp,
        ),
        "spa.active": (
            body is ThermalBody.HOT_TUB,
            hydraulic_timestamp,
        ),
    }
    for concept, (observed_value, observed_at) in values.items():
        observations.put(
            PoolObservation(
                observation_id=concept,
                value=observed_value,
                observed_at=observed_at,
                source_kind=ObservationSourceKind.LIVE,
                source_id="native-intellicenter",
                quality=ObservationQuality.GOOD,
                confidence=1.0,
            )
        )
    return observations


def hydraulic_store(
    *,
    at: datetime,
    pool_active: bool | None = True,
    spa_active: bool | None = False,
    pump_rpm: int = 3000,
    stale: tuple[str, ...] = (),
    unusable: tuple[str, ...] = (),
) -> ObservationStore:
    observations = ObservationStore()
    values: dict[str, object | None] = {
        "pool.active": pool_active,
        "spa.active": spa_active,
        "pump.rpm": pump_rpm,
    }
    for observation_id, value in values.items():
        if value is None:
            continue
        observed_at = (
            at - timedelta(minutes=1) if observation_id in stale else at
        )
        observations.put(
            PoolObservation(
                observation_id=observation_id,
                value=value,
                observed_at=observed_at,
                source_kind=ObservationSourceKind.LIVE,
                source_id="native-intellicenter",
                quality=(
                    ObservationQuality.SUSPECT
                    if observation_id in unusable
                    else ObservationQuality.GOOD
                ),
                confidence=1.0,
            )
        )
    return observations


def hydraulic_evidence(
    *,
    target_body: ThermalBody,
    pool_active: bool | None,
    spa_active: bool | None,
    pool_fresh: bool = True,
    spa_fresh: bool = True,
    pool_usable: bool = True,
    spa_usable: bool = True,
) -> ThermalHydraulicSafetyEvidence:
    return ThermalHydraulicSafetyEvidence(
        target_body=target_body,
        pool_active=pool_active,
        spa_active=spa_active,
        pool_activity_fresh=pool_fresh,
        spa_activity_fresh=spa_fresh,
        pool_activity_usable=pool_usable,
        spa_activity_usable=spa_usable,
    )


def priming_plan(
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalExecutionPlanAssessment:
    source = (
        PhysicalHeatMode.SOLAR
        if body is ThermalBody.POOL
        else PhysicalHeatMode.GAS
    )
    return ThermalExecutionPlanBuilder().build(
        desired(
            source,
            2900 if body is ThermalBody.POOL else 3000,
            body=body,
        ),
        ThermalCurrentState(
            observed_at=NOW,
            body=body,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=0,
            body_active=True,
        ),
    )


def delivered_priming_session(
    body: ThermalBody = ThermalBody.POOL,
) -> tuple[
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionSession,
]:
    plan = priming_plan(body)
    live_policy = policy(
        ThermalLiveCommissioningScope.POOL
        if body is ThermalBody.POOL
        else ThermalLiveCommissioningScope.HOT_TUB
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=live_policy, evidence=evidence(plan))
    session = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=live_policy,
            evidence=evidence(plan, at=NOW + timedelta(seconds=1)),
            delivery=FakeThermalDelivery(),
        )
    )
    return engine, live_policy, session


def inactive_body_plan(body: ThermalBody) -> ThermalExecutionPlanAssessment:
    return ThermalExecutionPlanBuilder().build(
        desired(PhysicalHeatMode.SOLAR, 2900, body=body),
        ThermalCurrentState(
            observed_at=NOW,
            body=body,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=0,
            body_active=False,
        ),
    )


def authorize(
    plan: ThermalExecutionPlanAssessment,
    *,
    live_policy: ThermalLiveExecutionPolicy | None = None,
    live_evidence: ThermalLiveSafetyEvidence | None = None,
    step_index: int = 0,
):
    return ThermalLiveAuthorizationEngine().authorize(
        plan,
        step_index=step_index,
        policy=live_policy or policy(),
        evidence=live_evidence or evidence(plan),
    )


def test_default_kill_switch_and_scope_deny_live_authority() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)

    result = authorize(plan, live_policy=ThermalLiveExecutionPolicy())

    assert result.disposition is ThermalLiveAuthorizationDisposition.BLOCKED
    assert "thermal_live_kill_switch_disabled" in result.blocking_reasons
    assert "thermal_live_commissioning_scope_disabled" in result.blocking_reasons


@pytest.mark.parametrize(
    ("body", "scope", "authorized"),
    (
        (ThermalBody.POOL, ThermalLiveCommissioningScope.POOL, True),
        (ThermalBody.POOL, ThermalLiveCommissioningScope.HOT_TUB, False),
        (ThermalBody.HOT_TUB, ThermalLiveCommissioningScope.HOT_TUB, True),
        (ThermalBody.HOT_TUB, ThermalLiveCommissioningScope.POOL, False),
    ),
)
def test_one_body_commissioning_scope_is_exact(
    body: ThermalBody,
    scope: ThermalLiveCommissioningScope,
    authorized: bool,
) -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.GAS,
        3000,
        body=body,
    )

    result = authorize(plan, live_policy=policy(scope))

    assert result.authorized is authorized


def test_only_commissioned_pump_and_thermal_baselines_are_authorized() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert plan.operations[0].equipment_id == COMMISSIONED_THERMAL_PUMP_ID
    assert authorize(plan).authorized

    wrong_pump = replace(
        plan.operations[0],
        equipment_id="other-pump",
    )
    altered = replace(plan, operations=(wrong_pump, *plan.operations[1:]))
    wrong_rpm = replace(plan.operations[0], rpm=2600)
    nonthermal_rpm = replace(plan, operations=(wrong_rpm, *plan.operations[1:]))

    assert "uncommissioned_thermal_pump" in authorize(altered).blocking_reasons
    assert "nonthermal_or_uncommissioned_pump_rpm" in authorize(
        nonthermal_rpm
    ).blocking_reasons


def test_whole_plan_structural_preflight_reuses_live_operation_contracts() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        0,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveAuthorizationEngine()

    accepted = engine.structural_preflight(plan, policy=policy())

    assert accepted.eligible
    assert accepted.blocking_reasons == ()


@pytest.mark.parametrize(
    "operation",
    (
        StopPump(equipment_id=COMMISSIONED_THERMAL_PUMP_ID),
        SetBodyActive(equipment_id=ThermalBody.POOL, active=False),
        SetHydraulicRoute(
            equipment_id="shared",
            suction_body_id="pool",
            return_body_id="hot_tub",
        ),
        PoolOperation(equipment_id="unknown"),
        SetPumpSpeed(equipment_id=COMMISSIONED_THERMAL_PUMP_ID, rpm=1500),
    ),
)
def test_whole_plan_preflight_rejects_any_unsupported_future_step(
    operation: PoolOperation,
) -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    assert len(plan.operations) >= 2
    altered = replace(
        plan,
        operations=(plan.operations[0], operation),
        step_specifications=(
            plan.step_specifications[0],
            replace(
                plan.step_specifications[1],
                operation_id=operation.operation_id,
            ),
        ),
    )

    result = ThermalLiveAuthorizationEngine().structural_preflight(
        altered,
        policy=policy(),
    )

    assert not result.eligible
    assert any(reason.startswith("step_1:") for reason in result.blocking_reasons)


@pytest.mark.parametrize(
    "operation",
    (
        StartPump(equipment_id=COMMISSIONED_THERMAL_PUMP_ID),
        StopPump(equipment_id=COMMISSIONED_THERMAL_PUMP_ID),
        SetHydraulicRoute(
            equipment_id="shared",
            suction_body_id="pool",
            return_body_id="hot_tub",
        ),
        PoolOperation(equipment_id="FTR01"),
    ),
)
def test_nonthermal_operations_are_denied(operation: PoolOperation) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    altered = replace(
        plan,
        operations=(operation, *plan.operations[1:]),
        step_specifications=(
            replace(
                plan.step_specifications[0],
                operation_id=operation.operation_id,
            ),
            *plan.step_specifications[1:],
        ),
    )

    result = authorize(altered)

    assert not result.authorized
    assert any(reason.startswith("nonthermal_operation:") for reason in result.blocking_reasons)


def test_unknown_heat_body_is_rejected_by_canonical_type() -> None:
    with pytest.raises(ValueError, match="unsupported thermal body"):
        SetHeatMode(equipment_id="unknown", mode=PhysicalHeatMode.SOLAR)


@pytest.mark.parametrize(
    ("configuration", "expected_reason"),
    (
        (
            NativeConfigurationInput(native_solar_preferred=True),
            "native_configuration_conflict:native_solar_preferred_conflict",
        ),
        (
            NativeConfigurationInput(
                rpm_assignments=(NativeRpmAssignment("Solar", 2900),)
            ),
            "native_configuration_conflict:native_rpm_assignment_conflict",
        ),
    ),
)
def test_solar_native_configuration_conflicts_block_authority(
    configuration: NativeConfigurationInput,
    expected_reason: str,
) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)

    result = authorize(plan, live_evidence=evidence(plan, configuration=configuration))

    assert expected_reason in result.blocking_reasons


def test_gas_native_rpm_conflict_blocks_and_is_diagnosable() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.GAS, 3000)
    configuration = NativeConfigurationInput(
        rpm_assignments=(NativeRpmAssignment("Spa heater", 3000),)
    )

    result = authorize(plan, live_evidence=evidence(plan, configuration=configuration))

    assert result.blocking_reasons == (
        "native_configuration_conflict:native_rpm_assignment_conflict",
    )


def test_unrelated_native_conflict_neither_grants_nor_blocks_wrong_scope() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    configuration = NativeConfigurationInput(
        rpm_assignments=(NativeRpmAssignment("Spillway", 2900),)
    )

    disabled = authorize(
        plan,
        live_policy=ThermalLiveExecutionPolicy(),
        live_evidence=evidence(plan, configuration=configuration),
    )
    enabled = authorize(
        plan,
        live_evidence=evidence(plan, configuration=configuration),
    )

    assert not disabled.authorized
    assert enabled.authorized


@pytest.mark.parametrize("body", (ThermalBody.POOL, ThermalBody.HOT_TUB))
def test_inactive_body_blocks_autonomous_thermal_execution(body: ThermalBody) -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
        body=body,
    )
    scope = (
        ThermalLiveCommissioningScope.POOL
        if body is ThermalBody.POOL
        else ThermalLiveCommissioningScope.HOT_TUB
    )

    result = authorize(
        plan,
        live_policy=policy(scope),
        live_evidence=evidence(plan, body_active=False),
    )

    assert "target_body_inactive" in result.blocking_reasons


@pytest.mark.parametrize(
    "change",
    (
        {"native_available": False},
        {"manual_available": False},
        {"fresh": False},
        {"health": False},
        {"hydraulic_safe": False},
        {"contradictions": ("pump_truth_conflict",)},
        {"interrupted": True},
    ),
)
def test_all_live_safety_gates_fail_closed(change: dict[str, object]) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)

    result = authorize(plan, live_evidence=evidence(plan, **change))  # type: ignore[arg-type]

    assert not result.authorized


def test_stale_and_superseded_plans_are_denied() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)

    stale = authorize(
        plan,
        live_evidence=evidence(plan, at=NOW + timedelta(minutes=3)),
    )
    newer_evaluation = authorize(
        plan,
        live_evidence=evidence(plan, current_evaluation_id="evaluation-2"),
    )
    newer_plan = authorize(
        plan,
        live_evidence=evidence(plan, current_plan_id="new-plan"),
    )

    assert "thermal_plan_stale" in stale.blocking_reasons
    assert "evaluation_superseded" in newer_evaluation.blocking_reasons
    assert "plan_superseded" in newer_plan.blocking_reasons


def test_no_second_step_is_delivered_before_first_native_verification() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    live_evidence = evidence(plan)
    session = engine.begin(plan, policy=policy(), evidence=live_evidence)
    delivery = FakeThermalDelivery()

    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=live_evidence,
            delivery=delivery,
        )
    )

    assert waiting.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert len(delivery.calls) == 1
    assert plan.operations[0].metadata["command_delivery_enabled"] is False
    assert waiting.execution_plan.steps[0].operation.metadata[
        "command_delivery_enabled"
    ] is True
    assert waiting.execution_plan.steps[0].preconditions[
        "thermal_live_authorization_required"
    ] is True
    with pytest.raises(ValueError, match="not ready"):
        asyncio.run(
            engine.deliver_current_step(
                waiting,
                policy=policy(),
                evidence=evidence(plan, at=NOW + timedelta(seconds=1)),
                delivery=delivery,
            )
        )


@pytest.mark.parametrize("tamper", ("payload", "operation_id"))
def test_tampered_execution_plan_operation_is_never_delivered(tamper: str) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    original_step = session.execution_plan.steps[0]
    if tamper == "payload":
        tampered_operation: PoolOperation = SetHeatMode(
            equipment_id=ThermalBody.POOL,
            mode=PhysicalHeatMode.SOLAR,
            operation_id=original_step.operation.operation_id,
            metadata=original_step.operation.metadata,
        )
    else:
        tampered_operation = replace(
            original_step.operation,
            operation_id="tampered-operation-id",
        )
    tampered_step = replace(original_step, operation=tampered_operation)
    tampered_session = replace(
        session,
        execution_plan=replace(
            session.execution_plan,
            steps=(tampered_step, *session.execution_plan.steps[1:]),
        ),
    )
    delivery = FakeThermalDelivery()

    result = asyncio.run(
        engine.deliver_current_step(
            tampered_session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )

    assert result.status is ThermalLiveExecutionStatus.BLOCKED
    assert result.failure_reason is not None
    assert "execution_plan_operation_" in result.failure_reason
    assert delivery.calls == []


@dataclass(frozen=True, slots=True)
class MismatchedOperationAuthorizationEngine(ThermalLiveAuthorizationEngine):
    def authorize(
        self,
        assessment: ThermalExecutionPlanAssessment,
        *,
        step_index: int,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
        originating_currentness: ThermalExecutionCurrentness | None = None,
        execution_progress: ThermalExecutionProgress | None = None,
    ) -> ThermalLiveAuthorizationResult:
        authorized = super().authorize(
            assessment,
            step_index=step_index,
            policy=policy,
            evidence=evidence,
            originating_currentness=originating_currentness,
            execution_progress=execution_progress,
        )
        return replace(authorized, operation_id="mismatched-authorized-operation")


def test_authorization_operation_id_mismatch_is_never_delivered() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    engine.authorization_engine = MismatchedOperationAuthorizationEngine()
    delivery = FakeThermalDelivery()

    result = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )

    assert result.status is ThermalLiveExecutionStatus.BLOCKED
    assert result.failure_reason == "authorization_operation_id_mismatch"
    assert delivery.calls == []


def test_each_step_records_only_its_fresh_delivery_authorization() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    assert all(
        "source_thermal_live_authorization_id" not in step.metadata
        for step in session.execution_plan.steps
    )
    assert all(
        step.metadata["thermal_live_authorization_required"] == "true"
        for step in session.execution_plan.steps
    )
    delivery = FakeThermalDelivery()

    first_waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )
    first_authorization_id = first_waiting.current_attempt.authorization.authorization_id  # type: ignore[union-attr]
    second_ready = engine.verify_current_step(
        first_waiting,
        store("pump.rpm", 2900, at=NOW + timedelta(seconds=1)),
        current_context=first_waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )
    second_waiting = asyncio.run(
        engine.deliver_current_step(
            second_ready,
            policy=policy(),
            evidence=evidence(plan, at=NOW + timedelta(seconds=2)),
            delivery=delivery,
        )
    )
    second_authorization_id = second_waiting.current_attempt.authorization.authorization_id  # type: ignore[union-attr]

    assert first_authorization_id != second_authorization_id
    assert first_authorization_id in delivery.calls[0][1]
    assert second_authorization_id in delivery.calls[1][1]
    assert first_authorization_id not in delivery.calls[1][1]

    completed = engine.verify_current_step(
        second_waiting,
        store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=3)),
        current_context=second_waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=3),
        source_id="native-intellicenter",
    )
    assert completed.outcome is not None
    assert completed.outcome.step_outcomes[0].metadata[
        "source_authorization_id"
    ] == first_authorization_id
    assert completed.outcome.step_outcomes[1].metadata[
        "source_authorization_id"
    ] == second_authorization_id


@pytest.mark.parametrize(
    ("current_source", "current_rpm", "desired_source", "desired_rpm", "types"),
    (
        (
            PhysicalHeatMode.OFF,
            2600,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.OFF,
            2600,
            PhysicalHeatMode.GAS,
            3000,
            (SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.SOLAR,
            2900,
            PhysicalHeatMode.GAS,
            3000,
            (SetPumpSpeed, SetHeatMode),
        ),
        (
            PhysicalHeatMode.GAS,
            3000,
            PhysicalHeatMode.SOLAR,
            2900,
            (SetHeatMode, SetPumpSpeed),
        ),
    ),
)
def test_phase_one_order_is_preserved_by_live_coordinator(
    current_source: PhysicalHeatMode,
    current_rpm: int,
    desired_source: PhysicalHeatMode,
    desired_rpm: int,
    types: tuple[type[object], ...],
) -> None:
    plan = thermal_plan(current_source, current_rpm, desired_source, desired_rpm)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()

    for sequence, expected_type in enumerate(types, start=1):
        current_evidence = evidence(plan, at=NOW + timedelta(seconds=sequence * 2))
        session = asyncio.run(
            engine.deliver_current_step(
                session,
                policy=policy(),
                evidence=current_evidence,
                delivery=delivery,
            )
        )
        operation = delivery.calls[-1][0]
        assert isinstance(operation, expected_type)
        observation_id, expected = next(
            iter(session.current_attempt.step.expected_observations.items())  # type: ignore[union-attr]
        )
        session = engine.verify_current_step(
            session,
            store(observation_id, expected, at=current_evidence.evaluated_at),
            current_context=session.originating_context,
            policy=policy(),
            evaluated_at=current_evidence.evaluated_at,
            source_id="native-intellicenter",
        )

    assert session.status is ThermalLiveExecutionStatus.COMPLETED
    assert tuple(type(item[0]) for item in delivery.calls) == types


@pytest.mark.parametrize(
    ("source", "desired_rpm"),
    (
        (PhysicalHeatMode.SOLAR, 2900),
        (PhysicalHeatMode.GAS, 3000),
    ),
)
def test_off_transition_deselects_source_only(
    source: PhysicalHeatMode,
    desired_rpm: int,
) -> None:
    plan = thermal_plan(source, desired_rpm, PhysicalHeatMode.OFF, None)
    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], SetHeatMode)
    assert plan.operations[0].mode is PhysicalHeatMode.OFF


def test_source_only_rpm_only_and_already_converged_remain_narrow() -> None:
    rpm_only = thermal_plan(
        PhysicalHeatMode.SOLAR,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    source_only = thermal_plan(
        PhysicalHeatMode.GAS,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    converged = thermal_plan(
        PhysicalHeatMode.SOLAR,
        2880,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    assert [type(item) for item in rpm_only.operations] == [SetPumpSpeed]
    assert [type(item) for item in source_only.operations] == [SetHeatMode]
    assert converged.operations == ()


@pytest.mark.parametrize(
    "status",
    (CommandStatus.REJECTED, CommandStatus.FAILED, CommandStatus.TIMED_OUT),
)
def test_delivery_failure_stops_without_advancing(status: CommandStatus) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery(statuses=[status])

    result = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )

    assert result.status in {
        ThermalLiveExecutionStatus.FAILED,
        ThermalLiveExecutionStatus.TIMED_OUT,
    }
    assert len(delivery.calls) == 1


def test_rpm_settles_pending_then_verifies_within_inclusive_tolerance() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )

    pending = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2874, at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )
    verified = engine.verify_current_step(
        pending,
        store("pump.rpm", 2875, at=NOW + timedelta(seconds=2)),
        current_context=pending.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=2),
        source_id="native-intellicenter",
    )

    assert pending.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert verified.status is ThermalLiveExecutionStatus.READY
    assert len(delivery.calls) == 1


def test_pump_mismatch_at_deadline_times_out() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )

    result = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2600, at=NOW + timedelta(seconds=30)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=30),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.TIMED_OUT


def test_wrong_heater_fails_even_when_htmode_context_is_zero() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.GAS,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    observations = store("pool.raw_heater_id", "H0001", at=NOW + timedelta(seconds=1))
    observations.put(
        PoolObservation(
            observation_id="pool.raw_htmode",
            value="0",
            observed_at=NOW + timedelta(seconds=1),
            source_kind=ObservationSourceKind.LIVE,
            source_id="native-intellicenter",
        )
    )

    result = engine.verify_current_step(
        waiting,
        observations,
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.FAILED


def test_correct_heater_verifies_with_htmode_zero_as_context_only() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.GAS,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    observations = store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=1))
    observations.put(
        PoolObservation(
            observation_id="pool.raw_htmode",
            value="0",
            observed_at=NOW + timedelta(seconds=1),
            source_kind=ObservationSourceKind.LIVE,
            source_id="native-intellicenter",
        )
    )

    result = engine.verify_current_step(
        waiting,
        observations,
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.COMPLETED


def test_stale_authoritative_observation_stops_execution() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.GAS,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )

    result = engine.verify_current_step(
        waiting,
        store(
            "pool.raw_heater_id",
            "H0002",
            at=NOW,
            hydraulics_at=NOW + timedelta(minutes=1),
        ),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(minutes=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.FAILED
    assert result.failure_reason == "authoritative_verification_evidence_unusable"


def test_disabling_kill_switch_during_plan_blocks_next_command_without_restoration() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )
    ready = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2900, at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    blocked = asyncio.run(
        engine.deliver_current_step(
            ready,
            policy=policy(enabled=False),
            evidence=evidence(plan, at=NOW + timedelta(seconds=2)),
            delivery=delivery,
        )
    )

    assert blocked.status is ThermalLiveExecutionStatus.BLOCKED
    assert len(delivery.calls) == 1


@pytest.mark.parametrize(
    ("current_evaluation_id", "current_plan_id"),
    (("evaluation-2", None), ("evaluation-1", "new-plan")),
)
def test_newer_desired_state_prevents_old_plan_from_continuing(
    current_evaluation_id: str,
    current_plan_id: str | None,
) -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=delivery,
        )
    )
    ready = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2900, at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )
    newer = evidence(
        plan,
        at=NOW + timedelta(seconds=2),
        current_evaluation_id=current_evaluation_id,
        current_plan_id=current_plan_id,
    )

    result = asyncio.run(
        engine.deliver_current_step(
            ready,
            policy=policy(),
            evidence=newer,
            delivery=delivery,
        )
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert len(delivery.calls) == 1


def test_interrupted_execution_cannot_resume_or_actuate_after_restart() -> None:
    plan = thermal_plan(PhysicalHeatMode.OFF, 2600, PhysicalHeatMode.SOLAR, 2900)
    engine = ThermalLiveExecutionEngine()

    with pytest.raises(ValueError, match="fresh_reevaluation"):
        engine.begin(
            plan,
            policy=policy(),
            evidence=evidence(plan, interrupted=True),
        )


def test_flight_recorder_and_outcome_retain_why_receipt_and_verification() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.GAS,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    recorder = InMemoryExecutionFlightRecorder()
    engine = ThermalLiveExecutionEngine(recorder=recorder)
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    completed = engine.verify_current_step(
        waiting,
        store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    record_types = tuple(item.record_type for item in recorder.timeline.records)
    assert ExecutionRecordType.PROPOSAL in record_types
    assert ExecutionRecordType.AUTHORIZATION in record_types
    assert ExecutionRecordType.PLAN in record_types
    assert ExecutionRecordType.VERIFICATION in record_types
    assert ExecutionRecordType.OUTCOME in record_types
    assert completed.outcome is not None
    assert completed.outcome.step_outcomes[0].receipt_ids == ("receipt-1",)
    assert completed.outcome.metadata["source_reason_code"] == "selected_solar"
    assert completed.outcome.metadata["rpm_reason_code"] == "baseline:2900"


def test_no_live_execution_is_created_for_already_converged_plan() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.SOLAR,
        2880,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    result = authorize(plan)

    assert not result.authorized
    assert "thermal_plan_not_ready" in result.blocking_reasons


def test_priming_step_does_not_advance_until_60_seconds_continuously_verified() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        0,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert plan.operations[0].rpm == 3000
    assert (
        plan.step_specifications[0].metadata["minimum_verified_hold_seconds"]
        == "60"
    )

    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()

    delivered_at = NOW + timedelta(seconds=1)
    session = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan, at=delivered_at),
            delivery=delivery,
        )
    )

    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        store("pump.rpm", 3000, at=first_verified_at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert session.current_attempt is not None
    assert session.current_attempt.verified_hold_started_at == first_verified_at

    still_holding_at = NOW + timedelta(seconds=61)
    session = engine.verify_current_step(
        session,
        store("pump.rpm", 3000, at=still_holding_at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=still_holding_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert session.current_attempt is not None
    assert session.current_attempt.verified_hold_started_at == first_verified_at

    completed_hold_at = NOW + timedelta(seconds=62)
    session = engine.verify_current_step(
        session,
        store("pump.rpm", 3000, at=completed_hold_at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=completed_hold_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.READY
    assert session.current_attempt is None
    assert session.coordination.current_step_sequence == 2


def test_priming_hold_fails_closed_if_rpm_deviates_before_completion() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        0,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()

    delivered_at = NOW + timedelta(seconds=1)
    session = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan, at=delivered_at),
            delivery=delivery,
        )
    )

    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        store("pump.rpm", 3000, at=first_verified_at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION

    deviation_at = NOW + timedelta(seconds=30)
    session = engine.verify_current_step(
        session,
        store("pump.rpm", 2900, at=deviation_at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=deviation_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.FAILED
    assert session.failure_reason == "priming_verified_hold_continuity_lost"


@pytest.mark.parametrize(
    ("pool_active", "spa_active", "stale", "unusable"),
    (
        (False, False, (), ()),
        (False, True, (), ()),
        (True, True, (), ()),
        (None, False, (), ()),
        (True, None, (), ()),
        (True, False, ("pool.active",), ()),
        (True, False, ("spa.active",), ()),
        (True, False, (), ("pool.active",)),
        (True, False, (), ("spa.active",)),
    ),
)
def test_priming_hold_fails_closed_when_pool_hydraulics_lose_continuity(
    pool_active: bool | None,
    spa_active: bool | None,
    stale: tuple[str, ...],
    unusable: tuple[str, ...],
) -> None:
    plan = priming_plan()
    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert plan.step_specifications[0].metadata["priming_step"] == "true"
    engine, live_policy, session = delivered_priming_session()

    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        hydraulic_store(at=first_verified_at),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )
    assert session.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION

    broken_at = NOW + timedelta(seconds=62)
    session = engine.verify_current_step(
        session,
        hydraulic_store(
            at=broken_at,
            pool_active=pool_active,
            spa_active=spa_active,
            stale=stale,
            unusable=unusable,
        ),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=broken_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.FAILED
    assert session.failure_reason is not None
    assert session.failure_reason.startswith("hydraulic_continuity_lost:")


def test_priming_hold_fails_closed_when_pump_stops() -> None:
    engine, live_policy, session = delivered_priming_session()
    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        hydraulic_store(at=first_verified_at),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )

    stopped_at = NOW + timedelta(seconds=30)
    session = engine.verify_current_step(
        session,
        hydraulic_store(at=stopped_at, pump_rpm=0),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=stopped_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.FAILED
    assert session.failure_reason == "priming_verified_hold_continuity_lost"


def test_uninterrupted_hot_tub_priming_requires_hot_tub_only_topology() -> None:
    engine, live_policy, session = delivered_priming_session(
        ThermalBody.HOT_TUB
    )
    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        hydraulic_store(
            at=first_verified_at,
            pool_active=False,
            spa_active=True,
        ),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )
    completed_hold_at = NOW + timedelta(seconds=62)
    session = engine.verify_current_step(
        session,
        hydraulic_store(
            at=completed_hold_at,
            pool_active=False,
            spa_active=True,
        ),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=completed_hold_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.READY


def test_pool_takeover_during_hot_tub_priming_fails_closed() -> None:
    engine, live_policy, session = delivered_priming_session(
        ThermalBody.HOT_TUB
    )
    first_verified_at = NOW + timedelta(seconds=2)
    session = engine.verify_current_step(
        session,
        hydraulic_store(
            at=first_verified_at,
            pool_active=False,
            spa_active=True,
        ),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )
    takeover_at = NOW + timedelta(seconds=30)
    session = engine.verify_current_step(
        session,
        hydraulic_store(
            at=takeover_at,
            pool_active=True,
            spa_active=False,
        ),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=takeover_at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.FAILED
    assert session.failure_reason == "hydraulic_continuity_lost:other_body_active:pool"


def test_nonpriming_verified_step_still_advances_immediately() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.SOLAR,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert "minimum_verified_hold_seconds" not in plan.step_specifications[0].metadata

    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    delivery = FakeThermalDelivery()

    at = NOW + timedelta(seconds=2)
    session = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan, at=at),
            delivery=delivery,
        )
    )

    session = engine.verify_current_step(
        session,
        store("pump.rpm", 2900, at=at),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.COMPLETED


def test_pool_temperature_probe_rpm_remains_outside_live_authority() -> None:
    probe_desired = ThermalDesiredState(
        evaluated_at=NOW,
        body=ThermalBody.POOL,
        requested_mode="solar",
        selected_source=PhysicalHeatMode.OFF,
        required_pump_rpm=1500,
        reason_code="pool_temperature_probe_required",
        rpm_reason_code="baseline:1500",
        rationale=("Trusted Pool water temperature is required.",),
        criteria=("pool_temperature_untrusted",),
        evidence={},
    )
    plan = ThermalExecutionPlanBuilder().build(
        probe_desired,
        ThermalCurrentState(
            observed_at=NOW,
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=3000,
            body_active=True,
        ),
    )
    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], SetPumpSpeed)
    assert plan.operations[0].rpm == 1500

    result = authorize(plan)

    assert result.authorized is False
    assert "nonthermal_or_uncommissioned_pump_rpm" in result.blocking_reasons


def test_inactive_body_may_authorize_only_its_activation_step() -> None:
    plan = inactive_body_plan(ThermalBody.POOL)

    assert isinstance(plan.operations[0], SetBodyActive)

    first = authorize(
        plan,
        live_evidence=evidence(
            plan,
            body_active=False,
            hydraulic_safe=True,
        ),
        step_index=0,
    )

    assert first.authorized is True
    assert "target_body_inactive" not in first.blocking_reasons
    assert "hydraulic_safety_model_not_satisfied" not in first.blocking_reasons


def test_body_activation_does_not_bypass_explicit_hydraulic_safety_veto() -> None:
    plan = inactive_body_plan(ThermalBody.POOL)

    result = authorize(
        plan,
        live_evidence=evidence(
            plan,
            body_active=False,
            hydraulic_safe=False,
        ),
    )

    assert result.authorized is False
    assert "hydraulic_safety_model_not_satisfied" in result.blocking_reasons


@pytest.mark.parametrize("body", (ThermalBody.POOL, ThermalBody.HOT_TUB))
@pytest.mark.parametrize(
    (
        "target_active",
        "other_active",
        "target_fresh",
        "other_fresh",
        "target_usable",
        "other_usable",
        "authorized",
        "reason",
    ),
    (
        (False, False, True, True, True, True, True, None),
        (False, True, True, True, True, True, False, "other_body_active"),
        (
            True,
            True,
            True,
            True,
            True,
            True,
            False,
            "hydraulic_topology_contradictory:pool_and_hot_tub_active",
        ),
        (
            False,
            None,
            True,
            False,
            True,
            False,
            False,
            "hydraulic_activity_evidence_unusable",
        ),
        (
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            "hydraulic_activity_evidence_not_fresh",
        ),
        (
            None,
            False,
            False,
            True,
            False,
            True,
            False,
            "hydraulic_activity_evidence_unusable",
        ),
        (
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            "hydraulic_activity_evidence_not_fresh",
        ),
    ),
)
def test_body_activation_requires_unambiguous_two_body_hydraulic_evidence(
    body: ThermalBody,
    target_active: bool | None,
    other_active: bool | None,
    target_fresh: bool,
    other_fresh: bool,
    target_usable: bool,
    other_usable: bool,
    authorized: bool,
    reason: str | None,
) -> None:
    plan = inactive_body_plan(body)
    assert isinstance(plan.operations[0], SetBodyActive)
    if body is ThermalBody.POOL:
        pool_active, spa_active = target_active, other_active
        pool_fresh, spa_fresh = target_fresh, other_fresh
        pool_usable, spa_usable = target_usable, other_usable
    else:
        pool_active, spa_active = other_active, target_active
        pool_fresh, spa_fresh = other_fresh, target_fresh
        pool_usable, spa_usable = other_usable, target_usable
    topology = hydraulic_evidence(
        target_body=body,
        pool_active=pool_active,
        spa_active=spa_active,
        pool_fresh=pool_fresh,
        spa_fresh=spa_fresh,
        pool_usable=pool_usable,
        spa_usable=spa_usable,
    )
    live_evidence = evidence(
        plan,
        body_active=target_active is True,
        hydraulic_safe=True,
        hydraulic=topology,
    )

    result = authorize(
        plan,
        live_policy=policy(
            ThermalLiveCommissioningScope.POOL
            if body is ThermalBody.POOL
            else ThermalLiveCommissioningScope.HOT_TUB
        ),
        live_evidence=live_evidence,
    )

    assert result.authorized is authorized
    if reason is not None:
        assert any(item.startswith(reason) for item in result.blocking_reasons)


def test_body_activation_verification_rejects_other_body_takeover() -> None:
    plan = inactive_body_plan(ThermalBody.POOL)
    safe_activation_evidence = evidence(
        plan,
        body_active=False,
        hydraulic_safe=True,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(
        plan,
        policy=policy(),
        evidence=safe_activation_evidence,
    )
    session = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=replace(
                safe_activation_evidence,
                evaluated_at=NOW + timedelta(seconds=1),
            ),
            delivery=FakeThermalDelivery(),
        )
    )
    at = NOW + timedelta(seconds=2)

    session = engine.verify_current_step(
        session,
        hydraulic_store(at=at, pool_active=True, spa_active=True),
        current_context=session.originating_context,
        policy=policy(),
        evaluated_at=at,
        source_id="native-intellicenter",
    )

    assert session.status is ThermalLiveExecutionStatus.FAILED
    assert session.failure_reason == (
        "hydraulic_continuity_lost:"
        "hydraulic_topology_contradictory:pool_and_hot_tub_active"
    )


def test_inactive_body_still_blocks_priming_step_until_activation_verified() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        desired(
            PhysicalHeatMode.SOLAR,
            2900,
            body=ThermalBody.POOL,
        ),
        ThermalCurrentState(
            observed_at=NOW,
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=0,
            body_active=False,
        ),
    )

    assert isinstance(plan.operations[0], SetBodyActive)
    assert isinstance(plan.operations[1], SetPumpSpeed)

    second = authorize(
        plan,
        live_evidence=evidence(
            plan,
            body_active=False,
            hydraulic_safe=False,
        ),
        step_index=1,
    )

    assert second.authorized is False
    assert "target_body_inactive" in second.blocking_reasons
    assert "hydraulic_safety_model_not_satisfied" in second.blocking_reasons


def test_verified_body_activation_allows_following_priming_step() -> None:
    plan = ThermalExecutionPlanBuilder().build(
        desired(
            PhysicalHeatMode.SOLAR,
            2900,
            body=ThermalBody.POOL,
        ),
        ThermalCurrentState(
            observed_at=NOW,
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=0,
            body_active=False,
        ),
    )

    second = authorize(
        plan,
        live_evidence=evidence(
            plan,
            body_active=True,
            hydraulic_safe=True,
        ),
        step_index=1,
    )

    assert second.authorized is True


@pytest.mark.parametrize(
    ("body", "replacement_source"),
    (
        (ThermalBody.POOL, PhysicalHeatMode.OFF),
        (ThermalBody.POOL, PhysicalHeatMode.GAS),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.OFF),
    ),
)
def test_delivered_step_cannot_verify_after_thermal_plan_is_superseded(
    body: ThermalBody,
    replacement_source: PhysicalHeatMode,
) -> None:
    scope = (
        ThermalLiveCommissioningScope.POOL
        if body is ThermalBody.POOL
        else ThermalLiveCommissioningScope.HOT_TUB
    )
    original = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
        body=body,
    )
    replacement = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        replacement_source,
        None if replacement_source is PhysicalHeatMode.OFF else 3000,
        body=body,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(
        original,
        policy=policy(scope),
        evidence=evidence(original),
    )
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(scope),
            evidence=evidence(original),
            delivery=FakeThermalDelivery(),
        )
    )

    result = engine.verify_current_step(
        waiting,
        store(
            (
                "pool.raw_heater_id"
                if body is ThermalBody.POOL
                else "spa.raw_heater_id"
            ),
            "H0002",
            at=NOW + timedelta(seconds=1),
            body=body,
        ),
        current_context=ThermalLiveExecutionContext(
            evaluation_id="evaluation-2",
            plan_id=replacement.plan_id,
        ),
        policy=policy(scope),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert result.failure_reason == "thermal_execution_superseded:evaluation_id"
    assert result.current_attempt is None
    assert result.ownership.owns_heat_source is False


@pytest.mark.parametrize(
    ("body", "source", "rpm", "scope"),
    (
        (
            ThermalBody.POOL,
            PhysicalHeatMode.SOLAR,
            2900,
            ThermalLiveCommissioningScope.POOL,
        ),
        (
            ThermalBody.POOL,
            PhysicalHeatMode.GAS,
            3000,
            ThermalLiveCommissioningScope.POOL,
        ),
        (
            ThermalBody.HOT_TUB,
            PhysicalHeatMode.GAS,
            3000,
            ThermalLiveCommissioningScope.HOT_TUB,
        ),
    ),
)
def test_matching_current_identity_preserves_existing_thermal_execution(
    body: ThermalBody,
    source: PhysicalHeatMode,
    rpm: int,
    scope: ThermalLiveCommissioningScope,
) -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        rpm,
        source,
        rpm,
        body=body,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(
        plan,
        policy=policy(scope),
        evidence=evidence(plan),
    )
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(scope),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    assert waiting.current_attempt is not None
    observation_id, expected = next(
        iter(waiting.current_attempt.step.expected_observations.items())
    )

    completed = engine.verify_current_step(
        waiting,
        store(
            observation_id,
            expected,
            at=NOW + timedelta(seconds=1),
            body=body,
        ),
        current_context=waiting.originating_context,
        policy=policy(scope),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert completed.status is ThermalLiveExecutionStatus.COMPLETED


@pytest.mark.parametrize(
    ("current_context", "reason"),
    (
        (
            ThermalLiveExecutionContext(
                evaluation_id="evaluation-1",
                plan_id="replacement-plan",
            ),
            "thermal_execution_superseded:plan_id",
        ),
        (
            ThermalLiveExecutionContext(
                evaluation_id="evaluation-2",
                plan_id="original-plan-placeholder",
            ),
            "thermal_execution_superseded:evaluation_id",
        ),
    ),
)
def test_verification_requires_matching_current_thermal_identity(
    current_context: ThermalLiveExecutionContext,
    reason: str,
) -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    if current_context.evaluation_id == "evaluation-2":
        current_context = replace(current_context, plan_id=plan.plan_id)
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )

    result = engine.verify_current_step(
        waiting,
        store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=1)),
        current_context=current_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert result.failure_reason == reason


def test_supersession_discards_priming_hold_and_clears_ownership() -> None:
    engine, live_policy, session = delivered_priming_session()
    first_verified_at = NOW + timedelta(seconds=2)
    holding = engine.verify_current_step(
        session,
        hydraulic_store(at=first_verified_at),
        current_context=session.originating_context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )
    assert holding.current_attempt is not None
    assert holding.current_attempt.verified_hold_started_at == first_verified_at
    assert holding.ownership.owns_pump_setpoint is True

    result = engine.verify_current_step(
        holding,
        hydraulic_store(at=NOW + timedelta(seconds=62)),
        current_context=ThermalLiveExecutionContext(
            evaluation_id="evaluation-2",
            plan_id="replacement-plan",
        ),
        policy=live_policy,
        evaluated_at=NOW + timedelta(seconds=62),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert result.current_attempt is None
    assert result.ownership.owns_pump_setpoint is False
    with pytest.raises(ValueError, match="session is not awaiting verification"):
        engine.verify_current_step(
            result,
            hydraulic_store(at=NOW + timedelta(seconds=63)),
            current_context=result.originating_context,
            policy=live_policy,
            evaluated_at=NOW + timedelta(seconds=63),
            source_id="native-intellicenter",
        )


def test_new_epoch_same_purpose_residual_plan_verifies_without_false_supersession() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    delivery = FakeThermalDelivery()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    originating = session.originating_currentness
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(
                plan,
                execution_currentness=originating,
            ),
            delivery=delivery,
        )
    )
    current_plan = ThermalExecutionPlanBuilder().build(
        replace(plan.desired, evaluated_at=NOW + timedelta(seconds=1)),
        ThermalCurrentState(
            observed_at=NOW + timedelta(seconds=1),
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=2900,
            body_active=True,
        ),
    )
    current = ThermalExecutionCurrentness.from_assessment(
        current_plan,
        evaluation_id="evaluation-2",
    )

    result = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2900, at=NOW + timedelta(seconds=1)),
        current_context=ThermalLiveExecutionContext(
            evaluation_id=current.evaluation_id,
            plan_id=current.plan_id,
            execution_currentness=current,
        ),
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.READY
    assert result.coordination.current_step_sequence == 2


def test_current_convergence_does_not_skip_delivered_step_verification() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(
                plan,
                execution_currentness=session.originating_currentness,
            ),
            delivery=FakeThermalDelivery(),
        )
    )
    converged_plan = ThermalExecutionPlanBuilder().build(
        replace(plan.desired, evaluated_at=NOW + timedelta(seconds=1)),
        ThermalCurrentState(
            observed_at=NOW + timedelta(seconds=1),
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.SOLAR,
            pump_rpm=2900,
            body_active=True,
        ),
    )
    current = ThermalExecutionCurrentness.from_assessment(
        converged_plan,
        evaluation_id="evaluation-converged",
    )
    context = ThermalLiveExecutionContext(
        current.evaluation_id,
        current.plan_id,
        current,
    )

    wrong = engine.verify_current_step(
        waiting,
        store("pool.raw_heater_id", "00000", at=NOW + timedelta(seconds=1)),
        current_context=context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert wrong.status is ThermalLiveExecutionStatus.FAILED
    assert wrong.status is not ThermalLiveExecutionStatus.COMPLETED

    second_engine = ThermalLiveExecutionEngine()
    second_session = second_engine.begin(
        plan,
        policy=policy(),
        evidence=evidence(plan),
    )
    second_waiting = asyncio.run(
        second_engine.deliver_current_step(
            second_session,
            policy=policy(),
            evidence=evidence(
                plan,
                execution_currentness=second_session.originating_currentness,
            ),
            delivery=FakeThermalDelivery(),
        )
    )
    verified = second_engine.verify_current_step(
        second_waiting,
        store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=1)),
        current_context=context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert verified.status is ThermalLiveExecutionStatus.COMPLETED


def test_new_epoch_changed_purpose_still_supersedes_before_verification() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(
                plan,
                execution_currentness=session.originating_currentness,
            ),
            delivery=FakeThermalDelivery(),
        )
    )
    gas_plan = ThermalExecutionPlanBuilder().build(
        replace(
            plan.desired,
            evaluated_at=NOW + timedelta(seconds=1),
            requested_mode="gas",
            selected_source=PhysicalHeatMode.GAS,
            required_pump_rpm=3000,
            reason_code="gas_physical_gas",
            rpm_reason_code="baseline:3000",
        ),
        ThermalCurrentState(
            observed_at=NOW + timedelta(seconds=1),
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=2900,
            body_active=True,
        ),
    )
    current = ThermalExecutionCurrentness.from_assessment(
        gas_plan,
        evaluation_id="evaluation-2",
    )

    result = engine.verify_current_step(
        waiting,
        store("pump.rpm", 2900, at=NOW + timedelta(seconds=1)),
        current_context=ThermalLiveExecutionContext(
            current.evaluation_id,
            current.plan_id,
            current,
        ),
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert result.failure_reason == "thermal_execution_purpose_superseded"


def test_priming_hold_continues_across_compatible_runtime_epochs() -> None:
    engine, live_policy, waiting = delivered_priming_session()
    first_verified_at = NOW + timedelta(seconds=2)
    after_priming = ThermalExecutionPlanBuilder().build(
        replace(
            waiting.assessment.desired,
            evaluated_at=first_verified_at,
        ),
        ThermalCurrentState(
            observed_at=first_verified_at,
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=3000,
            body_active=True,
        ),
    )
    current = ThermalExecutionCurrentness.from_assessment(
        after_priming,
        evaluation_id="evaluation-after-priming",
    )
    context = ThermalLiveExecutionContext(
        current.evaluation_id,
        current.plan_id,
        current,
    )

    holding = engine.verify_current_step(
        waiting,
        hydraulic_store(at=first_verified_at),
        current_context=context,
        policy=live_policy,
        evaluated_at=first_verified_at,
        source_id="native-intellicenter",
    )
    completed = engine.verify_current_step(
        holding,
        hydraulic_store(at=NOW + timedelta(seconds=62)),
        current_context=context,
        policy=live_policy,
        evaluated_at=NOW + timedelta(seconds=62),
        source_id="native-intellicenter",
    )

    assert holding.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert completed.status is ThermalLiveExecutionStatus.READY
    assert completed.coordination.current_step_sequence == 2


def test_supersession_after_body_activation_blocks_following_delivery() -> None:
    plan = inactive_body_plan(ThermalBody.POOL)
    engine = ThermalLiveExecutionEngine()
    delivery = FakeThermalDelivery()
    session = engine.begin(
        plan,
        policy=policy(),
        evidence=evidence(
            plan,
            body_active=False,
            hydraulic_safe=True,
            hydraulic=hydraulic_evidence(
                target_body=ThermalBody.POOL,
                pool_active=False,
                spa_active=False,
            ),
        ),
    )
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(
                plan,
                body_active=False,
                hydraulic_safe=True,
                hydraulic=hydraulic_evidence(
                    target_body=ThermalBody.POOL,
                    pool_active=False,
                    spa_active=False,
                ),
            ),
            delivery=delivery,
        )
    )
    assert waiting.ownership.owns_body_activation is True
    ready = engine.verify_current_step(
        waiting,
        store("pool.active", True, at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )
    assert ready.status is ThermalLiveExecutionStatus.READY

    result = asyncio.run(
        engine.deliver_current_step(
            ready,
            policy=policy(),
            evidence=evidence(
                plan,
                at=NOW + timedelta(seconds=2),
                current_evaluation_id="evaluation-2",
                current_plan_id="replacement-plan",
            ),
            delivery=delivery,
        )
    )

    assert result.status is ThermalLiveExecutionStatus.SUPERSEDED
    assert result.ownership.owns_body_activation is False
    assert len(delivery.calls) == 1


def test_preexisting_matching_native_state_never_creates_session_ownership() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )

    first = ThermalLiveExecutionEngine().begin(
        plan,
        policy=policy(),
        evidence=evidence(plan),
    )
    restarted = ThermalLiveExecutionEngine().begin(
        plan,
        policy=policy(),
        evidence=evidence(plan),
    )

    for session in (first, restarted):
        assert session.ownership.owns_body_activation is False
        assert session.ownership.owns_pump_setpoint is False
        assert session.ownership.owns_heat_source is False


@pytest.mark.parametrize(
    ("plan", "attribute", "expected"),
    (
        (
            inactive_body_plan(ThermalBody.POOL),
            "owns_body_activation",
            True,
        ),
        (
            thermal_plan(
                PhysicalHeatMode.OFF,
                2600,
                PhysicalHeatMode.SOLAR,
                2900,
            ),
            "owns_pump_setpoint",
            True,
        ),
        (
            thermal_plan(
                PhysicalHeatMode.OFF,
                2900,
                PhysicalHeatMode.SOLAR,
                2900,
            ),
            "owns_heat_source",
            True,
        ),
    ),
)
def test_accepted_delivery_establishes_only_typed_session_ownership(
    plan: ThermalExecutionPlanAssessment,
    attribute: str,
    expected: bool,
) -> None:
    inactive = isinstance(plan.operations[0], SetBodyActive)
    live_evidence = evidence(
        plan,
        body_active=not inactive,
        hydraulic_safe=True,
        hydraulic=(
            hydraulic_evidence(
                target_body=ThermalBody.POOL,
                pool_active=False,
                spa_active=False,
            )
            if inactive
            else None
        ),
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=live_evidence)

    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=live_evidence,
            delivery=FakeThermalDelivery(),
        )
    )

    assert getattr(waiting.ownership, attribute) is expected
    assert waiting.current_attempt is not None
    operation = waiting.current_attempt.step.operation
    if isinstance(operation, SetPumpSpeed):
        assert waiting.ownership.pump_operation_id == operation.operation_id
        assert waiting.ownership.pump_receipt_id == "receipt-1"
        assert waiting.ownership.pump_correlation_id == waiting.current_attempt.correlation_id
        assert waiting.ownership.commanded_pump_rpm == operation.rpm
    elif isinstance(operation, SetHeatMode):
        assert waiting.ownership.heat_source_operation_id == operation.operation_id
        assert waiting.ownership.heat_source_receipt_id == "receipt-1"
        assert (
            waiting.ownership.heat_source_correlation_id
            == waiting.current_attempt.correlation_id
        )
        assert waiting.ownership.commanded_heat_source is operation.mode
    else:
        assert waiting.ownership.body_activation_operation_id == operation.operation_id
        assert waiting.ownership.body_activation_receipt_id == "receipt-1"
        assert (
            waiting.ownership.body_activation_correlation_id
            == waiting.current_attempt.correlation_id
        )


def test_rejected_delivery_never_establishes_ownership() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))

    result = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(statuses=[CommandStatus.REJECTED]),
        )
    )

    assert result.status is ThermalLiveExecutionStatus.FAILED
    assert result.ownership.owns_pump_setpoint is False


def test_failed_verification_clears_accepted_delivery_ownership() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    assert waiting.ownership.owns_heat_source is True

    failed = engine.verify_current_step(
        waiting,
        hydraulic_store(
            at=NOW + timedelta(seconds=1),
            pool_active=False,
            spa_active=False,
        ),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert failed.status is ThermalLiveExecutionStatus.FAILED
    assert failed.ownership.owns_heat_source is False


def test_completed_session_clears_active_ownership_but_retains_receipt_audit() -> None:
    plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(plan, policy=policy(), evidence=evidence(plan))
    waiting = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=evidence(plan),
            delivery=FakeThermalDelivery(),
        )
    )
    assert waiting.ownership.owns_heat_source is True

    completed = engine.verify_current_step(
        waiting,
        store("pool.raw_heater_id", "H0002", at=NOW + timedelta(seconds=1)),
        current_context=waiting.originating_context,
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )

    assert completed.status is ThermalLiveExecutionStatus.COMPLETED
    assert completed.ownership.owns_heat_source is False
    assert completed.attempts[0].receipt is not None
