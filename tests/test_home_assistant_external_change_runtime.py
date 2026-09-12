"""Behavioral tests for the command-free HA external-change event adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from poolos.integration import PhysicalHeatMode
from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.observations import ObservationQuality, PoolObservation
from poolos.physical_command_authority import (
    AutomaticThermalDispatchPurpose,
    ExpectedNativeConsequence,
    PhysicalCommandRequest,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppression,
    SpaAutomaticControlSuppressionSource,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "external_change_runtime.py"
PACKAGE_NAME = "poolos_external_change_runtime_behavior_test"


def _load_module() -> ModuleType:
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    homeassistant.core = core
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core

    package = ModuleType(PACKAGE_NAME)
    package.__path__ = [str(MODULE_PATH.parent)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package
    thermal_runtime = ModuleType(f"{PACKAGE_NAME}.thermal_runtime")
    thermal_runtime.PoolOSThermalRuntime = object
    sys.modules[f"{PACKAGE_NAME}.thermal_runtime"] = thermal_runtime

    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.external_change_runtime", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _native(
    at: datetime,
    *,
    pool_active: bool,
    spa_active: bool | None = None,
) -> NativeIntelliCenterObservationSnapshot:
    body_observations = [
        PoolObservation(
            "pool.active",
            pool_active,
            observed_at=at,
            source_id="B1101",
            quality=ObservationQuality.GOOD,
        )
    ]
    if spa_active is not None:
        body_observations.append(
            PoolObservation(
                "spa.active",
                spa_active,
                observed_at=at,
                source_id="B1202",
                quality=ObservationQuality.GOOD,
            )
        )
    return NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=(
            PoolObservation(
                "intellicenter.system_mode",
                "auto",
                observed_at=at,
                source_id="SYS01",
                quality=ObservationQuality.GOOD,
            ),
            *body_observations,
        ),
        missing_concepts=(),
    )


def test_runtime_publishes_one_stable_bounded_ha_event_after_baseline() -> None:
    module = _load_module()
    calls: list[tuple[str, dict[str, Any]]] = []
    hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_fire=lambda event_type, data: calls.append((event_type, data))
        )
    )
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=hass,
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=None,
            pool_resolved=False,
            hot_tub_resolved=False,
        ),
    )
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    transport = NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=now,
        connected=True,
        temperature_unit="°F",
    )

    runtime.process(_native(now, pool_active=False), transport, 1)
    assert calls == []
    assert authority.controller_mode == "auto"
    assert runtime.latest_batch.events == ()

    runtime.process(
        _native(now + timedelta(seconds=1), pool_active=True), transport, 1
    )
    assert len(calls) == 1
    event_type, data = calls[0]
    assert event_type == "poolos_external_change"
    assert data["concept"] == "pool.active"
    assert data["native_object_id"] == "B1101"
    assert data["external_policy"] == "accept"
    assert data["notification_recommended"] is True
    assert data["reconciliation_required"] is False
    assert "history" not in data

    runtime.process(
        _native(now + timedelta(seconds=2), pool_active=True), transport, 1
    )
    assert runtime.latest_batch.events[0].concept == "pool.active"
    assert len(calls) == 1

    runtime.process(
        _native(now + timedelta(seconds=3), pool_active=True), transport, 2
    )
    assert runtime.latest_batch.events == ()
    assert len(calls) == 1


def test_baseline_off_does_not_suppress_but_external_on_to_off_does() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    restraint = PoolAutomaticControlSuppression()
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=None,
            pool_resolved=False,
            hot_tub_resolved=False,
        ),
        pool_automatic_control=restraint,
    )
    now = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    transport = _transport(now)

    runtime.process(_native(now, pool_active=False), transport, 1)
    assert not restraint.state.suppressed
    runtime.process(_native(now + timedelta(seconds=1), pool_active=True), transport, 1)
    assert not restraint.state.suppressed
    runtime.process(_native(now + timedelta(seconds=2), pool_active=False), transport, 1)

    assert restraint.state.suppressed
    assert restraint.state.source is (
        PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF
    )
    assert restraint.state.suppressed_at == now + timedelta(seconds=2)
    assert runtime.latest_batch.events[0].concept == "pool.active"


def test_spa_on_to_off_suppression_is_independent_from_pool() -> None:
    module = _load_module()
    pool = PoolAutomaticControlSuppression()
    spa = SpaAutomaticControlSuppression()
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=PoolOSPhysicalCommandAuthority(),
        thermal_runtime=_thermal_runtime(
            module,
            assessment=None,
            pool_resolved=False,
            hot_tub_resolved=False,
        ),
        pool_automatic_control=pool,
        spa_automatic_control=spa,
    )
    now = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    transport = _transport(now)

    runtime.process(
        _native(now, pool_active=False, spa_active=False), transport, 1
    )
    runtime.process(
        _native(
            now + timedelta(seconds=1),
            pool_active=False,
            spa_active=True,
        ),
        transport,
        1,
    )
    runtime.process(
        _native(
            now + timedelta(seconds=2),
            pool_active=False,
            spa_active=False,
        ),
        transport,
        1,
    )

    assert spa.state.suppressed
    assert spa.state.source is SpaAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF
    assert not pool.state.suppressed


def test_spa_takeover_does_not_misclassify_routed_pool_off_as_manual_off() -> None:
    module = _load_module()
    pool = PoolAutomaticControlSuppression()
    spa = SpaAutomaticControlSuppression()
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=PoolOSPhysicalCommandAuthority(),
        thermal_runtime=_thermal_runtime(
            module,
            assessment=None,
            pool_resolved=False,
            hot_tub_resolved=False,
        ),
        pool_automatic_control=pool,
        spa_automatic_control=spa,
    )
    now = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    transport = _transport(now)

    runtime.process(
        _native(now, pool_active=True, spa_active=False), transport, 1
    )
    runtime.process(
        _native(
            now + timedelta(seconds=1),
            pool_active=False,
            spa_active=True,
        ),
        transport,
        1,
    )

    assert not pool.state.suppressed
    assert not spa.state.suppressed
    assert {event.concept for event in runtime.latest_batch.events} >= {
        "pool.active",
        "spa.active",
    }


def test_correlated_poolos_owned_cleanup_off_does_not_false_latch() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    authority.begin_automatic_thermal_epoch("cleanup-epoch")
    authority.register_automatic_thermal_cleanup(
        epoch_identity="cleanup-epoch",
        candidate_identity="cleanup-candidate",
        body="pool",
        purpose=AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        operation="body_active",
        target="B1101",
        requested_value=False,
    )
    context = authority.bind_automatic_thermal_dispatch(
        epoch_identity="cleanup-epoch",
        session_identity="cleanup-session",
        body="pool",
        purpose=AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        cleanup_candidate_identity="cleanup-candidate",
    )
    restraint = PoolAutomaticControlSuppression()
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=None,
            pool_resolved=False,
            hot_tub_resolved=False,
        ),
        pool_automatic_control=restraint,
    )
    now = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    transport = _transport(now)
    runtime.process(_native(now, pool_active=True), transport, 1)
    expectation = authority.reserve(
        PhysicalCommandRequest(
            operation="body_active",
            target="B1101",
            source=PhysicalRequestSource.AUTOMATIC_THERMAL,
            requested_value=False,
            automatic_thermal_context=context,
        ),
        ExpectedNativeConsequence("pool.active", "B1101", False),
        now=now + timedelta(milliseconds=500),
    )
    assert expectation is not None
    authority.mark_dispatch_started(expectation)

    runtime.process(_native(now + timedelta(seconds=1), pool_active=False), transport, 1)

    assert not restraint.state.suppressed
    assert runtime.latest_batch.events == ()
    assert len(runtime.latest_batch.correlated_consequences) == 1


def _body_assessment(
    module: ModuleType,
    *,
    active: bool,
    disposition: str,
    selected_source: str,
    rpm: int | None,
    evidence_usable: bool = True,
    technical_ready: bool = True,
    technical_blockers: tuple[str, ...] = (),
    evidence_blockers: tuple[str, ...] = (),
    requested_mode: str = "Solar",
) -> SimpleNamespace:
    return SimpleNamespace(
        body_active=active,
        requested_mode=module.ThermalRequestedMode(requested_mode),
        evidence_blockers=evidence_blockers,
        plan=SimpleNamespace(
            disposition=module.ThermalPlanDisposition(disposition),
            blocking_reasons=("blocked",) if disposition == "blocked" else (),
            desired=SimpleNamespace(
                selected_source=PhysicalHeatMode(selected_source),
                required_pump_rpm=rpm,
                evidence_usable=evidence_usable,
            ),
        ),
        technical_preflight=SimpleNamespace(
            ready=technical_ready,
            blocking_reasons=technical_blockers,
        ),
    )


def _thermal_runtime(
    module: ModuleType,
    *,
    assessment: object | None,
    pool_mode: str = "Solar",
    hot_tub_mode: str = "Solar Preferred",
    pool_resolved: bool = True,
    hot_tub_resolved: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        assessment=assessment,
        pool_requested_mode=module.ThermalRequestedMode(pool_mode),
        pool_requested_mode_resolved=pool_resolved,
        hot_tub_requested_mode=module.ThermalRequestedMode(hot_tub_mode),
        hot_tub_requested_mode_resolved=hot_tub_resolved,
    )


def _thermal_native(
    at: datetime,
    *,
    pool_heater: str | None = None,
    spa_heater: str | None = None,
    pump_rpm: int | None = None,
) -> NativeIntelliCenterObservationSnapshot:
    values = [("intellicenter.system_mode", "auto", "SYS01")]
    if pool_heater is not None:
        values.append(("pool.raw_heater_id", pool_heater, "B1101"))
    if spa_heater is not None:
        values.append(("spa.raw_heater_id", spa_heater, "B1202"))
    if pump_rpm is not None:
        values.append(("pump.rpm", pump_rpm, "PMP01"))
    return NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=tuple(
            PoolObservation(
                concept,
                value,
                observed_at=at,
                source_id=source_id,
                quality=ObservationQuality.GOOD,
            )
            for concept, value, source_id in values
        ),
        missing_concepts=(),
    )


def _transport(at: datetime) -> NativeIntelliCenterTransportSnapshot:
    return NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=at,
        connected=True,
        temperature_unit="°F",
    )


def test_pump_ownership_requires_usable_nonblocked_thermal_plan() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            pool_mode="Solar",
            hot_tub_mode="Gas",
            assessment=SimpleNamespace(
                pool=_body_assessment(
                    module,
                    active=True,
                    disposition="blocked",
                    selected_source="solar",
                    rpm=2900,
                    technical_ready=False,
                    technical_blockers=("authoritative_observations_not_fresh",),
                ),
                hot_tub=_body_assessment(
                    module,
                    active=True,
                    disposition="ready",
                    selected_source="gas",
                    rpm=3000,
                    evidence_usable=False,
                    evidence_blockers=("stale_native:spa.temperature",),
                ),
            ),
        ),
    )

    assert dict(runtime._ownership().intended_values) == {}

    runtime.thermal_runtime.assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=True,
            disposition="ready",
            selected_source="solar",
            rpm=2900,
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
        ),
    )
    assert dict(runtime._ownership().intended_values) == {
        "pump.rpm": 2900,
    }


def test_accepted_execution_intent_overrides_steady_state_planner_intent() -> None:
    """Priming uses accepted execution provenance, not the later Solar target."""

    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=SimpleNamespace(
                pool=_body_assessment(
                    module,
                    active=True,
                    disposition="ready",
                    selected_source="solar",
                    rpm=2900,
                ),
                hot_tub=_body_assessment(
                    module,
                    active=False,
                    disposition="already_converged",
                    selected_source="off",
                    rpm=None,
                ),
            ),
        ),
        owned_intent_provider=lambda: {"pump.rpm": 3000},
    )

    assert dict(runtime._ownership().intended_values)["pump.rpm"] == 3000

    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    runtime.process(
        _thermal_native(now, pump_rpm=2900),
        _transport(now),
        1,
    )
    runtime.process(
        _thermal_native(now + timedelta(seconds=1), pump_rpm=3000),
        _transport(now + timedelta(seconds=1)),
        1,
    )

    assert len(runtime.latest_batch.events) == 1
    assert runtime.latest_batch.events[0].concept == "pump.rpm"
    assert runtime.latest_batch.events[0].reconciliation_required is False
    assert runtime.diagnostics()["active_drift_count"] == 0


def test_conflicting_simultaneous_pump_claims_fail_closed_deterministically() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            pool_mode="Solar",
            hot_tub_mode="Gas",
            assessment=SimpleNamespace(
                pool=_body_assessment(
                    module,
                    active=True,
                    disposition="ready",
                    selected_source="solar",
                    rpm=2900,
                ),
                hot_tub=_body_assessment(
                    module,
                    active=True,
                    disposition="ready",
                    selected_source="gas",
                    rpm=3000,
                ),
            ),
        ),
    )

    ownership = dict(runtime._ownership().intended_values)
    assert "pump.rpm" not in ownership
    assert ownership == {}
    assert "conflicting_thermal_pump_ownership" in runtime.diagnostics()[
        "ownership_blockers"
    ]


def test_assessment_refresh_recomputes_drift_without_native_transition() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=True,
            disposition="ready",
            selected_source="solar",
            rpm=2900,
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
        ),
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(module, assessment=assessment),
    )
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    native = NativeIntelliCenterObservationSnapshot(
        generated_at=now,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=(
            PoolObservation(
                "intellicenter.system_mode",
                "auto",
                observed_at=now,
                source_id="SYS01",
                quality=ObservationQuality.GOOD,
            ),
            PoolObservation(
                "pump.rpm",
                2600,
                observed_at=now,
                source_id="PMP01",
                quality=ObservationQuality.GOOD,
            ),
            PoolObservation(
                "pool.raw_heater_id",
                "H0001",
                observed_at=now,
                source_id="B1101",
                quality=ObservationQuality.GOOD,
            ),
        ),
        missing_concepts=(),
    )
    transport = NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=now,
        connected=True,
        temperature_unit="°F",
    )

    runtime.process(native, transport, 1)
    assert runtime.diagnostics()["active_drift_count"] == 2

    runtime.thermal_runtime.assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
        hot_tub=assessment.hot_tub,
    )
    runtime.thermal_runtime.pool_requested_mode = (
        module.ThermalRequestedMode.SOLAR_PREFERRED
    )
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_count"] == 0

    runtime.thermal_runtime.assessment = assessment
    runtime.thermal_runtime.pool_requested_mode = module.ThermalRequestedMode.SOLAR
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_count"] == 2


def test_direct_solar_configuration_does_not_drift_when_planner_temporarily_selects_off() -> None:
    """Configured Solar remains H0002 when cold-roof policy selects no active heat."""
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    thermal_runtime = SimpleNamespace(
        assessment=SimpleNamespace(
            pool=_body_assessment(
                module,
                active=True,
                disposition="ready",
                selected_source="off",
                rpm=None,
                requested_mode="Solar",
            ),
            hot_tub=_body_assessment(
                module,
                active=False,
                disposition="already_converged",
                selected_source="off",
                rpm=None,
                requested_mode="Solar Preferred",
            ),
        ),
        pool_requested_mode=module.ThermalRequestedMode.SOLAR,
        pool_requested_mode_resolved=True,
        hot_tub_requested_mode=module.ThermalRequestedMode.SOLAR_PREFERRED,
        hot_tub_requested_mode_resolved=True,
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=thermal_runtime,
    )
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    native = NativeIntelliCenterObservationSnapshot(
        generated_at=now,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=(
            PoolObservation(
                "intellicenter.system_mode",
                "auto",
                observed_at=now,
                source_id="SYS01",
                quality=ObservationQuality.GOOD,
            ),
            PoolObservation(
                "pool.raw_heater_id",
                "H0002",
                observed_at=now,
                source_id="B1101",
                quality=ObservationQuality.GOOD,
            ),
        ),
        missing_concepts=(),
    )
    transport = NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=now,
        connected=True,
        temperature_unit="°F",
    )

    runtime.process(native, transport, 1)

    assert dict(runtime._ownership().intended_values) == {
        "pool.raw_heater_id": "H0002"
    }
    assert runtime.diagnostics()["active_drift_count"] == 0


@pytest.mark.parametrize(
    (
        "body",
        "requested_mode",
        "native_heater",
        "body_active",
        "expected_intended",
    ),
    (
        ("pool", "Solar", "H0002", True, None),
        ("pool", "Solar", "H0002", False, None),
        ("pool", "Solar", "H0001", True, "H0002"),
        ("pool", "Gas", "H0001", True, None),
        ("pool", "Gas", "H0002", False, "H0001"),
        ("pool", "Off", "00000", False, None),
        ("pool", "Off", "H0002", False, "00000"),
        ("spa", "Solar", "H0002", False, None),
        ("spa", "Gas", "H0001", False, None),
        ("spa", "Solar", "H0001", False, "H0002"),
        ("spa", "Gas", "H0002", False, "H0001"),
    ),
)
def test_direct_configured_mode_ownership_is_independent_of_operational_plan(
    body: str,
    requested_mode: str,
    native_heater: str,
    body_active: bool,
    expected_intended: str | None,
) -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    pool_mode = requested_mode if body == "pool" else "Solar Preferred"
    spa_mode = requested_mode if body == "spa" else "Solar Preferred"
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=body_active if body == "pool" else False,
            disposition="ready",
            selected_source="off",
            rpm=None,
            requested_mode=pool_mode,
        ),
        hot_tub=_body_assessment(
            module,
            active=body_active if body == "spa" else False,
            disposition="ready",
            selected_source="off",
            rpm=None,
            requested_mode=spa_mode,
        ),
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=assessment,
            pool_mode=pool_mode,
            hot_tub_mode=spa_mode,
        ),
    )
    now = datetime(2026, 9, 2, 13, 0, tzinfo=UTC)
    runtime.process(
        _thermal_native(
            now,
            pool_heater=native_heater if body == "pool" else None,
            spa_heater=native_heater if body == "spa" else None,
        ),
        _transport(now),
        1,
    )

    concept = f"{body}.raw_heater_id"
    ownership = dict(runtime._ownership().intended_values)
    assert ownership[concept] == {
        "Off": "00000",
        "Gas": "H0001",
        "Solar": "H0002",
    }[requested_mode]
    diagnostics = runtime.diagnostics()
    if expected_intended is None:
        assert concept not in diagnostics["active_drift_concepts"]
    else:
        assert diagnostics["active_drift_intended_values"][concept] == (
            expected_intended
        )


@pytest.mark.parametrize("native_heater", ("H0001", "H0002"))
def test_solar_preferred_has_no_static_configured_heater_ownership(
    native_heater: str,
) -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=True,
            disposition="ready",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=assessment,
            pool_mode="Solar Preferred",
        ),
    )
    now = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)
    runtime.process(
        _thermal_native(now, pool_heater=native_heater),
        _transport(now),
        1,
    )

    for planned_source in ("solar", "off", "solar", "off"):
        assessment.pool.plan.desired.selected_source = PhysicalHeatMode(
            planned_source
        )
        runtime.refresh_ownership()
        assert "pool.raw_heater_id" not in runtime._ownership().intended_values
        assert "pool.raw_heater_id" not in runtime.diagnostics()[
            "active_drift_concepts"
        ]


@pytest.mark.parametrize(
    ("requested_mode", "native_heater", "planned_sources"),
    (
        ("Solar", "H0002", ("solar", "off", "solar", "off")),
        ("Gas", "H0001", ("off", "gas", "off")),
    ),
)
def test_direct_configured_ownership_does_not_follow_planner_transitions(
    requested_mode: str,
    native_heater: str,
    planned_sources: tuple[str, ...],
) -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=True,
            disposition="ready",
            selected_source=planned_sources[0],
            rpm=None,
            requested_mode=requested_mode,
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(
            module,
            assessment=assessment,
            pool_mode=requested_mode,
        ),
    )
    now = datetime(2026, 9, 2, 14, 30, tzinfo=UTC)
    runtime.process(
        _thermal_native(now, pool_heater=native_heater),
        _transport(now),
        1,
    )

    for planned_source in planned_sources:
        assessment.pool.plan.desired.selected_source = PhysicalHeatMode(
            planned_source
        )
        runtime.refresh_ownership()
        assert runtime.diagnostics()["active_drift_count"] == 0


def test_requested_mode_changes_recompute_configured_drift_from_retained_truth() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
    )
    thermal_runtime = _thermal_runtime(module, assessment=assessment)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=thermal_runtime,
    )
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    runtime.process(
        _thermal_native(now, pool_heater="H0002"),
        _transport(now),
        1,
    )
    assert runtime.diagnostics()["active_drift_count"] == 0

    thermal_runtime.pool_requested_mode = module.ThermalRequestedMode.GAS
    assessment.pool.requested_mode = module.ThermalRequestedMode.GAS
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_intended_values"] == {
        "pool.raw_heater_id": "H0001"
    }

    runtime.process(
        _thermal_native(now + timedelta(seconds=1), pool_heater="H0001"),
        _transport(now + timedelta(seconds=1)),
        1,
    )
    assert runtime.diagnostics()["active_drift_count"] == 0

    thermal_runtime.pool_requested_mode = (
        module.ThermalRequestedMode.SOLAR_PREFERRED
    )
    assessment.pool.requested_mode = module.ThermalRequestedMode.SOLAR_PREFERRED
    runtime.refresh_ownership()
    assert "pool.raw_heater_id" not in runtime._ownership().intended_values

    thermal_runtime.pool_requested_mode = module.ThermalRequestedMode.SOLAR
    assessment.pool.requested_mode = module.ThermalRequestedMode.SOLAR
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_intended_values"] == {
        "pool.raw_heater_id": "H0002"
    }


def test_configured_ownership_waits_for_restore_and_native_baseline() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    assessment = SimpleNamespace(
        pool=_body_assessment(
            module,
            active=True,
            disposition="ready",
            selected_source="off",
            rpm=None,
        ),
        hot_tub=_body_assessment(
            module,
            active=False,
            disposition="already_converged",
            selected_source="off",
            rpm=None,
            requested_mode="Solar Preferred",
        ),
    )
    thermal_runtime = _thermal_runtime(
        module,
        assessment=assessment,
        pool_resolved=False,
        hot_tub_resolved=False,
    )
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=thermal_runtime,
    )
    now = datetime(2026, 9, 2, 16, 0, tzinfo=UTC)

    runtime.process(
        _thermal_native(now, pool_heater="H0001"),
        _transport(now),
        1,
    )
    assert "pool.raw_heater_id" not in runtime._ownership().intended_values
    assert runtime.diagnostics()["active_drift_count"] == 0

    thermal_runtime.pool_requested_mode_resolved = True
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_intended_values"] == {
        "pool.raw_heater_id": "H0002"
    }

    no_baseline_runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=_thermal_runtime(module, assessment=assessment),
    )
    assert (
        "pool.raw_heater_id"
        not in no_baseline_runtime._ownership().intended_values
    )
    no_baseline_runtime.refresh_ownership()
    assert no_baseline_runtime.diagnostics()["active_drift_count"] == 0
