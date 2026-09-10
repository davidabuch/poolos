"""Regression coverage for one effective configurable pump-baseline policy."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_priming_policy import PumpPrimingPolicy
from poolos.spa_thermal_policy import (
    SpaHeatingMode,
    SpaPolicyInput,
    SpaSessionKind,
    SpaUserSource,
)
from poolos.thermal_source_policy import (
    PoolHeatingMode,
    ThermalHeatSource,
    ThermalSourceInput,
)
from poolos.physical_command_authority import (
    AutomaticThermalDispatchPurpose,
    GridOutageDispatchPurpose,
    PhysicalAuthorityReason,
    PhysicalCommandRequest,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)


NON_DEFAULT_BASELINES = PumpOperatingBaselines(
    filtration_rpm=2650,
    solar_heating_rpm=2950,
    gas_heating_rpm=3050,
    temperature_probe_rpm=1550,
    priming_rpm=3050,
    grid_outage_rpm=1600,
)

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
TEST_PACKAGE = "_poolos_configurable_pump_baselines_test"


def _load_component_module(name: str) -> ModuleType:
    if TEST_PACKAGE not in sys.modules:
        package = ModuleType(TEST_PACKAGE)
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        package.__package__ = TEST_PACKAGE
        sys.modules[TEST_PACKAGE] = package
    qualified = f"{TEST_PACKAGE}.{name}"
    if existing := sys.modules.get(qualified):
        return existing
    path = COMPONENT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


CONST = _load_component_module("const")
PUMP_BASELINES = _load_component_module("pump_baselines")


def configured_values() -> dict[str, Any]:
    return {
        CONST.CONF_PUMP_FILTRATION_RPM: 2650,
        CONST.CONF_PUMP_SOLAR_HEATING_RPM: 2950,
        CONST.CONF_PUMP_GAS_HEATING_RPM: 3050,
        CONST.CONF_PUMP_TEMPERATURE_PROBE_RPM: 1550,
        CONST.CONF_PUMP_PRIMING_RPM: 3050,
        CONST.CONF_PUMP_GRID_OUTAGE_RPM: 1600,
    }


def ready_authority() -> PoolOSPhysicalCommandAuthority:
    authority = PoolOSPhysicalCommandAuthority(baselines=NON_DEFAULT_BASELINES)
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    return authority


def test_effective_policy_defaults_and_strict_configuration_validation() -> None:
    assert PUMP_BASELINES.effective_pump_operating_baselines({}) == (
        PumpOperatingBaselines()
    )
    assert PUMP_BASELINES.effective_pump_operating_baselines(
        configured_values()
    ) == NON_DEFAULT_BASELINES

    for invalid in (True, -1, 0, 449, 3451, 2650.0, "2650"):
        configured = configured_values()
        configured[CONST.CONF_PUMP_FILTRATION_RPM] = invalid
        with pytest.raises(ValueError):
            PUMP_BASELINES.effective_pump_operating_baselines(configured)


def test_policy_fingerprint_is_deterministic_and_value_specific() -> None:
    same = PumpOperatingBaselines(**dict(NON_DEFAULT_BASELINES.as_dict()))
    changed = PumpOperatingBaselines(
        **{
            **dict(NON_DEFAULT_BASELINES.as_dict()),
            "solar_heating_rpm": 2960,
        }
    )

    assert NON_DEFAULT_BASELINES.fingerprint == same.fingerprint
    assert NON_DEFAULT_BASELINES.fingerprint != changed.fingerprint


def test_production_composition_binds_every_nested_core_dependency() -> None:
    graph = PUMP_BASELINES.compose_pump_baseline_runtime(configured_values())

    assert graph.baselines == NON_DEFAULT_BASELINES
    assert graph.thermal_evaluator.baselines is graph.baselines
    assert graph.thermal_evaluator.pool_selector._policy.baselines is graph.baselines
    assert graph.thermal_evaluator.spa_tracker._policy.baselines is graph.baselines
    assert (
        graph.thermal_evaluator.planner.priming_policy.baselines
        is graph.baselines
    )
    assert graph.thermal_orchestrator.baselines is graph.baselines
    assert graph.physical_authority.baselines is graph.baselines
    assert graph.grid_outage_engine.baselines is graph.baselines
    assert graph.pump_speed_session.baselines is graph.baselines
    assert graph.baselines.spillway_rpm == 2900


def test_merged_options_override_data_without_discarding_unrelated_values() -> None:
    entry_data = {
        "grid_status_entity": "binary_sensor.grid",
        "preferred_filtration_catchup_start": "20:00",
        **configured_values(),
    }
    entry_options = {
        "preferred_filtration_catchup_start": "22:01",
        CONST.CONF_PUMP_SOLAR_HEATING_RPM: 2960,
    }
    configured = {**entry_data, **entry_options}

    graph = PUMP_BASELINES.compose_pump_baseline_runtime(configured)

    assert configured["grid_status_entity"] == "binary_sensor.grid"
    assert configured["preferred_filtration_catchup_start"] == "22:01"
    assert graph.baselines.filtration_rpm == 2650
    assert graph.baselines.solar_heating_rpm == 2960
    assert graph.baselines.gas_heating_rpm == 3050


def test_reload_builds_a_new_policy_without_mutating_the_old_policy() -> None:
    first = PUMP_BASELINES.compose_pump_baseline_runtime(configured_values())
    updated = configured_values()
    updated[CONST.CONF_PUMP_SOLAR_HEATING_RPM] = 3100
    updated[CONST.CONF_PUMP_GRID_OUTAGE_RPM] = 1650

    second = PUMP_BASELINES.compose_pump_baseline_runtime(updated)

    assert first.baselines.solar_heating_rpm == 2950
    assert first.baselines.grid_outage_rpm == 1600
    assert second.baselines.solar_heating_rpm == 3100
    assert second.baselines.grid_outage_rpm == 1650
    assert first.baselines is not second.baselines
    assert first.baselines.fingerprint != second.baselines.fingerprint


def test_configuration_surface_exposes_all_six_values_without_command_side_effects() -> None:
    flow_source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    translations = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )

    for key in configured_values():
        assert f"CONF_{key.upper()}" in flow_source
        assert key in translations["config"]["step"]["user"]["data"]
        assert key in translations["options"]["step"]["init"]["data"]
    assert "async_set_" not in flow_source
    assert "services.async_call" not in flow_source


def test_composed_pool_spa_probe_and_priming_policy_emit_configured_values() -> None:
    from datetime import UTC, datetime

    graph = PUMP_BASELINES.compose_pump_baseline_runtime(configured_values())
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    solar = graph.thermal_evaluator.pool_selector.evaluate(
        ThermalSourceInput(
            evaluated_at=now,
            pool_active=True,
            spa_active=False,
            solar_active=False,
            trusted_pool_temperature_f=80.0,
            pool_target_f=90.0,
            collector_temperature_f=100.0,
            heating_mode=PoolHeatingMode.SOLAR_ONLY,
        )
    )
    gas = graph.thermal_evaluator.pool_selector.evaluate(
        ThermalSourceInput(
            evaluated_at=now,
            pool_active=True,
            spa_active=False,
            solar_active=False,
            trusted_pool_temperature_f=80.0,
            pool_target_f=90.0,
            collector_temperature_f=70.0,
            heating_mode=PoolHeatingMode.GAS_ONLY,
        )
    )
    probe = graph.thermal_evaluator.pool_selector.evaluate(
        ThermalSourceInput(
            evaluated_at=now,
            pool_active=False,
            spa_active=False,
            solar_active=False,
            trusted_pool_temperature_f=None,
            pool_target_f=90.0,
            collector_temperature_f=100.0,
            temperature_probe_required=True,
        )
    )
    spa = graph.thermal_evaluator.spa_tracker.evaluate(
        SpaPolicyInput(
            evaluated_at=now,
            spa_active=True,
            transition_source=SpaUserSource.NATIVE,
            spa_temperature_f=90.0,
            spa_target_f=100.0,
            collector_temperature_f=70.0,
            heating_mode=SpaHeatingMode.GAS_ONLY,
            session_kind=SpaSessionKind.EXTERNAL_USER,
            active_heat_source=ThermalHeatSource.GAS,
        )
    )
    priming = PumpPrimingPolicy(baselines=graph.baselines).evaluate(
        circulation_requested=True,
        currently_circulating=False,
    )

    assert solar.recommended_pump_rpm == 2950
    assert gas.recommended_pump_rpm == 3050
    assert probe.recommended_pump_rpm == 1550
    assert spa.recommended_pump_rpm == 3050
    assert priming.priming_rpm == 3050


def test_non_default_filtration_baseline_reaches_final_physical_authority() -> None:
    """Expose the pre-fix split between configured policy and fixed authority."""

    authority = ready_authority()
    authority.configure_automatic_filtration(enabled=True)
    authority.begin_automatic_filtration_epoch("configured-policy-epoch")
    context = authority.bind_automatic_filtration_dispatch(
        epoch_identity="configured-policy-epoch",
        session_identity="configured-policy-session",
        operation_identity="configured-filtration-operation",
        operation="pump_circuit_speed",
        target="p0102",
        requested_value=NON_DEFAULT_BASELINES.filtration_rpm,
        pump_circuit_id="p0102",
    )

    decision = authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_FILTRATION,
            requested_value=NON_DEFAULT_BASELINES.filtration_rpm,
            automatic_filtration_context=context,
        )
    )

    assert decision.allowed


def test_non_default_normal_thermal_values_are_exact_and_body_bound() -> None:
    authority = ready_authority()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("configured-thermal-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="configured-thermal-epoch",
        session_identity="configured-solar-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="solar_heating",
    )

    def decision(value: int, *, target: str = "p0102") -> PhysicalAuthorityReason:
        return authority.assess(
            PhysicalCommandRequest(
                operation="pump_circuit_speed",
                target=target,
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=value,
                automatic_thermal_context=context,
            )
        ).reason

    assert decision(2950) is PhysicalAuthorityReason.ALLOWED
    assert decision(2900) is PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    assert decision(3200) is PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    assert decision(2950, target="p0103") is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )


@pytest.mark.parametrize(
    ("body", "scope", "pump", "purpose", "configured_rpm", "wrong_rpm"),
    (
        ("pool", "pool", "p0102", "solar_heating", 2950, 3050),
        ("pool", "pool", "p0102", "gas_heating", 3050, 2950),
        ("hot_tub", "hot_tub", "p0103", "solar_heating", 2950, 3050),
        ("hot_tub", "hot_tub", "p0103", "gas_heating", 3050, 2950),
    ),
)
def test_pool_and_hot_tub_thermal_authority_is_exact_and_body_bound(
    body: str,
    scope: str,
    pump: str,
    purpose: str,
    configured_rpm: int,
    wrong_rpm: int,
) -> None:
    authority = ready_authority()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope=scope,
    )
    authority.begin_automatic_thermal_epoch(f"{body}-{purpose}-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity=f"{body}-{purpose}-epoch",
        session_identity=f"{body}-{purpose}-session",
        body=body,
        pump_circuit_id=pump,
        operating_purpose=purpose,
    )

    def reason(target: str, rpm: int) -> PhysicalAuthorityReason:
        return authority.assess(
            PhysicalCommandRequest(
                operation="pump_circuit_speed",
                target=target,
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=rpm,
                automatic_thermal_context=context,
            )
        ).reason

    assert reason(pump, configured_rpm) is PhysicalAuthorityReason.ALLOWED
    assert reason(pump, wrong_rpm) is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )
    other_pump = "p0103" if pump == "p0102" else "p0102"
    assert reason(other_pump, configured_rpm) is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )


def test_non_default_probe_and_outage_registration_remain_exact() -> None:
    authority = ready_authority()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("probe-epoch")
    authority.register_automatic_thermal_probe(
        epoch_identity="probe-epoch",
        operation_id="probe-operation",
        operation="pump_circuit_speed",
        target="p0102",
        requested_value=1550,
    )
    probe_context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="probe-epoch",
        session_identity="probe-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="temperature_acquisition",
        purpose=AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE,
        probe_operation_id="probe-operation",
    )
    assert authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=1550,
            automatic_thermal_context=probe_context,
        )
    ).allowed
    with pytest.raises(ValueError, match="temperature-probe"):
        authority.register_automatic_thermal_probe(
            epoch_identity="probe-epoch",
            operation_id="old-probe-operation",
            operation="pump_circuit_speed",
            target="p0102",
            requested_value=1500,
        )

    authority.configure_grid_outage_safety(enabled=True)
    authority.begin_grid_outage_frame(
        outage_epoch_id="outage-epoch",
        frame_identity="outage-frame",
    )
    outage_authority = authority.register_grid_outage_candidate(
        outage_epoch_id="outage-epoch",
        frame_identity="outage-frame",
        candidate_id="configured-outage",
        purpose=GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
        operation="pump_circuit_speed",
        target="p0102",
        requested_value=1600,
    )
    outage_context = authority.bind_grid_outage_dispatch(outage_authority)
    assert authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
            requested_value=1600,
            grid_outage_context=outage_context,
        )
    ).allowed
    with pytest.raises(ValueError, match="reduction envelope"):
        authority.register_grid_outage_candidate(
            outage_epoch_id="outage-epoch",
            frame_identity="outage-frame",
            candidate_id="old-outage",
            purpose=GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
            operation="pump_circuit_speed",
            target="p0102",
            requested_value=1500,
        )


def test_non_default_priming_authority_is_exact() -> None:
    authority = ready_authority()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("priming-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="priming-epoch",
        session_identity="priming-session",
        body="pool",
        pump_circuit_id="p0102",
    )

    def reason(rpm: int) -> PhysicalAuthorityReason:
        return authority.assess(
            PhysicalCommandRequest(
                operation="pump_circuit_speed",
                target="p0102",
                source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                requested_value=rpm,
                automatic_thermal_context=context,
            )
        ).reason

    assert reason(3050) is PhysicalAuthorityReason.ALLOWED
    assert reason(3000) is (
        PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
    )

def test_policy_a_context_is_stale_under_policy_b_authority() -> None:
    authority = ready_authority()
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("policy-a-epoch")
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="policy-a-epoch",
        session_identity="policy-a-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="solar_heating",
    )
    stale = type(context)(
        generation=context.generation,
        epoch_identity=context.epoch_identity,
        session_identity=context.session_identity,
        body=context.body,
        pump_circuit_id=context.pump_circuit_id,
        operating_purpose=context.operating_purpose,
        purpose=AutomaticThermalDispatchPurpose.NORMAL,
        policy_fingerprint=PumpOperatingBaselines().fingerprint,
    )

    result = authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=2950,
            automatic_thermal_context=stale,
        )
    )

    assert result.reason is PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE


@pytest.mark.parametrize(
    ("authority_baselines", "stale_fingerprint", "rpm"),
    (
        (NON_DEFAULT_BASELINES, PumpOperatingBaselines().fingerprint, 2950),
        (PumpOperatingBaselines(), NON_DEFAULT_BASELINES.fingerprint, 2900),
    ),
)
def test_policy_replacement_rejects_contexts_in_both_directions(
    authority_baselines: PumpOperatingBaselines,
    stale_fingerprint: str,
    rpm: int,
) -> None:
    authority = PoolOSPhysicalCommandAuthority(baselines=authority_baselines)
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("replacement-epoch")
    current = authority.bind_automatic_thermal_dispatch(
        epoch_identity="replacement-epoch",
        session_identity="replacement-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="solar_heating",
    )
    stale = replace(current, policy_fingerprint=stale_fingerprint)

    result = authority.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=rpm,
            automatic_thermal_context=stale,
        )
    )

    assert result.reason is PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE



def test_same_value_reload_rejects_stale_runtime_thermal_context() -> None:
    """Same policy values must not make old-runtime thermal work current."""

    policy_a = PumpOperatingBaselines(**dict(NON_DEFAULT_BASELINES.as_dict()))
    policy_b = PumpOperatingBaselines(**dict(NON_DEFAULT_BASELINES.as_dict()))

    assert policy_a is not policy_b
    assert policy_a.fingerprint == policy_b.fingerprint

    authority_a = PoolOSPhysicalCommandAuthority(baselines=policy_a)
    authority_b = PoolOSPhysicalCommandAuthority(baselines=policy_b)

    for authority in (authority_a, authority_b):
        authority.resolve_maintenance(False)
        authority.set_controller_mode("auto")
        authority.configure_automatic_thermal(
            driver_enabled=True,
            thermal_live_enabled=True,
            commissioning_scope="pool",
        )
        authority.begin_automatic_thermal_epoch("reload-epoch")

    context_a = authority_a.bind_automatic_thermal_dispatch(
        epoch_identity="reload-epoch",
        session_identity="reload-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="solar_heating",
    )
    context_b = authority_b.bind_automatic_thermal_dispatch(
        epoch_identity="reload-epoch",
        session_identity="reload-session",
        body="pool",
        pump_circuit_id="p0102",
        operating_purpose="solar_heating",
    )

    assert context_a.policy_fingerprint == context_b.policy_fingerprint
    assert context_a.runtime_binding
    assert context_b.runtime_binding
    assert context_a.runtime_binding != context_b.runtime_binding
    assert context_a != context_b

    stale = authority_b.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=NON_DEFAULT_BASELINES.solar_heating_rpm,
            automatic_thermal_context=context_a,
        )
    )
    current = authority_b.assess(
        PhysicalCommandRequest(
            operation="pump_circuit_speed",
            target="p0102",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=NON_DEFAULT_BASELINES.solar_heating_rpm,
            automatic_thermal_context=context_b,
        )
    )

    assert stale.reason is PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
    assert current.reason is PhysicalAuthorityReason.ALLOWED


def test_pump_baseline_config_flow_uses_serializable_number_selectors() -> None:
    """Pump RPM options must remain serializable by Home Assistant config flows."""

    flow_source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    assert "_valid_pump_rpm" not in flow_source
    assert "vol.All(" not in flow_source[
        flow_source.index("pump_speed_selector = selector.NumberSelector("):
        flow_source.index("CONF_INTELLICENTER_HOST")
    ]

    assert (
        "min=PumpOperatingBaselines.MINIMUM_CONFIGURABLE_RPM"
        in flow_source
    )
    assert (
        "max=PumpOperatingBaselines.MAXIMUM_CONFIGURABLE_RPM"
        in flow_source
    )
    assert "step=10" in flow_source
    assert 'mode="box"' in flow_source

    for key in (
        "CONF_PUMP_FILTRATION_RPM",
        "CONF_PUMP_SOLAR_HEATING_RPM",
        "CONF_PUMP_GAS_HEATING_RPM",
        "CONF_PUMP_TEMPERATURE_PROBE_RPM",
        "CONF_PUMP_PRIMING_RPM",
        "CONF_PUMP_GRID_OUTAGE_RPM",
    ):
        assert key in flow_source
