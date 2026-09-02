"""Behavioral tests for the command-free HA external-change event adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.observations import ObservationQuality, PoolObservation
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority


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


def _native(at: datetime, *, pool_active: bool) -> NativeIntelliCenterObservationSnapshot:
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
            PoolObservation(
                "pool.active",
                pool_active,
                observed_at=at,
                source_id="B1101",
                quality=ObservationQuality.GOOD,
            ),
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
        thermal_runtime=SimpleNamespace(assessment=None),
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
                selected_source=module.PhysicalHeatMode(selected_source),
                required_pump_rpm=rpm,
                evidence_usable=evidence_usable,
            ),
        ),
        technical_preflight=SimpleNamespace(
            ready=technical_ready,
            blocking_reasons=technical_blockers,
        ),
    )


def test_ownership_requires_usable_nonblocked_thermal_plan() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=SimpleNamespace(
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
            )
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
        "pool.raw_heater_id": "H0002",
        "pump.rpm": 2900,
    }


def test_conflicting_simultaneous_pump_claims_fail_closed_deterministically() -> None:
    module = _load_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    runtime = module.PoolOSExternalChangeRuntime(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None)),
        authority=authority,
        thermal_runtime=SimpleNamespace(
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
            )
        ),
    )

    ownership = dict(runtime._ownership().intended_values)
    assert "pump.rpm" not in ownership
    assert ownership == {
        "pool.raw_heater_id": "H0002",
        "spa.raw_heater_id": "H0001",
    }
    assert runtime.diagnostics()["ownership_blockers"] == [
        "conflicting_thermal_pump_ownership"
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
        thermal_runtime=SimpleNamespace(assessment=assessment),
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
            requested_mode="Off",
        ),
        hot_tub=assessment.hot_tub,
    )
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_count"] == 0

    runtime.thermal_runtime.assessment = assessment
    runtime.refresh_ownership()
    assert runtime.diagnostics()["active_drift_count"] == 2
