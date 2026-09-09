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
from poolos.pool_temperature_probe_execution import (
    PoolTemperatureProbeContinuityEvidence,
    PoolTemperatureProbeExecutionEvidence,
    PoolTemperatureProbeExecutionPhase,
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
from poolos.spa_temperature_policy import (
    SpaTemperatureDisposition,
    SpaTemperatureEvidence,
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
        "pool.pump_circuit.configured_speed_rpm": 2900,
        "spa.pump_circuit.configured_speed_rpm": 2600,
        "solar.temperature": 110.0,
        "solar.active": False,
        "heater.active": False,
        "pool.heating_demand_active": False,
        "spa.heating_demand_active": False,
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
    filtration_immediate_circulation_required: bool | None = None,
    pending: bool = False,
    confirmed: bool = False,
    observed_at: dict[str, datetime] | None = None,
    probe_execution: PoolTemperatureProbeExecutionEvidence | None = None,
    probe_continuity: PoolTemperatureProbeContinuityEvidence | None = None,
    trusted_spa: bool = True,
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
        pool_pump_circuit_id="p0102",
        spa_pump_circuit_id="p0198",
        filtration_debt=filtration_debt,
        filtration_immediate_circulation_required=(
            filtration_immediate_circulation_required
        ),
        pending_durable_incident_confirmation=pending,
        durable_incident_confirmed=confirmed,
        pool_temperature_probe_execution=probe_execution,
        pool_temperature_probe_continuity=(
            probe_continuity
            if probe_continuity is not None
            else (
                PoolTemperatureProbeContinuityEvidence(
                    evaluated_at=at,
                    valid=True,
                )
                if probe_execution is not None
                and probe_execution.phase
                is PoolTemperatureProbeExecutionPhase.ACQUIRING
                else None
            )
        ),
        spa_temperature_evidence=(
            SpaTemperatureEvidence(
                evaluated_at=at,
                disposition=SpaTemperatureDisposition.TRUSTED,
                trusted_temperature_f=float(
                    (values() if native_values is None else native_values)[
                        "spa.temperature"
                    ]
                ),
                trusted_at=at,
                acquisition_generation=1,
            )
            if trusted_spa
            else None
        ),
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


def test_runtime_exposes_stable_execution_purpose_across_fresh_epochs() -> None:
    evaluator = ThermalRuntimeEvaluator()
    first = evaluator.evaluate(evidence(), live_policy=disabled_policy())
    second = evaluator.evaluate(
        evidence(at=NOW + timedelta(seconds=1)),
        live_policy=disabled_policy(),
    )

    assert first.pool.evaluation_id != second.pool.evaluation_id
    assert first.pool.plan.plan_id != second.pool.plan.plan_id
    assert (
        first.pool.execution_currentness.purpose
        == second.pool.execution_currentness.purpose
    )
    assert (
        second.pool.diagnostics()["execution_purpose_id"]
        == second.pool.execution_currentness.purpose.purpose_id
    )


def test_runtime_execution_purpose_changes_with_target_temperature() -> None:
    first_values = values()
    second_values = values()
    second_values["pool.target_temperature"] = 91.0
    first = ThermalRuntimeEvaluator().evaluate(
        evidence(native_values=first_values),
        live_policy=disabled_policy(),
    )
    second = ThermalRuntimeEvaluator().evaluate(
        evidence(native_values=second_values),
        live_policy=disabled_policy(),
    )

    assert (
        first.pool.execution_currentness.purpose.purpose_id
        != second.pool.execution_currentness.purpose.purpose_id
    )


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
    assert result.pool.plan.desired.evidence["solar_configured"] is True


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
    heater_active: bool = False,
    spa_heating_demand_active: bool = False,
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
        "pool.pump_circuit.configured_speed_rpm": pump_rpm,
        "spa.pump_circuit.configured_speed_rpm": pump_rpm,
        "solar.temperature": solar_temperature,
        "solar.active": solar_active,
        "heater.active": heater_active,
        "pool.heating_demand_active": False,
        "spa.heating_demand_active": spa_heating_demand_active,
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
            filtration_immediate_circulation_required=True,
        ),
        live_policy=disabled_policy(),
    )
    plan = result.pool.plan

    assert plan.desired.selected_source is PhysicalHeatMode.OFF
    assert plan.desired.required_pump_rpm == 2600
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
            filtration_immediate_circulation_required=True,
        ),
        live_policy=disabled_policy(),
    ).pool.plan

    assert result.desired.selected_source is PhysicalHeatMode.OFF
    assert result.desired.required_pump_rpm == 2600
    assert result.operations == ()
    assert result.current.pump_rpm == 2600


def test_urgent_filtration_normalizes_live_pool_with_stale_solar_speed() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="00000",
                pump_rpm=2900,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
            filtration_immediate_circulation_required=True,
        ),
        live_policy=disabled_policy(),
    ).pool.plan

    assert result.desired.reason_code == "active_pool_session_operating_purpose"
    assert result.desired.evidence["active_operating_purpose"] == (
        "ordinary_circulation"
    )
    assert len(result.operations) == 1
    assert isinstance(result.operations[0], SetPumpSpeed)
    assert result.operations[0].rpm == 2600
    assert result.operations[0].metadata["operating_purpose"] == (
        "ordinary_circulation"
    )


def test_deferrable_filtration_debt_does_not_become_desired_pool_successor() -> None:
    """Current ordinary circulation is not proof that filtration is due now."""

    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=True,
                pool_heater="00000",
                pump_rpm=2900,
            ),
            pool_mode=ThermalRequestedMode.SOLAR,
            filtration_debt=timedelta(hours=5),
            filtration_immediate_circulation_required=False,
        ),
        live_policy=disabled_policy(),
    ).pool.plan

    assert result.desired.selected_source is PhysicalHeatMode.OFF
    assert result.desired.required_pump_rpm is None
    assert result.desired.evidence["current_operating_purpose"] == (
        "ordinary_circulation"
    )
    assert result.desired.evidence["active_operating_purpose"] is None
    assert result.operations == ()


def test_live_hot_tub_gas_behavior_remains_unchanged() -> None:
    result = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=live_values(
                pool_active=False,
                pool_heater="00000",
                pump_rpm=3000,
                spa_active=True,
                spa_heater="H0001",
                heater_active=True,
                spa_heating_demand_active=True,
            ),
            spa_mode=ThermalRequestedMode.GAS,
        ),
        live_policy=disabled_policy(),
    ).hot_tub.plan

    assert result.desired.selected_source is PhysicalHeatMode.GAS
    assert result.desired.required_pump_rpm == 3000
    assert result.operations == ()


@pytest.mark.parametrize(
    ("spa_heater", "solar_active", "heater_active", "expected_rpm"),
    (
        ("H0001", False, True, 3000),
        ("H0002", True, False, 2900),
        ("H0001", False, False, 2600),
        ("H0002", False, False, 2600),
    ),
)
def test_external_hot_tub_rpm_tracks_actual_heat_delivery(
    spa_heater: str,
    solar_active: bool,
    heater_active: bool,
    expected_rpm: int,
) -> None:
    evaluator = ThermalRuntimeEvaluator()
    native = live_values(
        pool_active=False,
        pool_heater="00000",
        pump_rpm=2816,
        spa_active=True,
        spa_heater=spa_heater,
        heater_active=heater_active,
        spa_heating_demand_active=heater_active,
        solar_temperature=140.0,
    )
    native["solar.active"] = solar_active
    native["spa.temperature"] = 80.0
    native["spa.target_temperature"] = 97.0
    mode = (
        ThermalRequestedMode.SOLAR_PREFERRED
        if spa_heater == "H0002"
        else ThermalRequestedMode.GAS
    )
    if spa_heater == "H0002" and not solar_active:
        evaluator.evaluate(
            evidence(
                native_values=native,
                spa_mode=mode,
            ),
            live_policy=disabled_policy(),
        )

    plan = evaluator.evaluate(
        evidence(
            at=(
                NOW + timedelta(minutes=2)
                if spa_heater == "H0002" and not solar_active
                else NOW
            ),
            native_values=native,
            spa_mode=mode,
        ),
        live_policy=disabled_policy(),
    ).hot_tub.plan

    assert plan.desired.required_pump_rpm == expected_rpm
    assert plan.desired.evidence["active_operating_purpose"] == {
        3000: "gas_heating",
        2900: "solar_heating",
        2600: "ordinary_circulation",
    }[expected_rpm]


def test_external_hot_tub_actual_source_transitions_drive_rpm_contract() -> None:
    evaluator = ThermalRuntimeEvaluator()

    def required_rpm(
        offset: int,
        *,
        spa_heater: str,
        heater_active: bool,
        solar_active: bool,
        mode: ThermalRequestedMode,
    ) -> int | None:
        native = live_values(
            pool_active=False,
            pool_heater="00000",
            pump_rpm=2600,
            spa_active=True,
            spa_heater=spa_heater,
            heater_active=heater_active,
            spa_heating_demand_active=heater_active,
            solar_temperature=140.0,
        )
        native["solar.active"] = solar_active
        native["spa.temperature"] = 80.0
        native["spa.target_temperature"] = 97.0
        return evaluator.evaluate(
            evidence(
                at=NOW + timedelta(seconds=offset),
                native_values=native,
                spa_mode=mode,
            ),
            live_policy=disabled_policy(),
        ).hot_tub.plan.desired.required_pump_rpm

    assert required_rpm(
        0,
        spa_heater="H0001",
        heater_active=True,
        solar_active=False,
        mode=ThermalRequestedMode.GAS,
    ) == 3000
    assert required_rpm(
        1,
        spa_heater="H0001",
        heater_active=False,
        solar_active=False,
        mode=ThermalRequestedMode.GAS,
    ) == 2600
    assert required_rpm(
        2,
        spa_heater="H0001",
        heater_active=True,
        solar_active=False,
        mode=ThermalRequestedMode.GAS,
    ) == 3000
    required_rpm(
        3,
        spa_heater="H0002",
        heater_active=False,
        solar_active=False,
        mode=ThermalRequestedMode.SOLAR_PREFERRED,
    )
    assert required_rpm(
        123,
        spa_heater="H0002",
        heater_active=False,
        solar_active=False,
        mode=ThermalRequestedMode.SOLAR_PREFERRED,
    ) == 2600
    assert required_rpm(
        124,
        spa_heater="H0002",
        heater_active=False,
        solar_active=True,
        mode=ThermalRequestedMode.SOLAR_PREFERRED,
    ) == 2900


def test_external_spa_gas_preparation_establishes_flow_before_source() -> None:
    preparing_values = live_values(
        pool_active=False,
        pool_heater="00000",
        pump_rpm=2600,
        spa_active=True,
        spa_heater="00000",
    )
    preparing_values["spa.temperature"] = 80.0
    preparing = ThermalRuntimeEvaluator().evaluate(
        evidence(
            native_values=preparing_values,
            spa_mode=ThermalRequestedMode.GAS,
        ),
        live_policy=disabled_policy(),
    ).hot_tub.plan
    at_target = ThermalRuntimeEvaluator().evaluate(
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

    assert preparing.desired.required_pump_rpm == 3000
    assert [type(operation) for operation in preparing.operations] == [
        SetPumpSpeed,
        SetHeatMode,
    ]
    assert at_target.desired.selected_source is PhysicalHeatMode.GAS
    assert at_target.desired.required_pump_rpm == 2600
    assert len(at_target.operations) == 1
    assert isinstance(at_target.operations[0], SetPumpSpeed)
    assert at_target.operations[0].rpm == 2600


def test_external_spa_solar_preparation_establishes_flow_before_source() -> None:
    evaluator = ThermalRuntimeEvaluator()
    preparing_values = live_values(
        pool_active=False,
        pool_heater="00000",
        pump_rpm=2600,
        spa_active=True,
        spa_heater="00000",
        solar_temperature=140.0,
    )
    preparing_values["spa.temperature"] = 80.0
    preparing_values["spa.target_temperature"] = 97.0
    evaluator.evaluate(
        evidence(
            native_values=preparing_values,
            spa_mode=ThermalRequestedMode.SOLAR_PREFERRED,
        ),
        live_policy=disabled_policy(),
    )

    plan = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(minutes=2),
            native_values=preparing_values,
            spa_mode=ThermalRequestedMode.SOLAR_PREFERRED,
        ),
        live_policy=disabled_policy(),
    ).hot_tub.plan

    assert plan.desired.selected_source is PhysicalHeatMode.SOLAR
    assert plan.desired.required_pump_rpm == 2900
    assert [type(operation) for operation in plan.operations] == [
        SetPumpSpeed,
        SetHeatMode,
    ]


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

    # The plan may describe activation, but shared hydraulics fail closed while
    # Pool is authoritative active and Hot Tub is inactive.
    assert result.hot_tub.technical_preflight.ready is False
    assert "other_body_active" in result.hot_tub.technical_preflight.blocking_reasons
    assert isinstance(result.hot_tub.plan.operations[0], SetHeatMode)
    assert result.hot_tub.plan.operations[0].mode is PhysicalHeatMode.SOLAR
    assert isinstance(result.hot_tub.plan.operations[1], SetBodyActive)
    assert result.hot_tub.plan.operations[1].equipment_id == ThermalBody.HOT_TUB.value
    assert result.hot_tub.plan.operations[1].active is True

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
    ]
    assert isinstance(plan.operations[-1], SetPumpSpeed)
    assert plan.operations[-1].rpm == 1500
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


def test_successful_pool_temperature_is_retained_for_current_operational_day() -> None:
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

    assert result.pool.water_temperature is not None
    assert result.pool.water_temperature.disposition.value == "retained"
    assert result.pool.plan.desired.evidence["pool_temperature_f"] == 84.0
    assert result.pool.plan.desired.required_pump_rpm == 2900


def _probe_values(
    *,
    active: bool,
    rpm: int,
    temperature: float = 98.0,
    spa_active: bool = False,
    configured_rpm: int = 1500,
) -> dict[str, object]:
    native = values(pool_active=active, spa_active=spa_active)
    native["pool.raw_heater_id"] = "00000"
    native["pump.rpm"] = rpm
    native["pool.pump_circuit.configured_speed_rpm"] = configured_rpm
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
    probe = evaluator.pool_temperature_probe
    execution = None
    if probe.execution_purpose_id is not None and active and not spa_active and rpm > 0:
        acquiring = True
        started_at = (
            probe.started_at
            if probe.started_at is not None
            else (at if acquiring else None)
        )
        generation = probe.ownership_generation or 1
        if probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED and acquiring:
            generation += 1 if probe.ownership_generation is not None else 0
        execution = PoolTemperatureProbeExecutionEvidence(
            phase=(
                PoolTemperatureProbeExecutionPhase.ACQUIRING
                if acquiring
                else PoolTemperatureProbeExecutionPhase.PREPARING
            ),
            execution_purpose_id=probe.execution_purpose_id,
            execution_plan_id="test-probe-plan",
            ownership_lease_id=f"test-probe-lease-{generation}",
            ownership_generation=generation,
            body_activation_owned=True,
            pump_setpoint_owned=True,
            acquisition_started_at=started_at,
        )
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
            probe_execution=execution,
        ),
        live_policy=disabled_policy(),
    )


def _active_probe_execution(
    evaluator: ThermalRuntimeEvaluator,
    started_at: datetime,
    *,
    purpose_id: str | None = None,
    generation: int = 1,
) -> PoolTemperatureProbeExecutionEvidence:
    bound_purpose_id = evaluator.pool_temperature_probe.execution_purpose_id
    assert bound_purpose_id is not None
    return PoolTemperatureProbeExecutionEvidence(
        phase=PoolTemperatureProbeExecutionPhase.ACQUIRING,
        execution_purpose_id=(
            bound_purpose_id if purpose_id is None else purpose_id
        ),
        execution_plan_id="test-probe-plan",
        ownership_lease_id=f"test-probe-lease-{generation}",
        ownership_generation=generation,
        body_activation_owned=True,
        pump_setpoint_owned=True,
        acquisition_started_at=started_at,
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


def test_positive_gpm_with_zero_actual_rpm_cannot_start_probe_acquisition() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    native = _probe_values(active=True, rpm=0)
    native["pump.gpm"] = 55
    native["pump.power"] = 0

    evaluator.evaluate(
        evidence(
            at=started,
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": started},
            probe_execution=_active_probe_execution(evaluator, started),
        ),
        live_policy=disabled_policy(),
    )

    assert evaluator.pool_temperature_probe.phase is (
        PoolTemperatureProbePhase.PROBE_REQUIRED
    )
    assert evaluator.pool_temperature_probe.started_at is None
    assert evaluator.pool_temperature_probe.samples == ()


@pytest.mark.parametrize(
    ("first_rpm", "expected_phase"),
    (
        (1500, PoolTemperatureProbePhase.PROBING),
        (1525, PoolTemperatureProbePhase.PROBING),
    ),
)
def test_probe_owned_circulation_cannot_immediately_trust_pipe_temperature(
    first_rpm: int,
    expected_phase: PoolTemperatureProbePhase,
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
    assert probe.phase is expected_phase
    assert probe.started_at == (
        NOW + timedelta(seconds=30)
        if expected_phase is PoolTemperatureProbePhase.PROBING
        else None
    )
    assert probe.last_assessment is not None
    assert probe.last_assessment.disposition.value == (
        "probing"
        if expected_phase is PoolTemperatureProbePhase.PROBING
        else "probe_required"
    )
    assert probe.last_assessment.reason_code in {
        "probe_minimum_duration",
        "thermal_decision_requires_trusted_water",
    }
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
        rpm=1500,
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
            probe_execution=_active_probe_execution(evaluator, started),
        ),
        live_policy=disabled_policy(),
    )
    evaluator.evaluate(
        evidence(
            at=started + timedelta(seconds=45),
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": observed_at},
            probe_execution=_active_probe_execution(evaluator, started),
        ),
        live_policy=disabled_policy(),
    )

    assert evaluator.pool_temperature_probe.samples[-1].observed_at == observed_at
    assert sum(
        sample.observed_at == observed_at
        for sample in evaluator.pool_temperature_probe.samples
    ) == 1


def test_probe_execution_purpose_change_discards_acquisition_epoch() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    original_purpose_id = evaluator.pool_temperature_probe.execution_purpose_id
    assert original_purpose_id is not None
    started = NOW + timedelta(seconds=30)
    execution = _active_probe_execution(evaluator, started)

    evaluator.evaluate(
        evidence(
            at=started,
            native_values=_probe_values(active=True, rpm=1500, temperature=90.0),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": started},
            probe_execution=execution,
        ),
        live_policy=disabled_policy(),
    )
    sample_at = started + timedelta(seconds=30)
    evaluator.evaluate(
        evidence(
            at=sample_at,
            native_values=_probe_values(active=True, rpm=1500, temperature=89.5),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": sample_at},
            probe_execution=execution,
        ),
        live_policy=disabled_policy(),
    )
    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == started
    assert len(probe.samples) == 1

    mismatch_at = started + timedelta(seconds=45)
    mismatched = _active_probe_execution(
        evaluator,
        started,
        purpose_id="different-probe-purpose",
    )
    result = evaluator.evaluate(
        evidence(
            at=mismatch_at,
            native_values=_probe_values(active=True, rpm=1500, temperature=89.0),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": mismatch_at},
            probe_execution=mismatched,
        ),
        live_policy=disabled_policy(),
    )

    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.started_at is None
    assert probe.samples == ()
    assert probe.ownership_generation is None
    assert probe.execution_purpose_id == original_purpose_id
    assert result.pool.plan.desired.evidence["pool_temperature_f"] is None

    restarted_at = started + timedelta(seconds=60)
    evaluator.evaluate(
        evidence(
            at=restarted_at,
            native_values=_probe_values(active=True, rpm=1500, temperature=88.5),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": restarted_at},
            probe_execution=_active_probe_execution(
                evaluator,
                restarted_at,
                generation=2,
            ),
        ),
        live_policy=disabled_policy(),
    )

    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == restarted_at
    assert probe.samples == ()
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "probe_minimum_duration"


def test_probe_ownership_generation_change_discards_acquisition_epoch() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    execution = _active_probe_execution(evaluator, started)
    sample_at = started + timedelta(seconds=30)
    evaluator.evaluate(
        evidence(
            at=sample_at,
            native_values=_probe_values(active=True, rpm=1500, temperature=89.5),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": sample_at},
            probe_execution=execution,
        ),
        live_policy=disabled_policy(),
    )
    probe = evaluator.pool_temperature_probe
    assert probe.started_at == started
    assert len(probe.samples) == 1

    next_started = started + timedelta(seconds=45)
    evaluator.evaluate(
        evidence(
            at=next_started,
            native_values=_probe_values(active=True, rpm=1500, temperature=89.0),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": next_started},
            probe_execution=_active_probe_execution(
                evaluator,
                next_started,
                generation=2,
            ),
        ),
        live_policy=disabled_policy(),
    )

    assert probe.phase is PoolTemperatureProbePhase.PROBING
    assert probe.started_at == next_started
    assert probe.ownership_generation == 2
    assert probe.samples == ()
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "probe_minimum_duration"


def test_mismatched_preparing_evidence_does_not_rebind_probe_requirement() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    canonical_purpose_id = evaluator.pool_temperature_probe.execution_purpose_id
    assert canonical_purpose_id is not None

    evaluator.evaluate(
        evidence(
            at=NOW + timedelta(seconds=10),
            native_values=_probe_values(active=False, rpm=0),
            pool_mode=ThermalRequestedMode.SOLAR,
            probe_execution=PoolTemperatureProbeExecutionEvidence(
                phase=PoolTemperatureProbeExecutionPhase.PREPARING,
                execution_purpose_id="different-probe-purpose",
                execution_plan_id="different-probe-plan",
                ownership_lease_id="different-probe-lease",
                ownership_generation=2,
                body_activation_owned=False,
                pump_setpoint_owned=False,
            ),
        ),
        live_policy=disabled_policy(),
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert probe.execution_purpose_id == canonical_purpose_id
    assert probe.ownership_generation is None
    assert probe.started_at is None
    assert probe.samples == ()


def test_purpose_change_after_trust_clears_probe_epoch_but_preserves_canonical_reuse() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    _evaluate_probe(evaluator, at=NOW + timedelta(seconds=30), active=True, rpm=3000)
    for elapsed_seconds, temperature in ((90, 87.0), (150, 86.5), (210, 86.0)):
        _evaluate_probe(
            evaluator,
            at=NOW + timedelta(seconds=elapsed_seconds),
            active=True,
            rpm=1500,
            temperature=temperature,
        )
    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.TRUSTED
    assert probe.samples
    acquisition_started_at = probe.started_at
    assert acquisition_started_at is not None

    evaluated_at = NOW + timedelta(seconds=220)
    evaluator.evaluate(
        evidence(
            at=evaluated_at,
            native_values=_probe_values(active=True, rpm=1500, temperature=85.5),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": evaluated_at},
            probe_execution=_active_probe_execution(
                evaluator,
                acquisition_started_at,
                purpose_id="different-probe-purpose",
            ),
        ),
        live_policy=disabled_policy(),
    )

    assert probe.phase is PoolTemperatureProbePhase.IDLE
    assert probe.execution_purpose_id is None
    assert probe.ownership_generation is None
    assert probe.started_at is None
    assert probe.samples == ()
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "trusted_temperature_within_reuse_window"


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
    assert interrupted.samples == ()
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
    assert probe.samples == ()
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
        rpm=1500,
        temperature=98.0,
    )
    _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=90),
        active=True,
        rpm=1500,
        temperature=87.0,
    )
    result = _evaluate_probe(
        evaluator,
        at=NOW + timedelta(seconds=150),
        active=True,
        rpm=1500,
        temperature=86.5,
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.TRUSTED
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "probe_settled"
    assert probe.last_assessment.trusted_temperature_f == 86.5
    assert result.pool.plan.desired.evidence["pool_temperature_f"] == 86.5


def test_probe_transients_never_become_trusted_and_fail_closed_at_five_minutes() -> None:
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
    acquisition_started = started
    for elapsed_seconds, temperature in (
        (30, 94.0),
        (90, 88.0),
        (150, 93.0),
        (270, 86.0),
    ):
        result = _evaluate_probe(
            evaluator,
            at=acquisition_started + timedelta(seconds=elapsed_seconds),
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
        at=acquisition_started + timedelta(minutes=5),
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
        at=acquisition_started + timedelta(minutes=5, seconds=30),
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
            probe_execution=_active_probe_execution(evaluator, started),
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


def test_matching_probe_rpm_without_execution_provenance_is_ordinary_trust() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)

    result = evaluator.evaluate(
        evidence(
            at=NOW + timedelta(seconds=30),
            native_values=_probe_values(active=True, rpm=1500, temperature=84.0),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": NOW + timedelta(seconds=30)},
            probe_execution=None,
        ),
        live_policy=disabled_policy(),
    )

    probe = evaluator.pool_temperature_probe
    assert probe.phase is PoolTemperatureProbePhase.IDLE
    assert probe.started_at is None
    assert probe.samples == ()
    assert probe.last_assessment is not None
    assert probe.last_assessment.reason_code == "existing_circulation"
    assert result.pool.plan.desired.reason_code != "pool_temperature_probe_required"


@pytest.mark.parametrize(
    ("actual_rpm", "configured_rpm"),
    ((1526, 1500), (1500, 1499), (3000, 2600)),
)
def test_probe_acquisition_rejects_wrong_actual_or_configured_rpm(
    actual_rpm: int,
    configured_rpm: int,
) -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500)
    _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=60),
        active=True,
        rpm=1500,
        temperature=89.0,
    )
    native = _probe_values(
        active=True,
        rpm=actual_rpm,
        configured_rpm=configured_rpm,
        temperature=89.0,
    )

    evaluator.evaluate(
        evidence(
            at=started + timedelta(seconds=90),
            native_values=native,
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": started + timedelta(seconds=90)},
            probe_execution=_active_probe_execution(evaluator, started),
        ),
        live_policy=disabled_policy(),
    )

    assert (
        evaluator.pool_temperature_probe.phase
        is PoolTemperatureProbePhase.PROBE_REQUIRED
    )
    assert evaluator.pool_temperature_probe.started_at is None
    assert evaluator.pool_temperature_probe.samples == ()


def test_probe_diagnostics_are_bounded_and_observational() -> None:
    evaluator = ThermalRuntimeEvaluator()
    result = _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    before = (
        evaluator.pool_temperature_probe.phase,
        evaluator.pool_temperature_probe.started_at,
        evaluator.pool_temperature_probe.samples,
    )

    first = dict(result.pool.diagnostics())
    second = dict(result.pool.diagnostics())

    assert first == second
    assert first["probe_lifecycle_state"] == "probe_required"
    assert first["probe_sample_count"] == 0
    assert (
        evaluator.pool_temperature_probe.phase,
        evaluator.pool_temperature_probe.started_at,
        evaluator.pool_temperature_probe.samples,
    ) == before


def test_current_frame_continuity_blocker_prevents_probe_trust() -> None:
    evaluator = ThermalRuntimeEvaluator()
    _evaluate_probe(evaluator, at=NOW, active=False, rpm=0)
    started = NOW + timedelta(seconds=30)
    _evaluate_probe(evaluator, at=started, active=True, rpm=1500, temperature=86.0)
    _evaluate_probe(
        evaluator,
        at=started + timedelta(seconds=60),
        active=True,
        rpm=1500,
        temperature=86.0,
    )
    execution = _active_probe_execution(evaluator, started)

    evaluator.evaluate(
        evidence(
            at=started + timedelta(minutes=2),
            native_values=_probe_values(active=True, rpm=1500, temperature=86.0),
            pool_mode=ThermalRequestedMode.SOLAR,
            observed_at={"pool.temperature": started + timedelta(minutes=2)},
            probe_execution=execution,
            probe_continuity=PoolTemperatureProbeContinuityEvidence(
                evaluated_at=started + timedelta(minutes=2),
                valid=False,
                blocker="runtime_ownership_preempted:pump_external_change",
            ),
        ),
        live_policy=disabled_policy(),
    )

    assert evaluator.pool_temperature_probe.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
    assert evaluator.pool_temperature_probe.last_assessment is not None
    assert evaluator.pool_temperature_probe.last_assessment.trusted_temperature_f is None
