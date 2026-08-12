"""Native IntelliCenter read-only adapter contracts for milestone 12.0A."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poolos.intellicenter_readonly import (
    NATIVE_TARGET_CONCEPTS,
    NativeBodyKind,
    NativeBodyState,
    NativeCircuitState,
    NativeIntelliCenterReadAdapter,
    NativeIntelliCenterReadError,
    NativeIntelliCenterStatus,
    NativeIntelliCenterTransportSnapshot,
    NativePumpState,
    NativeRawAttribute,
    NativeRawObject,
    NativeTemperatureKind,
    NativeTemperatureState,
)
from poolos.observations import ObservationQuality

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def transport(*, connected: bool = True) -> NativeIntelliCenterTransportSnapshot:
    return NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=connected,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                True,
                True,
                82.0,
                86.0,
                active_heat_source="gas",
            ),
            NativeBodyState("B1201", "Spa", NativeBodyKind.SPA, False, False, 80.0, 100.0),
        ),
        pumps=(NativePumpState("PMP01", "Filter Pump", True, 2200.0, 42.0, 1234.0),),
        temperatures=(
            NativeTemperatureState("S01", "Air", NativeTemperatureKind.AIR, 78.0),
            NativeTemperatureState("S02", "Solar", NativeTemperatureKind.SOLAR, 101.0),
            NativeTemperatureState("S03", "Water", NativeTemperatureKind.WATER, 82.0),
        ),
        circuits=(
            NativeCircuitState("C01", "Pool", True),
            NativeCircuitState("C02", "Spa", False),
            NativeCircuitState("C03", "Solar", True),
            NativeCircuitState("C04", "Solar Preferred", True),
            NativeCircuitState("C05", "Waterfall", False),
            NativeCircuitState("C06", "Jets", False),
            NativeCircuitState("C07", "Slide", True),
        ),
    )


def test_native_models_are_immutable_and_adapter_surface_is_read_only() -> None:
    snapshot = transport()
    with pytest.raises(FrozenInstanceError):
        snapshot.connected = False  # type: ignore[misc]

    public = {name for name in dir(NativeIntelliCenterReadAdapter) if not name.startswith("_")}
    assert public == {"capture", "initializing", "map_snapshot", "unavailable"}
    assert not any(
        fragment in name
        for name in public
        for fragment in ("command", "write", "set", "toggle", "send", "control")
    )


def test_maps_supported_concepts_with_distinct_native_provenance() -> None:
    result = NativeIntelliCenterReadAdapter().map_snapshot(
        transport(), generated_at=NOW
    )
    values = {item.observation_id: item for item in result.observations}

    assert result.status is NativeIntelliCenterStatus.AVAILABLE
    assert result.missing_concepts == ()
    assert values["pool.active"].value is True
    assert values["pool.heating_demand_active"].value is True
    assert values["pump.rpm"].value == 2200.0
    assert values["pump.gpm"].value == 42.0
    assert values["pump.power"].value == 1234.0
    assert values["solar.temperature"].value == 101.0
    assert values["solar_preferred.active"].value is True
    assert values["slide.active"].value is True
    assert values["heater.active"].value is True
    assert all(item.quality is ObservationQuality.GOOD for item in values.values())
    assert all(
        item.source_id is not None
        and item.source_id.startswith("intellicenter_native:panel-main:")
        for item in values.values()
    )
    assert all("home_assistant" not in (item.source_id or "") for item in values.values())


def test_missing_native_values_remain_explicitly_missing() -> None:
    empty = NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
    )
    result = NativeIntelliCenterReadAdapter().map_snapshot(empty, generated_at=NOW)
    assert result.observations == ()
    assert result.missing_concepts == NATIVE_TARGET_CONCEPTS
    assert result.available is True


def test_raw_discovery_inventory_is_immutable_deterministic_and_bounded() -> None:
    raw = tuple(
        NativeRawObject(
            native_id=f"OBJ{index:03d}",
            object_type="MYSTERY" if index == 0 else "CIRCUIT",
            subtype="FEATURE",
            name=f"Object {index}",
            parent_id="PANEL1",
            observed_at=NOW,
            attributes=tuple(
                NativeRawAttribute(f"ATTR{attribute:02d}", f"value-{attribute}")
                for attribute in range(20)
            ),
        )
        for index in reversed(range(30))
    )
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="direct-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        raw_inventory=raw,
    )

    diagnostics = dict(snapshot.raw_inventory_diagnostics())

    assert snapshot.raw_inventory[0].native_id == "OBJ001"
    assert snapshot.raw_inventory[-1].object_type == "MYSTERY"
    assert diagnostics["total_native_object_count"] == 30
    assert diagnostics["count_by_native_object_type"] == {
        "CIRCUIT": 29,
        "MYSTERY": 1,
    }
    assert diagnostics["displayed_native_object_count"] == 20
    assert diagnostics["inventory_truncated"] is True
    assert diagnostics["raw_inventory"][0]["attribute_count"] == 20
    assert len(diagnostics["raw_inventory"][0]["attribute_names"]) == 16
    with pytest.raises(FrozenInstanceError):
        snapshot.raw_inventory[0].name = "changed"  # type: ignore[misc]


def test_metric_temperatures_are_normalized_to_canonical_fahrenheit() -> None:
    metric = NativeIntelliCenterTransportSnapshot(
        source_id="metric-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°C",
        bodies=(
            NativeBodyState(
                "B1", "Pool", NativeBodyKind.POOL, True, False, 27.0, 30.0
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "S1", "Air", NativeTemperatureKind.AIR, 25.0
            ),
        ),
    )
    result = NativeIntelliCenterReadAdapter().map_snapshot(
        metric, generated_at=NOW
    )
    values = {item.observation_id: item for item in result.observations}
    assert values["pool.temperature"].value == 80.6
    assert values["pool.target_temperature"].value == 86.0
    assert values["air.temperature"].value == 77.0
    assert values["pool.temperature"].unit == "°F"


def test_explicit_body_heat_source_distinguishes_heater_solar_and_preference() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="heat-source-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1",
                "Pool",
                NativeBodyKind.POOL,
                True,
                True,
                82.0,
                86.0,
                active_heat_source="solar",
                selected_heat_mode="solar_preferred",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)
    values = {item.observation_id: item.value for item in result.observations}

    assert values["pool.heating_demand_active"] is True
    assert values["solar.active"] is True
    assert values["heater.active"] is False
    assert values["solar_preferred.active"] is True


def test_active_heating_without_source_evidence_does_not_fabricate_heat_type() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="older-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1", "Pool", NativeBodyKind.POOL, True, True, 82.0, 86.0
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)
    concepts = {item.observation_id for item in result.observations}

    assert "heater.active" not in concepts
    assert "solar.active" not in concepts
    assert "heater.active" in result.missing_concepts
    assert "solar.active" in result.missing_concepts


def test_ambiguous_pumps_remain_missing() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="multi-pump-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        pumps=(
            NativePumpState("P1", "Pool Pump A", True, 1800.0, 30.0, 800.0),
            NativePumpState("P2", "Pool Pump B", True, 2200.0, 40.0, 1100.0),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)

    assert {"pump.rpm", "pump.gpm", "pump.power"}.issubset(
        result.missing_concepts
    )


def test_circuit_use_and_subtype_supply_only_supported_exact_aliases() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="circuit-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        circuits=(
            NativeCircuitState("C1", "Body 1", True, use="POOL"),
            NativeCircuitState("C2", "Body 2", False, subtype="SPA"),
            NativeCircuitState("C3", "Deck Feature", True, subtype="WATERFALL"),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)
    values = {item.observation_id: item.value for item in result.observations}

    assert values["pool.command_active"] is True
    assert values["spa.command_active"] is False
    assert values["waterfall.active"] is True


def test_ambiguous_temperature_probe_kind_remains_missing() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="probe-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        temperatures=(
            NativeTemperatureState(
                "S1", "Pool Water", NativeTemperatureKind.WATER, 82.0
            ),
            NativeTemperatureState(
                "S2", "Spa Water", NativeTemperatureKind.WATER, 99.0
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)

    assert "water.temperature" in result.missing_concepts


def test_mapped_concept_diagnostics_are_deterministic_compact_and_immutable() -> None:
    result = NativeIntelliCenterReadAdapter().map_snapshot(
        transport(), generated_at=NOW
    )
    diagnostics = result.mapped_concept_diagnostics()

    assert [item["concept"] for item in diagnostics] == sorted(
        item.observation_id for item in result.observations
    )
    assert all(
        set(item) == {"concept", "native_source_id", "quality", "value_type", "value"}
        for item in diagnostics
    )
    with pytest.raises(TypeError):
        diagnostics[0]["value"] = "changed"  # type: ignore[index]


def test_transport_failure_is_explicit_and_deterministic() -> None:
    class FailureSource:
        def read_snapshot(self) -> NativeIntelliCenterTransportSnapshot:
            raise NativeIntelliCenterReadError("connection_timeout")

    left = NativeIntelliCenterReadAdapter().capture(FailureSource(), generated_at=NOW)
    right = NativeIntelliCenterReadAdapter().capture(FailureSource(), generated_at=NOW)
    assert left == right
    assert left.status is NativeIntelliCenterStatus.UNAVAILABLE
    assert left.failure_reason_code == "CONNECTION_TIMEOUT"
    assert left.observations == ()


def test_new_native_core_modules_import_no_ha_command_delivery_or_network_api() -> None:
    for name in ("intellicenter_readonly.py", "observation_parity.py"):
        tree = ast.parse((ROOT / "poolos" / name).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any(
            part
            in {
                "homeassistant",
                "requests",
                "aiohttp",
                "socket",
                "delivery",
                "commands",
                "execution",
            }
            for module in imports
            for part in module.split(".")
        )
