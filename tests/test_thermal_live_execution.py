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
from poolos.thermal_live_execution import (
    COMMISSIONED_THERMAL_PUMP_ID,
    ThermalLiveAuthorizationDisposition,
    ThermalLiveAuthorizationEngine,
    ThermalLiveAuthorizationResult,
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionPolicy,
    ThermalLiveExecutionStatus,
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
    configuration: NativeConfigurationInput = NativeConfigurationInput(),
    contradictions: tuple[str, ...] = (),
    interrupted: bool = False,
) -> ThermalLiveSafetyEvidence:
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
        native_configuration=NativeConfigurationGuard().evaluate(configuration),
        contradictory_evidence=contradictions,
        interrupted_execution_present=interrupted,
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


def store(observation_id: str, value: object, *, at: datetime) -> ObservationStore:
    observations = ObservationStore()
    observations.put(
        PoolObservation(
            observation_id=observation_id,
            value=value,
            observed_at=at,
            source_kind=ObservationSourceKind.LIVE,
            source_id="native-intellicenter",
            quality=ObservationQuality.GOOD,
            confidence=1.0,
        )
    )
    return observations


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
    ) -> ThermalLiveAuthorizationResult:
        authorized = super().authorize(
            assessment,
            step_index=step_index,
            policy=policy,
            evidence=evidence,
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
        policy=policy(),
        evaluated_at=NOW + timedelta(seconds=1),
        source_id="native-intellicenter",
    )
    verified = engine.verify_current_step(
        pending,
        store("pump.rpm", 2875, at=NOW + timedelta(seconds=2)),
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
        store("pool.raw_heater_id", "H0002", at=NOW),
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
