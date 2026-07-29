from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolos.homeassistant import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationBridge,
    HomeAssistantObservationError,
    HomeAssistantObservationMapper,
    HomeAssistantObservationProfile,
    HomeAssistantState,
    HomeAssistantValueType,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
    TruthLevel,
)

NOW = datetime(2026, 7, 29, 22, 0, tzinfo=timezone.utc)


def state(entity_id: str, value: str, **attributes: object) -> HomeAssistantState:
    return HomeAssistantState(
        entity_id=entity_id,
        state=value,
        last_changed=NOW,
        last_updated=NOW,
        attributes=attributes,
    )


def binding(**overrides: object) -> HomeAssistantObservationBinding:
    values: dict[str, object] = {
        "entity_id": "sensor.buch_family_pool_temperature",
        "observation_id": "actual.pool.water_temperature",
        "value_type": HomeAssistantValueType.FLOAT,
        "unit": "degF",
    }
    values.update(overrides)
    return HomeAssistantObservationBinding(**values)  # type: ignore[arg-type]


def test_state_payload_parses_home_assistant_timestamps() -> None:
    parsed = HomeAssistantState.from_payload(
        {
            "entity_id": "sensor.pool_temperature",
            "state": "86.5",
            "last_changed": "2026-07-29T21:59:00Z",
            "last_updated": "2026-07-29T22:00:00+00:00",
            "attributes": {"unit_of_measurement": "°F"},
        }
    )

    assert parsed.entity_id == "sensor.pool_temperature"
    assert parsed.last_updated == NOW
    assert parsed.attributes["unit_of_measurement"] == "°F"


def test_mapper_converts_state_to_canonical_observation() -> None:
    observation = HomeAssistantObservationMapper().map_state(
        state("sensor.buch_family_pool_temperature", "86.5"),
        binding(),
    )

    assert observation.observation_id == "actual.pool.water_temperature"
    assert observation.value == 86.5
    assert observation.unit == "degF"
    assert observation.observed_at == NOW
    assert observation.source_kind is ObservationSourceKind.LIVE
    assert observation.source_id == (
        "home_assistant:sensor.buch_family_pool_temperature"
    )
    assert observation.quality is ObservationQuality.GOOD
    assert observation.truth_level is TruthLevel.MEASURED


@pytest.mark.parametrize("unavailable", ["unknown", "unavailable"])
def test_unavailable_state_becomes_invalid_without_fabricating_value(
    unavailable: str,
) -> None:
    observation = HomeAssistantObservationMapper().map_state(
        state("sensor.buch_family_pool_temperature", unavailable),
        binding(),
    )

    assert observation.value == unavailable
    assert observation.quality is ObservationQuality.INVALID
    assert observation.confidence == 0.0


def test_invalid_numeric_value_is_retained_as_invalid_evidence() -> None:
    observation = HomeAssistantObservationMapper().map_state(
        state("sensor.buch_family_pool_temperature", "not-a-number"),
        binding(),
    )

    assert observation.value == "not-a-number"
    assert observation.quality is ObservationQuality.INVALID
    assert observation.confidence == 0.0


def test_attribute_binding_reads_attribute_instead_of_entity_state() -> None:
    observation = HomeAssistantObservationMapper().map_state(
        state("climate.pool", "heat", current_temperature=87.0),
        binding(
            entity_id="climate.pool",
            attribute="current_temperature",
        ),
    )

    assert observation.value == 87.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("on", True), ("off", False), ("connected", True), ("disconnected", False)],
)
def test_boolean_conversion(raw: str, expected: bool) -> None:
    observation = HomeAssistantObservationMapper().map_state(
        state("binary_sensor.grid_status", raw),
        binding(
            entity_id="binary_sensor.grid_status",
            observation_id="actual.energy.grid_available",
            value_type=HomeAssistantValueType.BOOLEAN,
            unit=None,
        ),
    )

    assert observation.value is expected


def test_bridge_ingests_bound_entities_and_ignores_unbound_entities() -> None:
    store = ObservationStore()
    bridge = HomeAssistantObservationBridge(
        profile=HomeAssistantObservationProfile((binding(),)),
        store=store,
    )

    ignored = bridge.ingest(state("sensor.unrelated", "12"))
    accepted = bridge.ingest(
        state("sensor.buch_family_pool_temperature", "86.5")
    )

    assert ignored is None
    assert accepted is not None
    assert store.get("actual.pool.water_temperature") == accepted


def test_live_and_simulated_sources_coexist_in_one_store() -> None:
    store = ObservationStore()
    simulated = PoolObservation(
        observation_id="actual.pool.water_temperature",
        value=85.0,
        unit="degF",
        truth_level=TruthLevel.PREDICTED,
        observed_at=NOW,
        source_kind=ObservationSourceKind.SIMULATED,
        source_id="sim-pool",
        quality=ObservationQuality.GOOD,
    )
    store.put(simulated)
    bridge = HomeAssistantObservationBridge(
        profile=HomeAssistantObservationProfile((binding(),)),
        store=store,
    )
    bridge.ingest(state("sensor.buch_family_pool_temperature", "86.5"))

    observations = store.get_all("actual.pool.water_temperature")
    assert len(observations) == 2
    assert {item.source_kind for item in observations} == {
        ObservationSourceKind.LIVE,
        ObservationSourceKind.SIMULATED,
    }


def test_profile_rejects_duplicate_entity_bindings() -> None:
    with pytest.raises(HomeAssistantObservationError, match="duplicate"):
        HomeAssistantObservationProfile((binding(), binding()))


def test_mapper_rejects_state_binding_mismatch() -> None:
    with pytest.raises(HomeAssistantObservationError, match="does not match"):
        HomeAssistantObservationMapper().map_state(
            state("sensor.other", "86"),
            binding(),
        )
