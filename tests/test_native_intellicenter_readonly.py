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
    NativeIntelliChlorState,
    NativePumpState,
    NativeRawAttribute,
    NativeRawObject,
    NativeTemperatureKind,
    NativeTemperatureState,
    NativeSystemState,
)
from poolos.observations import ObservationQuality
from poolos.observation_parity import ObservationParityEngine

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
                maximum_temperature=100.0,
                active_heat_source="gas",
                raw_heater_id="HTR01",
                raw_htmode="1",
            ),
            NativeBodyState(
                "B1201",
                "Spa",
                NativeBodyKind.SPA,
                False,
                False,
                80.0,
                100.0,
                maximum_temperature=104.0,
                raw_heater_id="HTR02",
                raw_htmode="0",
            ),
        ),
        pumps=(
            NativePumpState(
                "PMP01",
                "Filter Pump",
                True,
                2200.0,
                42.0,
                1234.0,
                minimum_rpm=950.0,
                maximum_rpm=3450.0,
            ),
        ),
        intellichlors=(
            NativeIntelliChlorState("CHR01", "IntelliChlor", 4050, 52, 4),
        ),
        systems=(
            NativeSystemState("_5451", "IC: 3.014", "auto"),
        ),
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
            NativeCircuitState(
                "_FEA2",
                "Freeze",
                False,
                subtype="FRZ",
                raw_status="OFF",
            ),
            NativeCircuitState(
                "C0002",
                "Pool Light",
                False,
                use="MAGNTAR",
                subtype="INTELLI",
            ),
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
    assert values["pump.minimum_rpm"].value == 950.0
    assert values["pump.maximum_rpm"].value == 3450.0
    assert values["intellichlor.salt_ppm"].value == 4050
    assert values["intellichlor.pool_output_percent"].value == 52
    assert values["intellichlor.spa_output_percent"].value == 4
    assert values["intellichlor.pool_output_percent"].unit == "%"
    assert values["intellichlor.spa_output_percent"].unit == "%"
    assert values["freeze.active"].value is False
    assert values["intellicenter.firmware_version"].value == "IC: 3.014"
    assert values["intellicenter.system_mode"].value == "auto"
    assert values["pool.maximum_temperature"].value == 100.0
    assert values["spa.maximum_temperature"].value == 104.0
    assert values["solar.temperature"].value == 101.0
    assert values["slide.active"].value is True
    assert values["heater.active"].value is True
    assert values["pool.raw_heater_id"].value == "HTR01"
    assert values["pool.raw_htmode"].value == "1"
    assert values["spa.raw_heater_id"].value == "HTR02"
    assert values["spa.raw_htmode"].value == "0"
    assert values["pool_light.active"].value is False
    assert values["pool_light.effect"].value == "MAGNTAR"
    assert "pool_light.color_mode" not in values
    assert all(item.quality is ObservationQuality.GOOD for item in values.values())
    assert all(
        item.source_id is not None
        and item.source_id.startswith("intellicenter_native:panel-main:")
        for item in values.values()
    )
    assert all("home_assistant" not in (item.source_id or "") for item in values.values())


def test_remaining_native_concepts_participate_in_deterministic_parity() -> None:
    native = NativeIntelliCenterReadAdapter().map_snapshot(
        transport(), generated_at=NOW
    )

    report = ObservationParityEngine().compare(
        native.observations,
        native.observations,
        generated_at=NOW,
        ha_source_available=True,
        native_source_available=True,
    )
    by_concept = {item.concept: item for item in report.details}

    for concept in (
        "freeze.active",
        "intellicenter.firmware_version",
        "intellicenter.system_mode",
        "intellichlor.pool_output_percent",
        "intellichlor.salt_ppm",
        "intellichlor.spa_output_percent",
        "pool.maximum_temperature",
        "pump.maximum_rpm",
        "pump.minimum_rpm",
        "spa.maximum_temperature",
    ):
        assert by_concept[concept].status.value == "MATCH"


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


def test_unknown_freeze_status_is_unavailable_not_fabricated() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        circuits=(
            NativeCircuitState(
                "_FEA2",
                "Freeze",
                True,
                subtype="FRZ",
                raw_status="UNKNOWN",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}
    assert "freeze.active" not in values
    assert "freeze.active" in result.missing_concepts


def test_partial_intellichlor_evidence_remains_individually_available() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        intellichlors=(
            NativeIntelliChlorState("CHR01", "IntelliChlor", 4050, None, None),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item for item in result.observations}
    assert values["intellichlor.salt_ppm"].value == 4050
    assert values["intellichlor.salt_ppm"].unit == "ppm"
    assert "intellichlor.pool_output_percent" not in values
    assert "intellichlor.spa_output_percent" not in values
    assert "intellichlor.pool_output_percent" in result.missing_concepts
    assert "intellichlor.spa_output_percent" in result.missing_concepts


def test_absent_body_raw_fields_and_ambiguous_lights_are_not_fabricated() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101", "Pool", NativeBodyKind.POOL, True, False, 82.0, 86.0
            ),
        ),
        circuits=(
            NativeCircuitState("C0002", "Pool Light", False, subtype="INTELLI"),
            NativeCircuitState("C0099", "Pool Light", True, subtype="INTELLI"),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)
    concepts = {item.observation_id for item in result.observations}

    assert "pool.raw_heater_id" not in concepts
    assert "pool.raw_htmode" not in concepts
    assert "pool.raw_hvac_mode" not in concepts
    assert "pool.raw_hvac_action" not in concepts
    assert "pool_light.active" not in concepts
    assert "pool_light.color_mode" not in concepts
    assert "pool_light.effect" not in concepts


def test_ambiguous_same_subtype_sense_probes_are_not_selected_by_name() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="panel-main",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        temperatures=(
            NativeTemperatureState("S01", "Air", NativeTemperatureKind.AIR, 78.0),
            NativeTemperatureState(
                "S02", "Outdoor Probe", NativeTemperatureKind.AIR, 79.0
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(snapshot, generated_at=NOW)

    assert "air.temperature" not in {
        item.observation_id for item in result.observations
    }
    assert "air.temperature" in result.missing_concepts


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
    assert "solar_preferred.active" not in values


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


def test_spa_gas_heat_uses_explicit_source_metadata() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="spa-gas-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                False,
                False,
                89.0,
                90.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="0",
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                97.0,
                98.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="1",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["heater.active"] is True
    assert values["solar.active"] is False
    assert values["spa.heating_demand_active"] is True


def test_spa_solar_heat_uses_explicit_source_metadata() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="spa-solar-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                False,
                False,
                89.0,
                90.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="0",
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                97.0,
                100.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="1",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["heater.active"] is False
    assert values["solar.active"] is True
    assert values["spa.heating_demand_active"] is True


def test_unknown_spa_heat_source_does_not_guess_gas_or_solar() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="spa-unknown-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                97.0,
                100.0,
                active_heat_source=None,
                raw_heater_id="H0001",
                raw_htmode="1",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    concepts = {item.observation_id for item in result.observations}

    assert "heater.active" not in concepts
    assert "solar.active" not in concepts
    assert "heater.active" in result.missing_concepts
    assert "solar.active" in result.missing_concepts


def test_water_temperature_tracks_single_active_spa_body() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="active-body-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                False,
                False,
                89.0,
                90.0,
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                False,
                98.0,
                98.0,
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "SSW11",
                "Water Sensor 1",
                NativeTemperatureKind.WATER,
                89.0,
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["spa.temperature"] == 98.0
    assert values["water.temperature"] == 98.0


def test_water_temperature_falls_back_to_sense_when_idle() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="idle-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                False,
                False,
                89.0,
                90.0,
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                False,
                False,
                98.0,
                98.0,
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "SSW11",
                "Water Sensor 1",
                NativeTemperatureKind.WATER,
                89.0,
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["water.temperature"] == 89.0


def test_after_spa_pool_can_resume_with_solar_heat() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="pool-resume-solar-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                True,
                True,
                90.0,
                92.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="2",
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                False,
                False,
                98.0,
                98.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="0",
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "SSW11",
                "Water Sensor 1",
                NativeTemperatureKind.WATER,
                90.0,
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["pool.active"] is True
    assert values["spa.active"] is False
    assert values["solar.active"] is True
    assert values["heater.active"] is False
    assert values["water.temperature"] == 90.0


def test_after_spa_system_can_remain_idle_without_heat_source() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="post-spa-idle-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                False,
                False,
                90.0,
                92.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="0",
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                False,
                False,
                98.0,
                98.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="0",
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "SSW11",
                "Water Sensor 1",
                NativeTemperatureKind.WATER,
                90.0,
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["pool.active"] is False
    assert values["spa.active"] is False
    assert values["solar.active"] is False
    assert values["heater.active"] is False
    assert values["water.temperature"] == 90.0


def test_active_spa_without_body_temperature_falls_back_to_water_sense() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="spa-transition-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                None,
                100.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="1",
            ),
        ),
        temperatures=(
            NativeTemperatureState(
                "SSW11",
                "Water Sensor 1",
                NativeTemperatureKind.WATER,
                91.0,
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["water.temperature"] == 91.0
    assert "water.temperature" not in result.missing_concepts


def test_spa_gas_heat_can_cycle_off_and_back_on_without_missing_source() -> None:
    resting = NativeIntelliCenterTransportSnapshot(
        source_id="spa-cycle-gas",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                False,
                100.0,
                100.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="0",
            ),
        ),
    )
    heating = NativeIntelliCenterTransportSnapshot(
        source_id="spa-cycle-gas",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                99.0,
                100.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="1",
            ),
        ),
    )

    resting_result = NativeIntelliCenterReadAdapter().map_snapshot(
        resting,
        generated_at=NOW,
    )
    heating_result = NativeIntelliCenterReadAdapter().map_snapshot(
        heating,
        generated_at=NOW,
    )

    resting_values = {
        item.observation_id: item.value
        for item in resting_result.observations
    }
    heating_values = {
        item.observation_id: item.value
        for item in heating_result.observations
    }

    assert resting_values["spa.active"] is True
    assert resting_values["heater.active"] is False
    assert resting_values["solar.active"] is False

    assert heating_values["spa.active"] is True
    assert heating_values["heater.active"] is True
    assert heating_values["solar.active"] is False

    assert "heater.active" not in resting_result.missing_concepts
    assert "heater.active" not in heating_result.missing_concepts


def test_spa_solar_heat_can_cycle_off_and_back_on_without_missing_source() -> None:
    resting = NativeIntelliCenterTransportSnapshot(
        source_id="spa-cycle-solar",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                False,
                100.0,
                100.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="0",
            ),
        ),
    )
    heating = NativeIntelliCenterTransportSnapshot(
        source_id="spa-cycle-solar",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                True,
                True,
                99.0,
                100.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="1",
            ),
        ),
    )

    resting_result = NativeIntelliCenterReadAdapter().map_snapshot(
        resting,
        generated_at=NOW,
    )
    heating_result = NativeIntelliCenterReadAdapter().map_snapshot(
        heating,
        generated_at=NOW,
    )

    resting_values = {
        item.observation_id: item.value
        for item in resting_result.observations
    }
    heating_values = {
        item.observation_id: item.value
        for item in heating_result.observations
    }

    assert resting_values["spa.active"] is True
    assert resting_values["heater.active"] is False
    assert resting_values["solar.active"] is False

    assert heating_values["spa.active"] is True
    assert heating_values["heater.active"] is False
    assert heating_values["solar.active"] is True

    assert "solar.active" not in resting_result.missing_concepts
    assert "solar.active" not in heating_result.missing_concepts


def test_after_spa_pool_can_resume_without_heat() -> None:
    snapshot = NativeIntelliCenterTransportSnapshot(
        source_id="pool-resume-idle-heat-panel",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        bodies=(
            NativeBodyState(
                "B1101",
                "Pool",
                NativeBodyKind.POOL,
                True,
                False,
                90.0,
                92.0,
                active_heat_source="solar",
                raw_heater_id="H0002",
                raw_htmode="0",
            ),
            NativeBodyState(
                "B1202",
                "Spa",
                NativeBodyKind.SPA,
                False,
                False,
                98.0,
                98.0,
                active_heat_source="gas",
                raw_heater_id="H0001",
                raw_htmode="0",
            ),
        ),
    )

    result = NativeIntelliCenterReadAdapter().map_snapshot(
        snapshot,
        generated_at=NOW,
    )
    values = {item.observation_id: item.value for item in result.observations}

    assert values["pool.active"] is True
    assert values["spa.active"] is False
    assert values["heater.active"] is False
    assert values["solar.active"] is False
