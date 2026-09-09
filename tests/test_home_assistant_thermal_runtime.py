from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from poolos.filtration_policy import FiltrationDisposition
from poolos.integration import SetPumpSpeed, ThermalBody
from poolos.native_configuration_policy import (
    AutonomousCapability,
    NativeConfigurationGuard,
)
from poolos.thermal_live_execution import ThermalLiveCommissioningScope
from poolos.thermal_runtime_assessment import ThermalRequestedMode
from poolos.observations import ObservationQuality


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


def _load_filtration_runtime_class():
    package_name = "_poolos_phase3_runtime_test"
    module_name = f"{package_name}.filtration_runtime"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing.PoolOSFiltrationRuntime
    path = ROOT / "custom_components" / "poolos" / "filtration_runtime.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.PoolOSFiltrationRuntime


PoolOSFiltrationRuntime = _load_filtration_runtime_class()


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
        "pool.pump_circuit.configured_speed_rpm": 2900,
        "spa.pump_circuit.configured_speed_rpm": 2600,
        "solar.temperature": 110.0,
        "solar.active": False,
        "heater.active": False,
    }


def runtime_fixture(
    *,
    raw_inventory: tuple[object, ...] = (),
    pool_pmpcirc_id: str = "p0102",
):
    observations = tuple(
        SimpleNamespace(observation_id=key, value=value, source_id=f"native:{key}")
        for key, value in _native_values().items()
    )
    native = SimpleNamespace(
        observations=observations,
        missing_concepts=(),
        available=True,
    )
    pool_pmpcirc = SimpleNamespace(
        object_type="PMPCIRC",
        native_id=pool_pmpcirc_id,
        observed_at=NOW,
        name="Pool",
        subtype=None,
        attributes=(
            SimpleNamespace(name="CIRCUIT", value="C0006"),
            SimpleNamespace(name="SELECT", value="RPM"),
            SimpleNamespace(name="PARENT", value="PMP01"),
            SimpleNamespace(name="SPEED", value="2900"),
        ),
    )
    spa_pmpcirc = SimpleNamespace(
        object_type="PMPCIRC",
        native_id="p0198",
        observed_at=NOW,
        name="Spa",
        subtype=None,
        attributes=(
            SimpleNamespace(name="CIRCUIT", value="C0001"),
            SimpleNamespace(name="SELECT", value="RPM"),
            SimpleNamespace(name="PARENT", value="PMP01"),
            SimpleNamespace(name="SPEED", value="2600"),
        ),
    )
    transport_snapshot = SimpleNamespace(
        connected=True,
        bodies=(SimpleNamespace(selected_heat_mode=None),),
        pumps=(
            SimpleNamespace(
                native_id="PMP01",
                minimum_rpm=450.0,
                maximum_rpm=3450.0,
            ),
        ),
        observed_at=NOW,
        raw_inventory=(*raw_inventory, pool_pmpcirc, spa_pmpcirc),
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


def _publish_runtime_frame(
    runtime,
    coordinator: FakeCoordinator,
    filtration_runtime,
    *,
    at: datetime,
    values: dict[str, object],
) -> None:
    observations = tuple(
        SimpleNamespace(
            observation_id=key,
            value=value,
            source_id=f"native:{key}",
            observed_at=at,
            quality=ObservationQuality.GOOD,
        )
        for key, value in values.items()
    )
    snapshot = SimpleNamespace(
        generated_at=at,
        observations=observations,
        stale_entities=(),
        healthy=True,
    )
    coordinator.data = snapshot
    coordinator.native_intellicenter_snapshot.observations = observations
    filtration_runtime.refresh(snapshot)
    runtime.refresh(snapshot)


def test_runtime_binds_current_recycled_pool_pmpcirc_into_assessment() -> None:
    runtime, _, _ = runtime_fixture(pool_pmpcirc_id="p0101")

    assert runtime.assessment is not None
    assert runtime.assessment.pool_pump_circuit_id == "p0101"
    assert runtime.assessment.spa_pump_circuit_id == "p0198"
    assert all(
        operation.equipment_id == "p0101"
        for operation in runtime.assessment.pool.plan.operations
        if isinstance(operation, SetPumpSpeed)
    )


def test_runtime_passes_deferrable_filtration_as_non_immediate_thermal_evidence() -> None:
    runtime, coordinator, manual = runtime_fixture()
    coordinator.native_intellicenter_snapshot.observations = tuple(
        SimpleNamespace(
            observation_id=item.observation_id,
            value=(
                90.0
                if item.observation_id == "pool.temperature"
                else (
                    80.0
                    if item.observation_id == "solar.temperature"
                    else item.value
                )
            ),
            source_id=item.source_id,
        )
        for item in coordinator.native_intellicenter_snapshot.observations
    )
    runtime.filtration_runtime = SimpleNamespace(
        assessment=SimpleNamespace(
            disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
            independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
            immediate_circulation_required=False,
            total_remaining_runtime=timedelta(hours=5),
        )
    )

    runtime.refresh()

    assert runtime.assessment is not None
    desired = runtime.assessment.pool.plan.desired
    assert desired.required_pump_rpm is None
    assert desired.evidence["current_operating_purpose"] == "ordinary_circulation"
    assert desired.evidence["filtration_immediate_circulation_required"] is False
    assert manual.command_calls == []
    assert all(
        operation.equipment_id == "p0198"
        for operation in runtime.assessment.hot_tub.plan.operations
        if isinstance(operation, SetPumpSpeed)
    )


def test_runtime_does_not_treat_crediting_as_independent_successor_need() -> None:
    """Incidental Solar credit cannot perpetuate Pool circulation."""

    runtime, coordinator, manual = runtime_fixture()
    coordinator.native_intellicenter_snapshot.observations = tuple(
        SimpleNamespace(
            observation_id=item.observation_id,
            value=(
                90.0
                if item.observation_id == "pool.temperature"
                else (
                    80.0
                    if item.observation_id == "solar.temperature"
                    else item.value
                )
            ),
            source_id=item.source_id,
        )
        for item in coordinator.native_intellicenter_snapshot.observations
    )
    runtime.filtration_runtime = SimpleNamespace(
        assessment=SimpleNamespace(
            disposition=FiltrationDisposition.CREDITING,
            independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
            immediate_circulation_required=False,
            total_remaining_runtime=timedelta(hours=5),
        )
    )

    runtime.refresh()

    assert runtime.assessment is not None
    desired = runtime.assessment.pool.plan.desired
    assert desired.required_pump_rpm is None
    assert desired.evidence["current_operating_purpose"] == "ordinary_circulation"
    assert desired.evidence["filtration_immediate_circulation_required"] is False
    assert manual.command_calls == []


def test_runtime_retains_crediting_when_independent_policy_is_run_now() -> None:
    """Incidental credit may continue when policy independently requires it now."""

    runtime, coordinator, manual = runtime_fixture()
    coordinator.native_intellicenter_snapshot.observations = tuple(
        SimpleNamespace(
            observation_id=item.observation_id,
            value=(
                90.0
                if item.observation_id == "pool.temperature"
                else (
                    80.0
                    if item.observation_id == "solar.temperature"
                    else item.value
                )
            ),
            source_id=item.source_id,
        )
        for item in coordinator.native_intellicenter_snapshot.observations
    )
    runtime.filtration_runtime = SimpleNamespace(
        assessment=SimpleNamespace(
            disposition=FiltrationDisposition.CREDITING,
            independent_disposition=FiltrationDisposition.RUN_NOW,
            immediate_circulation_required=True,
            total_remaining_runtime=timedelta(hours=5),
        )
    )

    runtime.refresh()

    assert runtime.assessment is not None
    desired = runtime.assessment.pool.plan.desired
    assert desired.required_pump_rpm == 2600
    assert desired.evidence["filtration_immediate_circulation_required"] is True
    assert manual.command_calls == []


def test_solar_end_crediting_transition_uses_filtration_counterfactual() -> None:
    """HA filtration truth prevents transient CREDITING from self-perpetuating."""

    runtime, coordinator, manual = runtime_fixture()
    filtration_runtime = PoolOSFiltrationRuntime(coordinator=SimpleNamespace())
    runtime.filtration_runtime = filtration_runtime

    solar = _native_values()
    solar.update(
        {
            "pool.temperature": 82.0,
            "pool.target_temperature": 83.0,
            "pool.raw_heater_id": "H0002",
            "pump.rpm": 2900,
            "solar.active": True,
        }
    )
    _publish_runtime_frame(
        runtime,
        coordinator,
        filtration_runtime,
        at=NOW + timedelta(seconds=1),
        values=solar,
    )
    assert filtration_runtime.assessment is not None
    assert filtration_runtime.assessment.disposition is FiltrationDisposition.CREDITING

    ended = dict(solar)
    ended.update(
        {
            "pool.temperature": 84.0,
            "pool.raw_heater_id": "00000",
            "solar.active": False,
        }
    )
    _publish_runtime_frame(
        runtime,
        coordinator,
        filtration_runtime,
        at=NOW + timedelta(seconds=2),
        values=ended,
    )
    assert filtration_runtime.assessment is not None
    assert filtration_runtime.assessment.disposition is FiltrationDisposition.CREDITING
    assert (
        filtration_runtime.assessment.independent_disposition
        is FiltrationDisposition.DEFERRED_TOU
    )
    assert runtime.assessment is not None
    assert runtime.assessment.pool.plan.desired.required_pump_rpm is None

    _publish_runtime_frame(
        runtime,
        coordinator,
        filtration_runtime,
        at=NOW + timedelta(seconds=3),
        values=ended,
    )
    assert runtime.assessment is not None
    assert runtime.assessment.pool.plan.desired.required_pump_rpm is None
    assert manual.command_calls == []


def test_solar_end_crediting_transition_retains_independent_run_now() -> None:
    runtime, coordinator, manual = runtime_fixture()
    filtration_runtime = PoolOSFiltrationRuntime(coordinator=SimpleNamespace())
    runtime.filtration_runtime = filtration_runtime
    catchup = NOW + timedelta(hours=7)
    solar = _native_values()
    solar.update(
        {
            "pool.temperature": 82.0,
            "pool.target_temperature": 83.0,
            "pool.raw_heater_id": "H0002",
            "pump.rpm": 2900,
            "solar.active": True,
        }
    )
    _publish_runtime_frame(
        runtime,
        coordinator,
        filtration_runtime,
        at=catchup + timedelta(seconds=1),
        values=solar,
    )

    ended = dict(solar)
    ended.update(
        {
            "pool.temperature": 84.0,
            "pool.raw_heater_id": "00000",
            "solar.active": False,
        }
    )
    _publish_runtime_frame(
        runtime,
        coordinator,
        filtration_runtime,
        at=catchup + timedelta(seconds=2),
        values=ended,
    )

    assert filtration_runtime.assessment is not None
    assert filtration_runtime.assessment.disposition is FiltrationDisposition.CREDITING
    assert (
        filtration_runtime.assessment.independent_disposition
        is FiltrationDisposition.RUN_NOW
    )
    assert runtime.assessment is not None
    assert runtime.assessment.pool.plan.desired.required_pump_rpm == 2600
    assert manual.command_calls == []


def test_first_install_and_every_new_runtime_start_effectively_disabled() -> None:
    first, _, _ = runtime_fixture()
    assert first.pool_requested_mode_resolved is False
    assert first.hot_tub_requested_mode_resolved is False
    first.set_effective_live_enabled(True)
    first.set_commissioning_scope(ThermalLiveCommissioningScope.POOL)
    restarted, _, _ = runtime_fixture()

    assert first.effective_live_enabled
    assert restarted.effective_live_enabled is False
    assert restarted.commissioning_scope is ThermalLiveCommissioningScope.DISABLED


def test_requested_mode_resolution_is_body_specific_and_explicit() -> None:
    runtime, _, _ = runtime_fixture()

    runtime.set_requested_mode(
        ThermalBody.POOL,
        ThermalRequestedMode.SOLAR,
        publish=False,
    )
    assert runtime.pool_requested_mode_resolved is True
    assert runtime.hot_tub_requested_mode_resolved is False

    runtime.set_requested_mode(
        ThermalBody.HOT_TUB,
        ThermalRequestedMode.SOLAR_PREFERRED,
        publish=False,
    )
    assert runtime.hot_tub_requested_mode_resolved is True


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


def test_orchestration_observer_receives_existing_snapshot_and_assessment() -> None:
    runtime, coordinator, manual = runtime_fixture()
    calls: list[tuple[object, object]] = []
    runtime.set_orchestration_observer(
        lambda snapshot, assessment: calls.append((snapshot, assessment))
    )

    runtime.set_requested_mode(
        ThermalBody.POOL,
        ThermalRequestedMode.GAS,
        publish=False,
    )

    assert calls == [(coordinator.data, runtime.assessment)]
    assert manual.command_calls == []


def test_orchestration_failure_does_not_suppress_thermal_publication() -> None:
    runtime, coordinator, manual = runtime_fixture()

    def fail(_snapshot: object, _assessment: object) -> None:
        raise RuntimeError("diagnostic failure")

    runtime.set_orchestration_observer(fail)
    runtime.set_requested_mode(ThermalBody.POOL, ThermalRequestedMode.GAS)

    assert runtime.assessment is not None
    assert runtime.assessment.pool.requested_mode is ThermalRequestedMode.GAS
    assert coordinator.listener_updates == 1
    assert manual.command_calls == []


def test_orchestration_failure_invokes_fail_closed_observer() -> None:
    runtime, coordinator, manual = runtime_fixture()
    failures: list[tuple[object, Exception]] = []

    def fail(_snapshot: object, _assessment: object) -> None:
        raise RuntimeError("orchestration failure")

    runtime.set_orchestration_observer(fail)
    runtime.set_orchestration_failure_observer(
        lambda snapshot, error: failures.append((snapshot, error))
    )
    runtime.set_requested_mode(ThermalBody.POOL, ThermalRequestedMode.GAS)

    assert len(failures) == 1
    assert failures[0][0] is coordinator.data
    assert isinstance(failures[0][1], RuntimeError)
    assert runtime.assessment is not None
    assert coordinator.listener_updates == 1
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
    assert "commissioned_desired_state_persists_across_restart" in switch
    assert "RestoreEntity" in switch.split(
        "class PoolOSThermalLiveExecutionSwitch", 1
    )[1].split("class ", 1)[0]
    assert '"Disabled": ThermalLiveCommissioningScope.DISABLED' in select
    assert '"Pool": ThermalLiveCommissioningScope.POOL' in select
    assert '"Hot Tub": ThermalLiveCommissioningScope.HOT_TUB' in select
    assert "PoolOSThermalAutomaticExecutionSwitch" in switch
    automatic = switch.split(
        "class PoolOSThermalAutomaticExecutionSwitch", 1
    )[1].split("class ", 1)[0]
    assert "RestoreEntity" in automatic
    assert "fresh_authoritative_epoch_required" in automatic
    assert "physical_session_ownership_restored" in automatic


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
