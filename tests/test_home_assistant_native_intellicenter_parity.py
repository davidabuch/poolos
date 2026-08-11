"""HA shadow-publication and isolation contracts for PoolOS milestone 12.0A."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import inspect

import yaml

from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter
from poolos.daily_retrospective import DailyOperationalRetrospectiveEngine
from poolos.multiday_commissioning import MultiDayCommissioningIntelligence
from poolos.observation_parity import ObservationParityEngine
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"
DASHBOARD = ROOT / "dashboards" / "poolos_control_center.yaml"
NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)

_SPEC = importlib.util.spec_from_file_location(
    "poolos_test_native_intellicenter", COMPONENT / "native_intellicenter.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
native_transport_snapshot = _MODULE.native_transport_snapshot


def test_reference_protocol_snapshot_is_copied_without_controller_or_entities() -> None:
    reference = SimpleNamespace(
        connected=True,
        observed_at=NOW,
        temperature_unit="°F",
        bodies=(
            SimpleNamespace(
                id="B1",
                name="Pool",
                body_type=SimpleNamespace(value="pool"),
                is_on=True,
                heating_active=False,
                current_temperature=82,
                target_temperature=86,
            ),
        ),
        pumps=(),
        temperature_sensors=(),
        circuits=(),
    )
    transport = native_transport_snapshot(
        reference,
        source_id="intellicenter_protocol:test",
        fallback_observed_at=NOW,
    )
    canonical = NativeIntelliCenterReadAdapter().map_snapshot(
        transport, generated_at=NOW
    )
    assert canonical.available is True
    assert {item.observation_id for item in canonical.observations} >= {
        "pool.active",
        "pool.heating_demand_active",
        "pool.temperature",
        "pool.target_temperature",
        "heater.active",
    }
    assert not hasattr(transport, "controller")
    assert not hasattr(transport, "hass")


def test_native_shadow_cannot_affect_authoritative_commissioning_inputs() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    observe = coordinator.split("async def _async_observe", 1)[1].split(
        "def _refresh_native_intellicenter_parity", 1
    )[0]

    assert "snapshot = build_snapshot(" in observe
    assert "self._refresh_native_intellicenter_parity(" in observe
    assert "snapshot, observed_at=observed_at" in observe
    assert "self.shadow_runtime.evaluate(snapshot)" in observe
    assert "observations=snapshot.observations" in observe
    assert '"healthy": snapshot.healthy' in observe
    assert "native.observations" not in observe
    assert "native" not in inspect.signature(
        DailyOperationalRetrospectiveEngine.generate
    ).parameters
    assert "native" not in inspect.signature(
        MultiDayCommissioningIntelligence.generate
    ).parameters


def test_native_failure_is_isolated_and_startup_is_not_an_alarm() -> None:
    coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assert 'reason_code="REFERENCE_SOURCE_NOT_CONFIGURED"' in coordinator
    assert 'reason_code="REFERENCE_SNAPSHOT_INVALID"' in coordinator
    assert "self.native_intellicenter_parity_report = None" in coordinator
    assert 'reason_code="NATIVE_SHADOW_FAILURE"' in coordinator
    assert "Defensive isolation for a non-authoritative shadow source" in coordinator
    assert "if self.in_startup_health_grace(observed_at)" in coordinator
    assert "native_source_available=native.available" in coordinator


def test_ha_diagnostics_are_compact_and_dashboard_exposes_four_entities() -> None:
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    yaml.safe_load(dashboard)
    for key in (
        "native_intellicenter_status",
        "native_intellicenter_parity",
        "native_intellicenter_matched_concepts",
        "native_intellicenter_mismatches",
    ):
        assert f'"{key}"' in sensor
        assert f"sensor.poolos_control_center_{key}" in dashboard
    assert "include_details=False" in sensor
    assert '"issue_concepts"' in sensor

    observations = tuple(
        PoolObservation(
            observation_id=f"concept.{index:02d}",
            value=index,
            observed_at=NOW,
            source_kind=ObservationSourceKind.LIVE,
            source_id=f"source:{index}",
            quality=ObservationQuality.GOOD,
        )
        for index in range(22)
    )
    report = ObservationParityEngine().compare(
        observations,
        (),
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=False,
    )
    compact = {
        **report.to_dict(include_details=False),
        "issue_concepts": [
            {"concept": item.concept, "status": item.status.value}
            for item in report.details
        ],
    }
    assert len(json.dumps(compact).encode("utf-8")) < 4_000


def test_new_ha_path_has_no_services_commands_or_delivery() -> None:
    combined = "\n".join(
        (COMPONENT / name).read_text(encoding="utf-8").lower()
        for name in ("native_intellicenter.py", "coordinator.py", "sensor.py")
    )
    for prohibited in (
        "hass.services",
        "async_call",
        "turn_on",
        "turn_off",
        "set_temperature",
        "set_speed",
        "command delivery",
        "physical equipment control",
    ):
        assert prohibited not in combined
