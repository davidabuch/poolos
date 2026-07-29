from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from poolos.homeassistant import (
    HomeAssistantPublicationError,
    HomeAssistantRestStatePublicationExecutor,
    HomeAssistantSimulationBinding,
    HomeAssistantSimulationPublicationProfile,
    HomeAssistantSimulationPublisher,
    HomeAssistantSimulationStateMapper,
    HomeAssistantStatePublication,
    HomeAssistantStatePublicationResult,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
    TruthLevel,
)

NOW = datetime(2026, 7, 29, 23, 0, tzinfo=timezone.utc)


def observation(
    value: object = 86.5,
    *,
    source_kind: ObservationSourceKind = ObservationSourceKind.SIMULATED,
    quality: ObservationQuality = ObservationQuality.GOOD,
) -> PoolObservation:
    return PoolObservation(
        observation_id="simulated.pool.water_temperature",
        value=value,
        unit="°F",
        truth_level=TruthLevel.PREDICTED,
        observed_at=NOW,
        source_kind=source_kind,
        source_id="simulation:primary",
        quality=quality,
        confidence=0.95,
    )


def binding() -> HomeAssistantSimulationBinding:
    return HomeAssistantSimulationBinding(
        observation_id="simulated.pool.water_temperature",
        entity_id="sensor.poolos_sim_pool_water_temperature",
        friendly_name="PoolOS Simulated Pool Water Temperature",
        device_class="temperature",
        state_class="measurement",
    )


class RecordingExecutor:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.publications: list[HomeAssistantStatePublication] = []

    def publish_state(
        self,
        publication: HomeAssistantStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantStatePublicationResult:
        self.publications.append(publication)
        return HomeAssistantStatePublicationResult(
            accepted=self.accepted,
            entity_id=publication.entity_id,
            received_at=NOW,
            details={"timeout": timeout},
        )


def test_mapper_publishes_simulated_state_with_metadata() -> None:
    result = HomeAssistantSimulationStateMapper().map_observation(
        observation(), binding()
    )
    assert result.entity_id == "sensor.poolos_sim_pool_water_temperature"
    assert result.state == "86.5"
    assert result.attributes["poolos_simulated"] is True
    assert result.attributes["poolos_observation_id"] == (
        "simulated.pool.water_temperature"
    )
    assert result.attributes["unit_of_measurement"] == "°F"
    assert result.attributes["device_class"] == "temperature"


def test_mapper_rejects_live_observation() -> None:
    with pytest.raises(HomeAssistantPublicationError, match="only simulated"):
        HomeAssistantSimulationStateMapper().map_observation(
            observation(source_kind=ObservationSourceKind.LIVE), binding()
        )


def test_dedicated_simulation_namespace_is_required() -> None:
    with pytest.raises(HomeAssistantPublicationError, match="poolos_sim"):
        HomeAssistantSimulationBinding(
            observation_id="simulated.pool.water_temperature",
            entity_id="sensor.pool_temperature",
            friendly_name="Unsafe",
        )


def test_control_domains_cannot_be_publication_targets() -> None:
    with pytest.raises(HomeAssistantPublicationError, match="sensor or binary_sensor"):
        HomeAssistantSimulationBinding(
            observation_id="simulated.pool.heating",
            entity_id="climate.poolos_sim_pool",
            friendly_name="Unsafe",
        )


def test_invalid_observation_publishes_unavailable() -> None:
    result = HomeAssistantSimulationStateMapper().map_observation(
        observation(None, quality=ObservationQuality.INVALID), binding()
    )
    assert result.state == "unavailable"


def test_boolean_state_uses_home_assistant_on_off() -> None:
    boolean_binding = HomeAssistantSimulationBinding(
        observation_id="simulated.energy.grid_available",
        entity_id="binary_sensor.poolos_sim_grid_available",
        friendly_name="PoolOS Simulated Grid Available",
    )
    boolean_observation = PoolObservation(
        observation_id="simulated.energy.grid_available",
        value=True,
        truth_level=TruthLevel.PREDICTED,
        observed_at=NOW,
        source_kind=ObservationSourceKind.SIMULATED,
        source_id="simulation:primary",
        quality=ObservationQuality.GOOD,
    )
    result = HomeAssistantSimulationStateMapper().map_observation(
        boolean_observation, boolean_binding
    )
    assert result.state == "on"


def test_profile_rejects_duplicate_observation_and_entity_bindings() -> None:
    first = binding()
    with pytest.raises(HomeAssistantPublicationError, match="observation_id"):
        HomeAssistantSimulationPublicationProfile((first, first))


def test_publisher_is_idempotent_after_accepted_publication() -> None:
    executor = RecordingExecutor()
    publisher = HomeAssistantSimulationPublisher(
        HomeAssistantSimulationPublicationProfile((binding(),)), executor
    )
    assert publisher.publish(observation()) is not None
    assert publisher.publish(observation()) is None
    assert len(executor.publications) == 1


def test_rejected_publication_is_not_cached() -> None:
    executor = RecordingExecutor(accepted=False)
    publisher = HomeAssistantSimulationPublisher(
        HomeAssistantSimulationPublicationProfile((binding(),)), executor
    )
    assert publisher.publish(observation()) is not None
    assert publisher.publish(observation()) is not None
    assert len(executor.publications) == 2


def test_unbound_observation_is_ignored() -> None:
    executor = RecordingExecutor()
    publisher = HomeAssistantSimulationPublisher(
        HomeAssistantSimulationPublicationProfile((binding(),)), executor
    )
    other = PoolObservation(
        observation_id="simulated.spa.water_temperature",
        value=100,
        truth_level=TruthLevel.PREDICTED,
        observed_at=NOW,
        source_kind=ObservationSourceKind.SIMULATED,
        source_id="simulation:primary",
        quality=ObservationQuality.GOOD,
    )
    assert publisher.publish(other) is None
    assert executor.publications == []


class Response:
    status = 201
    headers: dict[str, str] = {}

    def read(self) -> bytes:
        return b'{"entity_id":"sensor.poolos_sim_pool_water_temperature"}'

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class Opener:
    def __init__(self) -> None:
        self.request: Any = None
        self.timeout: float | None = None

    def open(self, request: Any, timeout: float | None = None) -> Response:
        self.request = request
        self.timeout = timeout
        return Response()


def test_rest_executor_posts_to_home_assistant_state_api() -> None:
    opener = Opener()
    executor = HomeAssistantRestStatePublicationExecutor(
        "http://homeassistant.local:8123", "token", opener=opener
    )
    publication = HomeAssistantSimulationStateMapper().map_observation(
        observation(), binding()
    )
    result = executor.publish_state(publication, timeout=3.0)
    assert result.accepted is True
    assert opener.timeout == 3.0
    assert opener.request.full_url.endswith(
        "/api/states/sensor.poolos_sim_pool_water_temperature"
    )
    assert opener.request.get_method() == "POST"
    assert opener.request.headers["Authorization"] == "Bearer token"
    payload = json.loads(opener.request.data.decode("utf-8"))
    assert payload["state"] == "86.5"
    assert payload["attributes"]["poolos_simulated"] is True
