from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from poolos.integration import PhysicalHeatMode, SetBodyActive, ThermalBody, SetHeatMode, SetPumpSpeed
from poolos.native_configuration_policy import (
    NativeConfigurationGuard,
    NativeConfigurationInput,
    NativeRpmAssignment,
)
from poolos.thermal_live_execution import (
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionPolicy,
)
from poolos.thermal_runtime_assessment import (
    PoolTemperatureProbePhase,
    ThermalRequestedMode,
    ThermalRuntimeEvaluator,
    ThermalRuntimeEvidence,
    ThermalTechnicalPreflight,
)


NOW = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)


def values(*, pool_active: bool = True, spa_active: bool = False) -> dict[str, object]:
    return {
        "pool.active": pool_active,
        "pool.temperature": 80.0,
        "pool.target_temperature": 90.0,
        "pool.raw_heater_id": "H0002",
        "pool.raw_htmode": "0",
        "spa.active": spa_active,
        "spa.temperature": 96.0,
        "spa.target_temperature": 101.0,
        "spa.raw_heater_id": "00000",
        "spa.raw_htmode": "0",
        "pump.rpm": 2900,
        "solar.temperature": 110.0,
        "solar.active": False,
    }


def evidence(
    *,
    at: datetime = NOW,
    native_values: dict[str, object] | None = None,
    pool_mode: ThermalRequestedMode = ThermalRequestedMode.GAS,
    spa_mode: ThermalRequestedMode = ThermalRequestedMode.SOLAR_PREFERRED,
    health: bool = True,
    native_available: bool = True,
    manual_available: bool = True,
    stale: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    configuration: NativeConfigurationInput = NativeConfigurationInput(),
    filtration_debt: timedelta | None = None,
    pending: bool = False,
    confirmed: bool = False,
    observed_at: dict[str, datetime] | None = None,
) -> ThermalRuntimeEvidence:
    return ThermalRuntimeEvidence(
        evaluated_at=at,
        native_values=values() if native_values is None else native_values,
        native_observed_at={} if observed_at is None else observed_at,
        pool_requested_mode=pool_mode,
        hot_tub_requested_mode=spa_mode,
        native_transport_available=native_available,
        manual_transport_available=manual_available,
        immediate_observation_healthy=health,
        stale_native_concepts=stale,
        missing_native_concepts=missing,
        native_configuration=NativeConfigurationGuard().evaluate(configuration),
        filtration_debt=filtration_debt,
        pending_durable_incident_confirmation=pending,
        durable_incident_confirmed=confirmed,
    )


def disabled_policy() -> ThermalLiveExecutionPolicy:
    return ThermalLiveExecutionPolicy()


def pool_policy(*, enabled: bool = True) -> ThermalLiveExecutionPolicy:
    return ThermalLiveExecutionPolicy(
        thermal_live_execution_enabled=enabled,
        commissioning_scope=ThermalLiveCommissioningScope.POOL,
    )


def test_disabled_operator_gates_do_not_hide_technical_preflight() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(), live_policy=disabled_policy()
    )

    assert not result.pool.actual_authorization.authorized
    assert "thermal_live_kill_switch_disabled" in (
        result.pool.actual_authorization.blocking_reasons
    )
    assert "thermal_live_commissioning_scope_disabled" in (
        result.pool.actual_authorization.blocking_reasons
    )
    assert result.pool.technical_preflight.ready
    assert isinstance(result.pool.technical_preflight, ThermalTechnicalPreflight)
    assert result.pool.technical_preflight.authorizing is False
    assert result.pool.technical_preflight.command_delivery_enabled is False
    assert not hasattr(result.pool.technical_preflight, "operation_id")


def test_pool_scope_and_hot_tub_scope_remain_one_body_only() -> None:
    evaluator = ThermalRuntimeEvaluator()
    pool = evaluator.evaluate(evidence(), live_policy=pool_policy())
    hot_values = values(pool_active=False, spa_active=True)
    hot = ThermalRuntimeEvaluator().evaluate(
        evidence(native_values=hot_values, spa_mode=ThermalRequestedMode.GAS),
        live_policy=ThermalLiveExecutionPolicy(
            thermal_live_execution_enabled=True,
            commissioning_scope=ThermalLiveCommissioningScope.HOT_TUB,
        ),
    )

    assert pool.pool.actual_authorization.authorized
    assert not pool.hot_tub.actual_authorization.authorized
    assert hot.hot_tub.actual_authorization.authorized
    assert not hot.pool.actual_authorization.authorized


def test_first_immediate_unhealthy_evaluation_blocks_before_durable_confirmation() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(health=False, pending=True, confirmed=False),
        live_policy=pool_policy(),
    )

    assert not result.pool.actual_authorization.authorized
    assert not result.pool.technical_preflight.ready
    assert "observation_health_unacceptable" in (
        result.pool.actual_authorization.blocking_reasons
    )
    assert result.pending_durable_incident_confirmation
    assert not result.durable_incident_confirmed


def test_missing_stale_and_manual_unavailable_each_fail_closed() -> None:
    cases = (
        evidence(missing=("pump.rpm",)),
        evidence(stale=("pump.rpm",)),
        evidence(manual_available=False),
    )

    results = tuple(
        ThermalRuntimeEvaluator().evaluate(item, live_policy=pool_policy()).pool
        for item in cases
    )

    assert all(not item.actual_authorization.authorized for item in results)
    assert all(not item.technical_preflight.ready for item in results)
    assert "authoritative_observations_not_fresh" in results[0].technical_preflight.blocking_reasons
    assert "authoritative_observations_not_fresh" in results[1].technical_preflight.blocking_reasons
    assert "physical_delivery_transport_unavailable" in results[2].technical_preflight.blocking_reasons


def test_relevant_gas_conflict_blocks_but_spillway_conflict_is_diagnostic_only() -> None:
    gas_conflict = evidence(
        configuration=NativeConfigurationInput(
            rpm_assignments=(NativeRpmAssignment("Spa Heater", 3000),)
        )
    )
    spillway = evidence(
        configuration=NativeConfigurationInput(
            rpm_assignments=(NativeRpmAssignment("Spillway", 2900),)
        )
    )

    blocked = ThermalRuntimeEvaluator().evaluate(
        gas_conflict, live_policy=pool_policy()
    )
    visible = ThermalRuntimeEvaluator().evaluate(spillway, live_policy=pool_policy())

    assert not blocked.pool.technical_preflight.ready
    assert any(
        reason.startswith("native_configuration_conflict:")
        for reason in blocked.pool.technical_preflight.blocking_reasons
    )
    assert visible.pool.technical_preflight.ready
    assert "native_rpm_assignment_conflict" in visible.native_conflict_codes


def test_solar_qualification_reuses_policy_and_exposes_why() -> None:
    evaluator = ThermalRuntimeEvaluator()
    first = evidence(pool_mode=ThermalRequestedMode.SOLAR)
    evaluator.evaluate(first, live_policy=disabled_policy())
    qualified = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(minutes=10),
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    diagnostics = dict(qualified.pool.diagnostics())
    assert diagnostics["requested_mode"] == "Solar"
    assert diagnostics["planned_source"] == "solar"
    assert diagnostics["planned_rpm"] == 2900
    assert diagnostics["source_reason_code"] == "solar_only_selected"
    assert diagnostics["rpm_reason_code"]
    assert diagnostics["plan_id"]
    assert diagnostics["evaluation_id"]


def test_requested_planned_and_effective_states_remain_distinct() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(pool_mode=ThermalRequestedMode.GAS),
        live_policy=disabled_policy(),
    )
    diagnostics = dict(result.pool.diagnostics())

    assert diagnostics["requested_mode"] == "Gas"
    assert diagnostics["planned_source"] == "gas"
    assert diagnostics["effective_native_heater_id"] == "H0002"
    assert diagnostics["planned_rpm"] == 3000
    assert diagnostics["actual_pump_rpm"] == 2900


def test_new_diagnostic_payloads_are_bounded_below_eight_kibibytes() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(), live_policy=disabled_policy()
    )
    payloads = (
        result.global_diagnostics(),
        result.pool.diagnostics(),
        result.hot_tub.diagnostics(),
    )

    assert max(
        len(json.dumps(dict(payload), sort_keys=True, default=str).encode())
        for payload in payloads
    ) < 8192


def test_phase_three_module_has_no_execution_or_delivery_driver() -> None:
    import poolos.thermal_runtime_assessment as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "ThermalLiveExecutionEngine" not in source
    assert "deliver_current_step" not in source
    assert ".begin(" not in source
    assert "ManualIntelliCenter" not in source


def live_values(
    *,
    pool_active: bool,
    pool_heater: str,
    pump_rpm: int,
    solar_temperature: float = 67.0,
    solar_active: bool = False,
    spa_active: bool = False,
    spa_heater: str = "H0001",
) -> dict[str, object]:
    return {
        "pool.active": pool_active,
        "pool.temperature": 86.0,
        "pool.target_temperature": 90.0,
        "pool.raw_heater_id": pool_heater,
        "pool.raw_htmode": "0",
        "spa.active": spa_active,
        "spa.temperature": 98.0,
        "spa.target_temperature": 97.0,
        "spa.raw_heater_id": spa_heater,
        "spa.raw_htmode": "0",
        "pump.rpm": pump_rpm,
        "solar.temperature": solar_temperature,
        "solar.active": solar_active,
    }


def test_live_cold_roof_inactive_pool_produces_valid_off_assessment() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=False,
                pool_heater="H0002",
                pump_rpm=0,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    assert result.pool.plan.desired.selected_source is PhysicalHeatMode.OFF
    assert result.pool.plan.desired.required_pump_rpm is None
    assert result.pool.plan.desired.reason_code == "solar_only_not_selected"


def test_live_cold_roof_active_filtration_rpm_requests_source_off_only() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="H0002",
                pump_rpm=2600,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )
    plan = result.pool.plan

    assert plan.desired.selected_source is PhysicalHeatMode.OFF
    assert plan.desired.required_pump_rpm is None
    assert len(plan.operations) == 1
    assert isinstance(plan.operations[0], SetHeatMode)
    assert plan.operations[0].mode is PhysicalHeatMode.OFF
    assert not any(isinstance(operation, SetPumpSpeed) for operation in plan.operations)
    assert plan.current.pump_rpm == 2600


def test_live_solar_and_gas_plans_retain_thermal_rpm_and_ordering() -> None:
    solar = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="00000",
                pump_rpm=2600,
                solar_temperature=100.0,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    ).pool.plan
    gas = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="H0002",
                pump_rpm=2600,
            ),
            pool_mode=ThermalRequestedMode.GAS,
        ),
        live_policy=disabled_policy(),
    ).pool.plan

    assert solar.desired.selected_source is PhysicalHeatMode.SOLAR
    assert solar.desired.required_pump_rpm == 2900
    assert [type(operation) for operation in solar.operations] == [
        SetPumpSpeed,
        SetHeatMode,
    ]
    assert gas.desired.selected_source is PhysicalHeatMode.GAS
    assert gas.desired.required_pump_rpm == 3000
    assert [type(operation) for operation in gas.operations] == [
        SetPumpSpeed,
        SetHeatMode,
    ]


def test_live_already_off_preserves_nonthermal_rpm_without_operations() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="00000",
                pump_rpm=2600,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    ).pool.plan

    assert result.desired.selected_source is PhysicalHeatMode.OFF
    assert result.desired.required_pump_rpm is None
    assert result.operations == ()
    assert result.current.pump_rpm == 2600


def test_live_hot_tub_gas_behavior_remains_unchanged() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=False,
                pool_heater="00000",
                pump_rpm=3000,
                spa_active=True,
                spa_heater="H0001",
            ),
            spa_mode=ThermalRequestedMode.GAS,
        ),
        live_policy=disabled_policy(),
    ).hot_tub.plan

    assert result.desired.selected_source is PhysicalHeatMode.GAS
    assert result.desired.required_pump_rpm == 3000
    assert result.operations == ()


def test_stateful_evaluator_rejects_timestamp_regression_with_exact_reason() -> None:
    evaluator = ThermalRuntimeEvaluator()
    native = live_values(
        pool_active=True,
        pool_heater="H0002",
        pump_rpm=2600,
    )
    evaluator.evaluate(
        evidence(
            at=NOW + timedelta(seconds=1),
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    with pytest.raises(
        ValueError,
        match="solar eligibility observations must be chronological",
    ):
        evaluator.evaluate(
            evidence(
                at=NOW,
                native_values=native,
                pool_mode=ThermalRequestedMode.SOLAR,
            ),
            live_policy=disabled_policy(),
        )


def test_authoritative_filtration_debt_blocks_opportunistic_spa_policy() -> None:
    native = live_values(
        pool_active=True,
        pool_heater="00000",
        pump_rpm=2600,
        solar_temperature=140.0,
    )
    native["pool.temperature"] = 90.0
    native["spa.temperature"] = 90.0
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(native_values=native, filtration_debt=timedelta(hours=1)),
        live_policy=disabled_policy(),
    )

    assert result.hot_tub.plan.desired.reason_code == "opportunistic_ineligible"
    assert result.hot_tub.plan.desired.selected_source is PhysicalHeatMode.OFF


def test_opportunistic_spa_policy_remains_blocked_when_body_is_inactive() -> None:
    native = live_values(
        pool_active=True,
        pool_heater="00000",
        pump_rpm=2600,
        solar_temperature=140.0,
    )
    native["pool.temperature"] = 90.0
    native["spa.temperature"] = 90.0
    evaluator = ThermalRuntimeEvaluator()
    evaluator.evaluate(
        evidence(native_values=native, filtration_debt=timedelta(0)),
        live_policy=disabled_policy(),
    )
    result = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(minutes=2),
            native_values=native,
            filtration_debt=timedelta(0),
        ),
        live_policy=disabled_policy(),
    )

    assert (
        result.hot_tub.plan.desired.reason_code
        == "opportunistic_started_or_resumed"
    )
    assert result.hot_tub.plan.desired.selected_source is PhysicalHeatMode.SOLAR

    # An inactive body is no longer a terminal technical blocker because
    # the plan now contains an explicit, verified body-activation first step.
    assert result.hot_tub.technical_preflight.ready is True
    assert result.hot_tub.technical_preflight.blocking_reasons == ()
    assert isinstance(result.hot_tub.plan.operations[0], SetBodyActive)
    assert result.hot_tub.plan.operations[0].equipment_id == ThermalBody.HOT_TUB.value
    assert result.hot_tub.plan.operations[0].active is True

    # Operator/live authority remains independently gated.
    assert result.hot_tub.actual_authorization.authorized is False
    assert (
        "thermal_live_kill_switch_disabled"
        in result.hot_tub.actual_authorization.blocking_reasons
    )


def test_idle_solar_pool_requests_temperature_probe_before_source_selection() -> None:
    native = values(pool_active=False)
    native["pool.raw_heater_id"] = "00000"
    native["pump.rpm"] = 0
    native["pool.temperature"] = 98.0
    native["pool.target_temperature"] = 90.0
    native["solar.temperature"] = 110.0
    native["solar.active"] = False

    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    plan = result.pool.plan

    assert plan.desired.reason_code == "pool_temperature_probe_required"
    assert plan.desired.selected_source is PhysicalHeatMode.OFF
    assert plan.desired.required_pump_rpm == 1500
    assert plan.desired.evidence["pool_temperature_f"] is None
    assert [type(operation) for operation in plan.operations] == [
        SetBodyActive,
        SetPumpSpeed,
        SetPumpSpeed,
    ]
    assert plan.operations[1].rpm == 3000
    assert plan.operations[2].rpm == 1500
    assert "required_pool_thermal_evidence_unavailable" not in (
        plan.blocking_reasons
    )


def test_missing_pool_temperature_is_acquirable_not_fatal_when_probe_required() -> None:
    native = values(pool_active=False)
    native["pool.raw_heater_id"] = "00000"
    native["pump.rpm"] = 0
    native["solar.temperature"] = 110.0

    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            missing=("pool.temperature",),
        ),
        live_policy=disabled_policy(),
    )

    plan = result.pool.plan

    assert plan.desired.reason_code == "pool_temperature_probe_required"
    assert plan.desired.required_pump_rpm == 1500
    assert "missing_native:pool.temperature" not in plan.blocking_reasons
    assert plan.disposition.value == "ready"


def test_recent_circulating_temperature_is_reused_without_reprobe() -> None:
    evaluator = ThermalRuntimeEvaluator()

    circulating = values(pool_active=True)
    circulating["pool.raw_heater_id"] = "00000"
    circulating["pump.rpm"] = 2600
    circulating["pool.temperature"] = 84.0
    circulating["pool.target_temperature"] = 90.0
    circulating["solar.temperature"] = 110.0

    evaluator.evaluate(
        evidence(
            at=NOW,
            native_values=circulating,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    idle = dict(circulating)
    idle["pool.active"] = False
    idle["pump.rpm"] = 0
    idle["pool.temperature"] = 99.0

    result = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(minutes=10),
            native_values=idle,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    assert result.pool.plan.desired.reason_code != "pool_temperature_probe_required"
    assert result.pool.plan.desired.evidence["pool_temperature_f"] == 84.0


def test_reused_pool_temperature_expires_and_idle_pipe_value_is_not_trusted() -> None:
    evaluator = ThermalRuntimeEvaluator()

    circulating = values(pool_active=True)
    circulating["pool.raw_heater_id"] = "00000"
    circulating["pump.rpm"] = 2600
    circulating["pool.temperature"] = 84.0
    circulating["pool.target_temperature"] = 90.0
    circulating["solar.temperature"] = 110.0

    evaluator.evaluate(
        evidence(
            at=NOW,
            native_values=circulating,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    idle = dict(circulating)
    idle["pool.active"] = False
    idle["pump.rpm"] = 0
    idle["pool.temperature"] = 99.0

    result = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(minutes=31),
            native_values=idle,
            pool_mode=ThermalRequestedMode.SOLAR,
        ),
        live_policy=disabled_policy(),
    )

    assert result.pool.plan.desired.reason_code == "pool_temperature_probe_required"
    assert result.pool.plan.desired.evidence["pool_temperature_f"] is None
    assert result.pool.plan.desired.required_pump_rpm == 1500


def _probe_values(
    *,
    active: bool,
    rpm: int,
    temperature: float = 98.0,
    spa_active: bool = False,
) -> dict[str, object]:
    native = values(pool_active=active, spa_active=spa_active)
    native["pool.raw_heater_id"] = "00000"
    native["pump.rpm"] = rpm
    native["pool.temperature"] = temperature
    native["pool.target_temperature"] = 90.0
    native["solar.temperature"] = 110.0
    native["solar.active"] = False
    return native


def _evaluate_probe(
    evaluator: ThermalRuntimeEvaluator,
    *,
    at: datetime,
    active: bool,
    rpm: int,
    temperature: float = 98.0,
    spa_active: bool = False,
    stale: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
) -> object:
    return evaluator.evaluate(
        evidence(
            at=at,
            native_values=_probe_values(
                active=active,
                rpm=rpm,
                temperature=temperature,
                spa_active=spa_active,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": at},
            stale=stale,
            missing=missing,
        ),
        live_policy=disabled_policy(),
    )


def test_probe_requirement_creates_explicit_runtime_ownership() -> None:
    evaluator = ThermalRuntimeEvaluator()

    result = _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)

    assert result.pool.plan.desired.reason_code == "pool_temperature_probe_required"
    assert evaluator.pool_temperature_probe.owned
    assert (
        evaluator.pool_temperature_probe.phase
        is PoolTemperatureProbePhase.PROBE_REQUIRED
    )
    assert evaluator.pool_temperature_probe.requested_at == NOW
    assert evaluator.pool_temperature_probe.started_at is None


@pytest.mark.parametrize("first_rpm", (1500, 3000))
def test_probe_owned_circulation_cannot_immediately_trust_pipe_temperature(
    first_rpm: int,
) -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)

    result = _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=30),
        active=True,
        rpm=first_rpm,
        temperature=98.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == NOW + timedelta(seconds=30)
    assert probe.last_assessment is not None
    assert probe.last_assessment.disposition.value == "probing"
    assert probe.last_assessment.reason_code == "probe_minimum_duration"
    assert probe.last_assessment.trusted_temperature_f is None
    assert result.pool.plan.desired.evidence["pool_temperature_f"] is None
    assert result.pool.plan.desired.required_pump_rpm == 1500


def test_probe_remains_probing_before_two_minutes_and_bounds_samples() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=30),
        active=True,
        rpm=3000,
        temperature=98.0,
    )

    for seconds in range(31, 150):
        _evaluate_probe(
            evaluator,
            at=NOW + timedelta(seconds=seconds),
            active=True,
            rpm=1500,
            temperature=98.0 - (seconds - 30) / 120,
        )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.last_assessment is not None
    assert probe.last_assessment.trusted_temperature_f is None
    assert len(probe.samples) == probe.sample_limit == 64


def test_probe_samples_use_authoritative_observation_time_and_ignore_duplicates() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(
        evaluator,
        at=started,
        active=True,
        rpm=1500,
        temperature=98.0,
    )

    observed_at = started + timedelta(seconds=15)
    native = _probe_values(active=True, rpm=1500, temperature=90.0)
    evaluator.evaluate(
        evidence(
            at=started + timedelta(seconds=30),
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": observed_at},
        ),
        live_policy=disabled_policy(),
    )
    evaluator.evaluate(
        evidence(
            at=started + timedelta(seconds=45),
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": observed_at},
        ),
        live_policy=disabled_policy(),
    )

    assert evaluator.pool_temperature_probe.samples[-1].observed_at == observed_at
    assert sum(
        sample.observed_at == observed_at
        for sample in evaluator.pool_temperature_probe.samples
    ) == 1


def test_pool_stop_discards_probe_epoch_and_requires_fresh_acquisition() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    first_started = NOW + timedelta(seconds=30)
    _evaluate_probe(
        evaluator,
        at=first_started,
        active=True,
        rpm=1500,
        temperature=90.0,
    )
    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(seconds=60),
        active=True,
        rpm=1500,
        temperature=89.5,
    )

    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(seconds=70),
        active=False,
        rpm=0,
        temperature=99.0,
    )

    interrupted = evaluator.pool_temperature_probe
    assert interrupted.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert interrupted.started_at is None
    assert interrupted.samples == ()

    second_started = first_started + timedelta(seconds=75)
    resumed = _evaluate_probe(
        evaluator,
        at=second_started,
        active=True,
        rpm=1500,
        temperature=89.0,
    )

    assert interrupted.phase is PoolTemperatureProbePhase.PROBING
    assert interrupted.started_at == second_started
    assert [sample.temperature_f for sample in interrupted.samples] == [89.0]
    assert interrupted.last_assessment is not None
    assert interrupted.last_assessment.trusted_temperature_f is None
    assert resumed.pool.plan.desired.evidence["pool_temperature_f"] is None


def test_old_samples_cannot_bridge_a_short_probe_interruption() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    first_started = NOW + timedelta(seconds=30)
    _evaluate_probe(
        evaluator,
        at=first_started,
        active=True,
        rpm=1500,
        temperature=90.0,
    )
    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(seconds=60),
        active=True,
        rpm=1500,
        temperature=89.5,
    )
    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(seconds=65),
        active=False,
        rpm=0,
    )

    second_started = first_started + timedelta(seconds=70)
    result = _evaluate_probe(
        evaluator,
        at=second_started,
        active=True,
        rpm=1500,
        temperature=89.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == second_started
    assert tuple(sample.observed_at for sample in probe.samples) == (second_started,)
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "probe_minimum_duration"
    assert result.pool.plan.desired.evidence["pool_temperature_f"] is None


def test_zero_rpm_invalidates_probe_even_while_pool_remains_active() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500)

    _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=30),
        active=True,
        rpm=0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.started_at is None
    assert probe.samples == ()


def test_spa_takeover_invalidates_pool_probe_epoch() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500)

    result = _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=30),
        active=False,
        spa_active=True,
        rpm=3000,
        temperature=101.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.started_at is None
    assert probe.samples == ()
    assert probe.last_assessment is not None
    assert probe.last_assessment.trusted_temperature_f is None
    assert result.pool.plan.desired.evidence["pool_temperature_f"] is None


def test_simultaneous_pool_and_spa_activity_invalidates_pool_probe_epoch() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500)

    _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=30),
        active=True,
        spa_active=True,
        rpm=3000,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.started_at is None
    assert probe.samples == ()


@pytest.mark.parametrize("concept", ("pool.active", "spa.active", "pump.rpm"))
@pytest.mark.parametrize("qualification", ("missing", "stale"))
def test_unusable_hydraulic_evidence_invalidates_pool_probe_epoch(
    concept: str,
    qualification: str,
) -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500)

    unusable = (concept,)
    _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=30),
        active=True,
        rpm=1500,
        missing=unusable if qualification == "missing" else (),
        stale=unusable if qualification == "stale" else (),
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.started_at is None
    assert probe.samples == ()


def test_probe_maximum_duration_restarts_with_fresh_continuous_epoch() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    first_started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=first_started, active=True, rpm=1500)
    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(minutes=4, seconds=50),
        active=True,
        rpm=1500,
        temperature=94.0,
    )
    _evaluate_probe(
        evaluator,
        at=first_started + timedelta(minutes=4, seconds=55),
        active=False,
        rpm=0,
    )

    second_started = first_started + timedelta(minutes=5, seconds=5)
    _evaluate_probe(
        evaluator,
        at=second_started,
        active=True,
        rpm=1500,
        temperature=90.0,
    )
    before_new_maximum = _evaluate_probe(
        evaluator,
        at=second_started + timedelta(minutes=4, seconds=59),
        active=True,
        rpm=1500,
        temperature=85.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == second_started
    assert probe.last_assessment is not None
    assert probe.last_assessment.disposition.value == "probing"
    assert before_new_maximum.pool.plan.desired.evidence["pool_temperature_f"] is None

    _evaluate_probe(
        evaluator,
        at=second_started + timedelta(minutes=5),
        active=True,
        rpm=1500,
        temperature=84.0,
    )
    assert probe.phase is PoolTemperatureProbePhase.ACQUISITION_FAILED


def test_probe_succeeds_only_after_minimum_duration_and_stable_window() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=30),
        active=True,
        rpm=3000,
        temperature=98.0,
    )
    _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=90),
        active=True,
        rpm=1500,
        temperature=87.0,
    )
    _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=120),
        active=True,
        rpm=1500,
        temperature=86.5,
    )

    result = _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=150),
        active=True,
        rpm=1500,
        temperature=86.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.TRUSTED
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "probe_settled"
    assert probe.last_assessment.trusted_temperature_f == 86.0
    assert result.pool.plan.desired.evidence["pool_temperature_f"] == 86.0


def test_probe_transients_never_become_trusted_and_fail_closed_at_five_minutes() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(
        evaluator,
        at=started,
        active=True,
        rpm=3000,
        temperature=98.0,
    )
    for elapsed_seconds, temperature in (
        (60, 94.0),
        (120, 88.0),
        (180, 93.0),
        (240, 86.0),
    ):
        result = _evaluate_probe(
            evaluator,
            at=started + timedelta(seconds=elapsed_seconds),
            active=True,
            rpm=1500,
            temperature=temperature,
        )
        assert (
            evaluator.pool_temperature_probe.phase
            is PoolTemperatureProbePhase.PROBING
        )
        assert result.pool.plan.desired.evidence["pool_temperature_f"] is None

    failed = _evaluate_probe(
        evaluator,
        at=started + timedelta(minutes=5),
        active=True,
        rpm=1500,
        temperature=89.0,
    )
    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.ACQUISITION_FAILED
    assert probe.last_assessment is not None
    assert probe.last_assessment.disposition.value == "acquisition_failed"
    assert probe.last_assessment.trusted_temperature_f is None
    assert failed.pool.plan.desired.required_pump_rpm is None

    _evaluate_probe(
        evaluator,
        at=started + timedelta(minutes=5, seconds=30),
        active=True,
        rpm=1500,
        temperature=89.0,
    )
    assert (
        evaluator.pool_temperature_probe.phase
        is PoolTemperatureProbePhase.ACQUISITION_FAILED
    )


def test_successful_probe_temperature_is_reused_for_thirty_minutes() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    for elapsed_seconds, temperature in ((0, 87.0), (60, 86.5), (120, 86.0)):
        _evaluate_probe(
            evaluator,
            at=started + timedelta(seconds=elapsed_seconds),
            active=True,
            rpm=1500,
            temperature=temperature,
        )

    idle = _evaluate_probe(
        evaluator,
        at=started + timedelta(minutes=10),
        active=False,
        rpm=0,
        temperature=99.0,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.last_assessment is not None
    assert probe.last_assessment.disposition.value == "reused"
    assert probe.last_assessment.trusted_temperature_f == 86.0
    assert idle.pool.plan.desired.evidence["pool_temperature_f"] == 86.0


def test_preexisting_circulation_still_trusts_temperature_without_probe_ownership() -> None:
    evaluator = ThermalRuntimeEvaluator()

    result = _evaluate_probe(
        evaluator,
        at=NOW,
        active=True,
        rpm=2600,
        temperature=84.0,
    )

    probe = evaluator.pool_temperature_probe
    assert not probe.owned
    assert probe.phase is PoolTemperatureProbePhase.IDLE
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "existing_circulation"
    assert probe.last_assessment.trusted_temperature_f == 84.0
    assert result.pool.plan.desired.evidence["pool_temperature_f"] == 84.0


def test_gas_only_mode_does_not_create_temperature_probe_lifecycle() -> None:
    evaluator = ThermalRuntimeEvaluator()

    evaluator.evaluate(
        evidence(
            at=NOW,
            native_values=_probe_values(active=False, rpm=0),
            pool_mode=ThermalRequestedMode.GAS,
        ),
        live_policy=disabled_policy(),
    )

    assert evaluator.pool_temperature_probe.phase is PoolTemperatureProbePhase.IDLE
    assert not evaluator.pool_temperature_probe.owned


def test_probe_does_not_synthesize_sample_timestamp_when_authoritative_time_missing() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)

    started = NOW + timedelta(seconds=30)
    _evaluate_probe(
        evaluator,
        at=started,
        active=True,
        rpm=1500,
        temperature=98.0,
    )

    sample_count = len(evaluator.pool_temperature_probe.samples)

    evaluator.evaluate(
        evidence(
            at=started + timedelta(seconds=30),
            native_values=_probe_values(
                active=True,
                rpm=1500,
                temperature=90.0,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={},
        ),
        live_policy=disabled_policy(),
    )

    probe = evaluator.pool_temperature_probe

    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert len(probe.samples) == sample_count
    assert all(
        sample.observed_at != started + timedelta(seconds=30)
        for sample in probe.samples
    )
