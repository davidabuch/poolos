"""Publish canonical simulated PoolOS observations as Home Assistant states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Protocol

if TYPE_CHECKING:
    from .catalog import HomeAssistantEntityCatalog

from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation


class HomeAssistantPublicationError(ValueError):
    """Raised when a simulated state cannot be published safely."""


@dataclass(frozen=True, slots=True)
class HomeAssistantStatePublication:
    """Transport-neutral state update for Home Assistant's state API."""

    entity_id: str
    state: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _simulation_entity_id(self.entity_id))
        if not self.state.strip():
            raise HomeAssistantPublicationError("published state must not be empty")
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class HomeAssistantStatePublicationResult:
    """Acknowledgement returned by a Home Assistant state executor."""

    accepted: bool
    entity_id: str
    received_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _simulation_entity_id(self.entity_id))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class HomeAssistantStatePublicationExecutor(Protocol):
    """Port implemented by REST or WebSocket state publication adapters."""

    def publish_state(
        self,
        publication: HomeAssistantStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantStatePublicationResult: ...


@dataclass(frozen=True, slots=True)
class HomeAssistantSimulationBinding:
    """Bind one simulated PoolOS observation to a dedicated HA entity."""

    observation_id: str
    entity_id: str
    friendly_name: str
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None

    def __post_init__(self) -> None:
        observation_id = self.observation_id.strip()
        friendly_name = self.friendly_name.strip()
        if not observation_id:
            raise HomeAssistantPublicationError("observation_id must not be empty")
        if not friendly_name:
            raise HomeAssistantPublicationError("friendly_name must not be empty")
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "entity_id", _simulation_entity_id(self.entity_id))
        object.__setattr__(self, "friendly_name", friendly_name)
        for name in ("device_class", "state_class", "icon"):
            value = getattr(self, name)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise HomeAssistantPublicationError(f"{name} must not be empty")
                object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class HomeAssistantSimulationPublicationProfile:
    """Validated set of simulated observation publication bindings."""

    bindings: tuple[HomeAssistantSimulationBinding, ...]

    def __post_init__(self) -> None:
        bindings = tuple(self.bindings)
        if not bindings:
            raise HomeAssistantPublicationError("publication bindings must not be empty")
        observation_ids: set[str] = set()
        entity_ids: set[str] = set()
        for binding in bindings:
            if binding.observation_id in observation_ids:
                raise HomeAssistantPublicationError("duplicate publication observation_id")
            if binding.entity_id in entity_ids:
                raise HomeAssistantPublicationError("duplicate publication entity_id")
            observation_ids.add(binding.observation_id)
            entity_ids.add(binding.entity_id)
        object.__setattr__(self, "bindings", bindings)


@dataclass(frozen=True, slots=True)
class HomeAssistantSimulationStateMapper:
    """Translate simulated observations into safe Home Assistant state updates."""

    def map_observation(
        self,
        observation: PoolObservation,
        binding: HomeAssistantSimulationBinding,
    ) -> HomeAssistantStatePublication:
        if observation.observation_id != binding.observation_id:
            raise HomeAssistantPublicationError(
                "observation does not match simulation publication binding"
            )
        if observation.source_kind is not ObservationSourceKind.SIMULATED:
            raise HomeAssistantPublicationError(
                "only simulated observations may be published by this bridge"
            )

        attributes: dict[str, Any] = {
            "friendly_name": binding.friendly_name,
            "poolos_observation_id": observation.observation_id,
            "poolos_source_kind": observation.source_kind.value,
            "poolos_source_id": observation.source_id,
            "poolos_truth_level": observation.truth_level.value,
            "poolos_quality": observation.quality.value,
            "poolos_confidence": observation.confidence,
            "poolos_observed_at": (
                observation.observed_at.isoformat() if observation.observed_at else None
            ),
            "poolos_simulated": True,
        }
        if observation.unit is not None:
            attributes["unit_of_measurement"] = observation.unit
        if binding.device_class is not None:
            attributes["device_class"] = binding.device_class
        if binding.state_class is not None:
            attributes["state_class"] = binding.state_class
        if binding.icon is not None:
            attributes["icon"] = binding.icon

        return HomeAssistantStatePublication(
            entity_id=binding.entity_id,
            state=_state_value(observation),
            attributes=attributes,
        )


@dataclass(slots=True)
class HomeAssistantSimulationPublisher:
    """Idempotently publish bound simulated observations to Home Assistant."""

    profile: HomeAssistantSimulationPublicationProfile
    executor: HomeAssistantStatePublicationExecutor
    mapper: HomeAssistantSimulationStateMapper = field(
        default_factory=HomeAssistantSimulationStateMapper
    )
    _bindings_by_observation: dict[str, HomeAssistantSimulationBinding] = field(
        init=False,
        repr=False,
    )
    _last_publications: dict[str, HomeAssistantStatePublication] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @classmethod
    def from_catalog(
        cls,
        catalog: "HomeAssistantEntityCatalog",
        executor: HomeAssistantStatePublicationExecutor,
    ) -> "HomeAssistantSimulationPublisher":
        """Create an outbound simulation publisher from the canonical catalog."""

        return cls(profile=catalog.publication_profile(), executor=executor)

    def __post_init__(self) -> None:
        self._bindings_by_observation = {
            binding.observation_id: binding for binding in self.profile.bindings
        }

    def publish(
        self,
        observation: PoolObservation,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantStatePublicationResult | None:
        """Publish one bound simulation observation, skipping unchanged state."""

        binding = self._bindings_by_observation.get(observation.observation_id)
        if binding is None:
            return None
        publication = self.mapper.map_observation(observation, binding)
        previous = self._last_publications.get(publication.entity_id)
        if previous == publication:
            return None
        result = self.executor.publish_state(publication, timeout=timeout)
        if result.accepted:
            self._last_publications[publication.entity_id] = publication
        return result


def _simulation_entity_id(value: str) -> str:
    entity_id = value.strip().lower()
    if "." not in entity_id:
        raise HomeAssistantPublicationError("entity_id must be a Home Assistant entity ID")
    domain, object_id = entity_id.split(".", 1)
    if domain not in {"sensor", "binary_sensor"}:
        raise HomeAssistantPublicationError(
            "simulated publication entities must use sensor or binary_sensor"
        )
    if not object_id.startswith("poolos_sim_"):
        raise HomeAssistantPublicationError(
            "simulated publication entity IDs must start with 'poolos_sim_'"
        )
    if not object_id or any(character.isspace() for character in entity_id):
        raise HomeAssistantPublicationError("entity_id is invalid")
    return entity_id


def _state_value(observation: PoolObservation) -> str:
    if observation.quality is ObservationQuality.INVALID or observation.value is None:
        return "unavailable"
    if isinstance(observation.value, bool):
        return "on" if observation.value else "off"
    return str(observation.value)
