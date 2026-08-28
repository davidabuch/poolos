from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

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
    pending: bool = False,
    confirmed: bool = False,
) -> ThermalRuntimeEvidence:
    return ThermalRuntimeEvidence(
        evaluated_at=at,
        native_values=values() if native_values is None else native_values,
        pool_requested_mode=pool_mode,
        hot_tub_requested_mode=spa_mode,
        native_transport_available=native_available,
        manual_transport_available=manual_available,
        immediate_observation_healthy=health,
        stale_native_concepts=stale,
        missing_native_concepts=missing,
        native_configuration=NativeConfigurationGuard().evaluate(configuration),
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
