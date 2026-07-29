from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from poolos.homeassistant import (
    HomeAssistantCatalogError,
    HomeAssistantEntityCatalog,
    HomeAssistantEntityClass,
    HomeAssistantEntityDefinition,
    HomeAssistantObservationBridge,
    HomeAssistantSimulationPublisher,
    HomeAssistantState,
    HomeAssistantStatePublication,
    HomeAssistantStatePublicationResult,
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


def definition(**overrides: object) -> HomeAssistantEntityDefinition:
    values: dict[str, object] = {
        "observation_id": "actual.pool.water_temperature",
        "value_type": HomeAssistantValueType.FLOAT,
        "entity_class": HomeAssistantEntityClass.SENSOR,
        "unit": "degF",
        "observed_entity_id": "sensor.buch_family_pool_temperature",
        "simulated_entity_id": "sensor.poolos_sim_pool_water_temperature",
        "friendly_name": "PoolOS Sim Pool Water Temperature",
        "device_class": "temperature",
        "state_class": "measurement",
        "metadata": {"body": "pool"},
    }
    values.update(overrides)
    return HomeAssistantEntityDefinition(**values)  # type: ignore[arg-type]


def test_catalog_builds_observation_and_publication_profiles() -> None:
    catalog = HomeAssistantEntityCatalog((definition(),))

    observed = catalog.observation_profile().bindings[0]
    published = catalog.publication_profile().bindings[0]

    assert observed.entity_id == "sensor.buch_family_pool_temperature"
    assert observed.observation_id == "actual.pool.water_temperature"
    assert observed.unit == "degF"
    assert published.entity_id == "sensor.poolos_sim_pool_water_temperature"
    assert published.friendly_name == "PoolOS Sim Pool Water Temperature"


def test_catalog_lookup_supports_both_boundary_identities() -> None:
    item = definition()
    catalog = HomeAssistantEntityCatalog((item,))

    assert catalog.get_by_observation_id(item.observation_id) is item
    assert catalog.get_by_entity_id("SENSOR.BUCH_FAMILY_POOL_TEMPERATURE") is item
    assert catalog.get_by_entity_id("sensor.poolos_sim_pool_water_temperature") is item
    assert catalog.get_by_entity_id("sensor.missing") is None


def test_catalog_metadata_is_immutable() -> None:
    item = definition(metadata={"body": "pool"})
    with pytest.raises(TypeError):
        item.metadata["body"] = "spa"  # type: ignore[index]


@pytest.mark.parametrize(
    "definitions",
    [
        (definition(), definition()),
        (
            definition(),
            definition(
                observation_id="actual.spa.water_temperature",
                simulated_entity_id="sensor.poolos_sim_spa_water_temperature",
            ),
        ),
    ],
)
def test_catalog_rejects_duplicate_observation_or_entity_mappings(
    definitions: tuple[HomeAssistantEntityDefinition, ...],
) -> None:
    with pytest.raises(HomeAssistantCatalogError, match="duplicate"):
        HomeAssistantEntityCatalog(definitions)


def test_definition_rejects_observed_domain_mismatch() -> None:
    with pytest.raises(HomeAssistantCatalogError, match="domain"):
        definition(
            entity_class=HomeAssistantEntityClass.CLIMATE,
            observed_entity_id="sensor.pool_temperature",
        )


def test_definition_rejects_unsafe_simulation_entity() -> None:
    with pytest.raises(HomeAssistantCatalogError, match="poolos_sim"):
        definition(simulated_entity_id="sensor.pool_temperature")


def test_catalog_requires_at_least_one_boundary() -> None:
    with pytest.raises(HomeAssistantCatalogError, match="observed or simulated"):
        definition(observed_entity_id=None, simulated_entity_id=None)


def test_catalog_reports_missing_direction_profiles() -> None:
    observed_only = HomeAssistantEntityCatalog(
        (definition(simulated_entity_id=None, friendly_name=None),)
    )
    published_only = HomeAssistantEntityCatalog(
        (definition(observed_entity_id=None),)
    )

    with pytest.raises(HomeAssistantCatalogError, match="publication"):
        observed_only.publication_profile()
    with pytest.raises(HomeAssistantCatalogError, match="observation"):
        published_only.observation_profile()


@dataclass
class RecordingExecutor:
    publications: list[HomeAssistantStatePublication] = field(default_factory=list)

    def publish_state(
        self,
        publication: HomeAssistantStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantStatePublicationResult:
        self.publications.append(publication)
        return HomeAssistantStatePublicationResult(True, publication.entity_id)


def test_bridges_construct_directly_from_catalog() -> None:
    catalog = HomeAssistantEntityCatalog((definition(),))
    store = ObservationStore()
    inbound = HomeAssistantObservationBridge.from_catalog(catalog, store)
    inbound.ingest(
        HomeAssistantState(
            entity_id="sensor.buch_family_pool_temperature",
            state="86.5",
            last_changed=NOW,
            last_updated=NOW,
        )
    )
    assert store.get("actual.pool.water_temperature") is not None

    executor = RecordingExecutor()
    outbound = HomeAssistantSimulationPublisher.from_catalog(catalog, executor)
    result = outbound.publish(
        PoolObservation(
            observation_id="actual.pool.water_temperature",
            value=85.0,
            unit="degF",
            truth_level=TruthLevel.PREDICTED,
            observed_at=NOW,
            source_kind=ObservationSourceKind.SIMULATED,
            source_id="simulation:primary",
            quality=ObservationQuality.GOOD,
        )
    )
    assert result is not None and result.accepted
    assert executor.publications[0].entity_id == (
        "sensor.poolos_sim_pool_water_temperature"
    )
