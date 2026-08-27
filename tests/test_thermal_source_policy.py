from datetime import datetime
from zoneinfo import ZoneInfo

from poolos.operational_intelligence import OperationalIntelligencePipeline
from poolos.pump_optimization import PumpOperationOptimizer, PumpOptimizationPolicy
from poolos.thermal_source_policy import ForecastGateEvidence, HeatSourcePermissions, HeatSourcePermissionUpdate, PermissionEvidenceKind, PoolHeatingMode, ThermalHeatSource, ThermalOperatingMode, ThermalSourceInput, ThermalSourceSelector, apply_permission_update


LOCAL = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL)


def observation(*, water: float | None = 86, target: float = 90, collector: float = 93, mode: PoolHeatingMode = PoolHeatingMode.SOLAR_ONLY, solar_active: bool = False, permissions: HeatSourcePermissions = HeatSourcePermissions(), override: bool = False, forecast: ForecastGateEvidence = ForecastGateEvidence(), probe: bool = False) -> ThermalSourceInput:
    return ThermalSourceInput(NOW, True, False, solar_active, water, target, collector, mode, permissions, override, forecast, probe)


def test_solar_only_uses_immediate_physical_solar_and_never_gas() -> None:
    selected = ThermalSourceSelector().evaluate(observation())
    unavailable = ThermalSourceSelector().evaluate(observation(collector=80))
    assert selected.mode is ThermalOperatingMode.POOL_SOLAR
    assert selected.recommended_pump_rpm == 2900
    assert unavailable.mode is ThermalOperatingMode.NONE
    assert unavailable.heat_source is ThermalHeatSource.NONE


def test_solar_preferred_prefers_solar_then_authorizes_gas_fallback() -> None:
    solar = ThermalSourceSelector().evaluate(observation(mode=PoolHeatingMode.SOLAR_PREFERRED))
    gas = ThermalSourceSelector().evaluate(observation(mode=PoolHeatingMode.SOLAR_PREFERRED, collector=80))
    assert solar.mode is ThermalOperatingMode.POOL_SOLAR
    assert gas.mode is ThermalOperatingMode.POOL_GAS
    assert gas.recommended_pump_rpm == 3000


def test_gas_only_suppresses_solar_and_modes_are_mutually_exclusive() -> None:
    result = ThermalSourceSelector().evaluate(observation(mode=PoolHeatingMode.GAS_ONLY, collector=140))
    assert result.mode is ThermalOperatingMode.POOL_GAS
    assert result.heat_source is ThermalHeatSource.GAS
    assert set(PoolHeatingMode) == {PoolHeatingMode.SOLAR_ONLY, PoolHeatingMode.SOLAR_PREFERRED, PoolHeatingMode.GAS_ONLY}


def test_hard_permissions_veto_only_the_affected_source() -> None:
    solar_veto = ThermalSourceSelector().evaluate(observation(permissions=HeatSourcePermissions(solar_allowed=False, solar_veto_reason="manual solar disable")))
    gas_veto = ThermalSourceSelector().evaluate(observation(mode=PoolHeatingMode.GAS_ONLY, permissions=HeatSourcePermissions(gas_allowed=False, gas_veto_reason="maintenance")))
    assert solar_veto.mode is ThermalOperatingMode.NONE
    assert solar_veto.skipped_due_to_permission == "manual solar disable"
    assert gas_veto.mode is ThermalOperatingMode.NONE
    assert gas_veto.skipped_due_to_permission == "maintenance"


def test_normal_shutdown_does_not_mutate_persistent_permissions() -> None:
    permissions = HeatSourcePermissions()
    unchanged = apply_permission_update(
        permissions,
        HeatSourcePermissionUpdate(PermissionEvidenceKind.NORMAL_OPERATION, solar_allowed=False, gas_allowed=False),
    )
    assert unchanged is permissions


def test_intentional_native_disable_creates_persistent_permission_veto() -> None:
    updated = apply_permission_update(
        HeatSourcePermissions(),
        HeatSourcePermissionUpdate(
            PermissionEvidenceKind.INTENTIONAL_USER_CONFIGURATION,
            solar_allowed=False,
            reason="disabled at native controller",
        ),
    )
    assert not updated.solar_allowed
    assert updated.gas_allowed
    assert updated.solar_veto_reason == "disabled at native controller"


def test_five_degree_or_less_deficit_bypasses_forecast_suppression() -> None:
    cold_forecast = ForecastGateEvidence((60, 60, 60, 60, 60), True, True)
    result = ThermalSourceSelector().evaluate(observation(water=85, target=90, collector=100, forecast=cold_forecast))
    assert result.mode is ThermalOperatingMode.POOL_SOLAR
    assert not result.forecast_gate_applied


def test_large_deficit_requires_four_of_five_warm_forecast_days() -> None:
    passing = ForecastGateEvidence((78, 79, 65, 80, 81), True, True)
    failing = ForecastGateEvidence((78, 79, 77, 76, 80), True, True)
    passed = ThermalSourceSelector().evaluate(observation(water=80, target=90, collector=100, forecast=passing))
    failed = ThermalSourceSelector().evaluate(observation(water=80, target=90, collector=100, forecast=failing))
    assert passed.mode is ThermalOperatingMode.POOL_SOLAR
    assert failed.mode is ThermalOperatingMode.NONE


def test_missing_forecast_falls_back_to_physical_rules() -> None:
    result = ThermalSourceSelector().evaluate(observation(water=80, target=90, collector=100))
    assert result.mode is ThermalOperatingMode.POOL_SOLAR
    assert result.forecast_gate_passed


def test_forecast_gate_applies_only_to_solar_only() -> None:
    cold = ForecastGateEvidence((60, 60, 60, 60, 60), True, True)
    result = ThermalSourceSelector().evaluate(
        observation(
            water=80,
            target=90,
            collector=100,
            mode=PoolHeatingMode.SOLAR_PREFERRED,
            forecast=cold,
        )
    )
    assert result.mode is ThermalOperatingMode.POOL_SOLAR
    assert not result.forecast_gate_applied


def test_override_only_bypasses_solar_only_forecast_gate() -> None:
    cold = ForecastGateEvidence((60, 60, 60, 60, 60), True, True)
    overridden = ThermalSourceSelector().evaluate(observation(water=80, collector=100, override=True, forecast=cold))
    physical_failure = ThermalSourceSelector().evaluate(observation(water=80, collector=85, override=True, forecast=cold))
    gas_only = ThermalSourceSelector().evaluate(observation(mode=PoolHeatingMode.GAS_ONLY, override=True, collector=140))
    assert overridden.mode is ThermalOperatingMode.POOL_SOLAR
    assert physical_failure.mode is ThermalOperatingMode.NONE
    assert gas_only.mode is ThermalOperatingMode.POOL_GAS


def test_target_change_alone_never_creates_override() -> None:
    result = ThermalSourceSelector().evaluate(observation(target=95))
    assert not observation(target=95).solar_override
    assert result.forecast_gate_applied


def test_probe_intent_uses_1500_then_trusted_eligible_input_uses_2900() -> None:
    probe = ThermalSourceSelector().evaluate(observation(water=None, probe=True))
    solar = ThermalSourceSelector().evaluate(observation(water=86, probe=False))
    assert probe.mode is ThermalOperatingMode.POOL_TEMPERATURE_PROBE
    assert probe.recommended_pump_rpm == 1500
    assert solar.mode is ThermalOperatingMode.POOL_SOLAR
    assert solar.recommended_pump_rpm == 2900


def test_baselines_flow_through_existing_optimizer_and_recommendation() -> None:
    assessment = ThermalSourceSelector().evaluate(observation())
    assert assessment.intent is not None
    pipeline = OperationalIntelligencePipeline(PumpOperationOptimizer(PumpOptimizationPolicy(1000, 3200, 100, {})))
    result = pipeline.evaluate((assessment.intent,), evaluated_at=NOW)
    assert result.recommendation.recommended_pump_rpm == 2900
    assert result.to_dict()["command_delivery_enabled"] is False


def test_tou_and_gpm_are_not_thermal_control_inputs() -> None:
    fields = ThermalSourceInput.__dataclass_fields__
    assert "pump_gpm" not in fields
    assert "tou_tier" not in fields
