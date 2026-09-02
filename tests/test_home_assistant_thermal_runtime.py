from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from poolos.integration import ThermalBody
from poolos.native_configuration_policy import (
    AutonomousCapability,
    NativeConfigurationGuard,
)
from poolos.thermal_live_execution import ThermalLiveCommissioningScope
from poolos.thermal_runtime_assessment import ThermalRequestedMode


NOW = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_class():
    package_name = "_poolos_phase3_runtime_test"
    module_name = f"{package_name}.thermal_runtime"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing.PoolOSThermalRuntime
    package = ModuleType(package_name)
    package.__path__ = []
    observation = ModuleType(f"{package_name}.observation")
    observation.ObservationSnapshot = object
    sys.modules[package_name] = package
    sys.modules[observation.__name__] = observation
    path = ROOT / "custom_components" / "poolos" / "thermal_runtime.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.PoolOSThermalRuntime


PoolOSThermalRuntime = _load_runtime_class()


@dataclass
class FakeManual:
    available: bool = True
    command_calls: list[object] = field(default_factory=list)


@dataclass
class FakeCoordinator:
    data: object
    native_intellicenter_snapshot: object
    independent_intellicenter_transport: object
    listener_updates: int = 0

    def health_incident_diagnostics(self) -> dict[str, bool]:
        return {
            "pending_confirmation": False,
            "unhealthy_seen_since_start": False,
        }

    def async_update_listeners(self) -> None:
        self.listener_updates += 1


def _native_values() -> dict[str, object]:
    return {
        "pool.active": True,
        "pool.temperature": 80.0,
        "pool.target_temperature": 90.0,
        "pool.raw_heater_id": "H0002",
        "pool.raw_htmode": "0",
        "spa.active": False,
        "spa.temperature": 96.0,
        "spa.target_temperature": 101.0,
        "spa.raw_heater_id": "00000",
        "spa.raw_htmode": "0",
        "pump.rpm": 2900,
        "solar.temperature": 110.0,
        "solar.active": False,
    }


def runtime_fixture(*, raw_inventory: tuple[object, ...] = ()):
    observations = tuple(
        SimpleNamespace(observation_id=key, value=value, source_id=f"native:{key}")
        for key, value in _native_values().items()
    )
    native = SimpleNamespace(
        observations=observations,
        missing_concepts=(),
        available=True,
    )
    transport_snapshot = SimpleNamespace(
        bodies=(SimpleNamespace(selected_heat_mode=None),),
        raw_inventory=raw_inventory,
    )
    coordinator = FakeCoordinator(
        data=SimpleNamespace(generated_at=NOW, healthy=True, stale_entities=()),
        native_intellicenter_snapshot=native,
        independent_intellicenter_transport=SimpleNamespace(
            latest_snapshot=transport_snapshot
        ),
    )
    manual = FakeManual()
    runtime = PoolOSThermalRuntime(coordinator, manual)
    runtime.refresh()
    return runtime, coordinator, manual


def test_first_install_and_every_new_runtime_start_effectively_disabled() -> None:
    first, _, _ = runtime_fixture()
    first.set_effective_live_enabled(True)
    first.set_commissioning_scope(ThermalLiveCommissioningScope.POOL)
    restarted, _, _ = runtime_fixture()

    assert first.effective_live_enabled
    assert restarted.effective_live_enabled is False
    assert restarted.commissioning_scope is ThermalLiveCommissioningScope.DISABLED


def test_config_and_refresh_paths_recompute_only_and_never_call_manual_setters() -> None:
    runtime, coordinator, manual = runtime_fixture()

    runtime.set_effective_live_enabled(True)
    runtime.set_commissioning_scope(ThermalLiveCommissioningScope.POOL)
    runtime.set_requested_mode(ThermalBody.POOL, ThermalRequestedMode.GAS)
    runtime.refresh(publish=True)

    assert coordinator.listener_updates == 4
    assert manual.command_calls == []
    assert runtime.assessment is not None
    assert runtime.assessment.pool.actual_authorization.authorized


def test_assessment_observer_runs_for_requested_intent_changes() -> None:
    runtime, _, manual = runtime_fixture()
    calls: list[object] = []
    runtime.set_assessment_observer(lambda: calls.append(runtime.assessment))

    runtime.set_requested_mode(
        ThermalBody.POOL,
        ThermalRequestedMode.GAS,
        publish=False,
    )

    assert len(calls) == 1
    assert calls[0] is runtime.assessment
    assert manual.command_calls == []


def test_requested_mode_comes_directly_from_runtime_not_ha_state_lookup() -> None:
    runtime, _, _ = runtime_fixture()

    runtime.set_requested_mode(
        ThermalBody.HOT_TUB,
        ThermalRequestedMode.SOLAR_PREFERRED,
        publish=False,
    )

    assert runtime.hot_tub_requested_mode is ThermalRequestedMode.SOLAR_PREFERRED
    source = (ROOT / "custom_components" / "poolos" / "thermal_runtime.py").read_text()
    assert "hass.states" not in source
    assert "get_state" not in source


def test_native_assignment_extraction_displays_nonthermal_conflict_without_authority() -> None:
    spillway = SimpleNamespace(
        object_type="PMPCIRC",
        native_id="p0999",
        name="Spillway",
        subtype=None,
        attributes=(SimpleNamespace(name="RPM", value="2900"),),
    )
    runtime, _, _ = runtime_fixture(raw_inventory=(spillway,))
    runtime.set_requested_mode(
        ThermalBody.POOL,
        ThermalRequestedMode.GAS,
        publish=False,
    )

    assert runtime.assessment is not None
    assert "native_rpm_assignment_conflict" in runtime.assessment.native_conflict_codes
    assert runtime.assessment.pool.technical_preflight.ready
    configuration = NativeConfigurationGuard().evaluate(
        runtime._native_configuration_input()
    )
    assert AutonomousCapability.SPILLWAY_PUMP_BASELINE in (
        configuration.disabled_capabilities
    )


def test_phase_three_ha_runtime_contains_no_execution_or_delivery_invocation() -> None:
    source = (ROOT / "custom_components" / "poolos" / "thermal_runtime.py").read_text()

    for prohibited in (
        "ThermalLiveExecutionEngine",
        "deliver_current_step",
        "ManualIntelliCenterThermalLiveDelivery",
        "async_set_body_heat_source",
        "async_set_pump_circuit_speed",
        "hass.services",
        "asyncio.sleep",
    ):
        assert prohibited not in source


def test_ha_entities_expose_exact_safe_configuration_contracts() -> None:
    switch = (ROOT / "custom_components" / "poolos" / "switch.py").read_text()
    select = (ROOT / "custom_components" / "poolos" / "select.py").read_text()

    assert "PoolOSThermalLiveExecutionSwitch" in switch
    assert "effective_state_resets_off_on_restart" in switch
    assert "RestoreEntity" not in switch.split(
        "class PoolOSThermalLiveExecutionSwitch", 1
    )[1].split("class ", 1)[0]
    assert '"Disabled": ThermalLiveCommissioningScope.DISABLED' in select
    assert '"Pool": ThermalLiveCommissioningScope.POOL' in select
    assert '"Hot Tub": ThermalLiveCommissioningScope.HOT_TUB' in select


def test_configuration_refresh_never_regresses_stateful_policy_timestamp() -> None:
    runtime, coordinator, manual = runtime_fixture()
    newer = SimpleNamespace(
        generated_at=NOW + timedelta(seconds=1),
        healthy=True,
        stale_entities=(),
    )

    runtime.refresh(newer)
    runtime.set_commissioning_scope(ThermalLiveCommissioningScope.POOL)

    assert runtime.assessment is not None
    assert runtime.assessment.generated_at == newer.generated_at
    assert runtime.last_error is None
    assert manual.command_calls == []
    assert coordinator.listener_updates == 1


def test_runtime_evaluation_error_retains_bounded_sanitized_reason() -> None:
    runtime, _, manual = runtime_fixture()

    class FailingEvaluator:
        def evaluate(self, evidence, *, live_policy):
            del evidence, live_policy
            raise ValueError("unsafe\nreason " + "x" * 2000)

    runtime.evaluator = FailingEvaluator()
    runtime.refresh()

    assert runtime.assessment is None
    assert runtime.last_error is not None
    assert runtime.last_error.startswith(
        "thermal_runtime_evaluation_failed:ValueError:unsafe reason"
    )
    assert "\n" not in runtime.last_error
    assert len(runtime.last_error) <= 320
    assert manual.command_calls == []
