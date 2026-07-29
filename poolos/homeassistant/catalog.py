"""Canonical Home Assistant entity catalog for PoolOS observation boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from poolos.observations import ObservationSourceKind, TruthLevel

from .observations import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationProfile,
    HomeAssistantValueType,
)
from .publication import (
    HomeAssistantSimulationBinding,
    HomeAssistantSimulationPublicationProfile,
)


class HomeAssistantCatalogError(ValueError):
    """Raised when a Home Assistant catalog is incomplete or ambiguous."""


class HomeAssistantEntityClass(str, Enum):
    """Home Assistant entity domains supported by catalog definitions."""

    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    CLIMATE = "climate"
    SWITCH = "switch"
    NUMBER = "number"
    SELECT = "select"
    LIGHT = "light"
    COVER = "cover"


@dataclass(frozen=True, slots=True)
class HomeAssistantEntityDefinition:
    """Single source of truth for one canonical PoolOS observation mapping."""

    observation_id: str
    value_type: HomeAssistantValueType
    entity_class: HomeAssistantEntityClass
    unit: str | None = None
    observed_entity_id: str | None = None
    observed_attribute: str | None = None
    source_kind: ObservationSourceKind = ObservationSourceKind.LIVE
    source_id: str | None = None
    truth_level: TruthLevel = TruthLevel.MEASURED
    confidence: float = 1.0
    simulated_entity_id: str | None = None
    friendly_name: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        observation_id = self.observation_id.strip()
        if not observation_id:
            raise HomeAssistantCatalogError("observation_id must not be empty")
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

        observed_entity_id = _optional_entity_id(self.observed_entity_id)
        simulated_entity_id = _optional_entity_id(self.simulated_entity_id)
        if observed_entity_id is None and simulated_entity_id is None:
            raise HomeAssistantCatalogError(
                "catalog definition must declare an observed or simulated entity"
            )
        if observed_entity_id is not None:
            domain = observed_entity_id.split(".", 1)[0]
            if domain != self.entity_class.value:
                raise HomeAssistantCatalogError(
                    "observed entity domain does not match entity_class"
                )
        if simulated_entity_id is not None:
            domain, object_id = simulated_entity_id.split(".", 1)
            if domain not in {"sensor", "binary_sensor"}:
                raise HomeAssistantCatalogError(
                    "simulated entity must use sensor or binary_sensor"
                )
            if not object_id.startswith("poolos_sim_"):
                raise HomeAssistantCatalogError(
                    "simulated entity object ID must start with 'poolos_sim_'"
                )
            if self.friendly_name is None or not self.friendly_name.strip():
                raise HomeAssistantCatalogError(
                    "friendly_name is required for simulated publication"
                )
        object.__setattr__(self, "observed_entity_id", observed_entity_id)
        object.__setattr__(self, "simulated_entity_id", simulated_entity_id)

        for name in (
            "unit",
            "observed_attribute",
            "source_id",
            "friendly_name",
            "device_class",
            "state_class",
            "icon",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise HomeAssistantCatalogError(f"{name} must not be empty")
                object.__setattr__(self, name, normalized)
        if not 0.0 <= self.confidence <= 1.0:
            raise HomeAssistantCatalogError("confidence must be between 0 and 1")

    @property
    def observation_enabled(self) -> bool:
        return self.observed_entity_id is not None

    @property
    def publication_enabled(self) -> bool:
        return self.simulated_entity_id is not None

    def observation_binding(self) -> HomeAssistantObservationBinding | None:
        """Build the inbound bridge binding represented by this definition."""

        if self.observed_entity_id is None:
            return None
        return HomeAssistantObservationBinding(
            entity_id=self.observed_entity_id,
            observation_id=self.observation_id,
            value_type=self.value_type,
            unit=self.unit,
            attribute=self.observed_attribute,
            source_kind=self.source_kind,
            source_id=self.source_id,
            truth_level=self.truth_level,
            confidence=self.confidence,
        )

    def publication_binding(self) -> HomeAssistantSimulationBinding | None:
        """Build the outbound simulation binding represented by this definition."""

        if self.simulated_entity_id is None:
            return None
        assert self.friendly_name is not None
        return HomeAssistantSimulationBinding(
            observation_id=self.observation_id,
            entity_id=self.simulated_entity_id,
            friendly_name=self.friendly_name,
            device_class=self.device_class,
            state_class=self.state_class,
            icon=self.icon,
        )


@dataclass(frozen=True, slots=True)
class HomeAssistantEntityCatalog:
    """Validated canonical registry for Home Assistant observation mappings."""

    definitions: tuple[HomeAssistantEntityDefinition, ...]
    _by_observation_id: Mapping[str, HomeAssistantEntityDefinition] = field(
        init=False,
        repr=False,
    )
    _by_entity_id: Mapping[str, HomeAssistantEntityDefinition] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        definitions = tuple(self.definitions)
        if not definitions:
            raise HomeAssistantCatalogError("catalog definitions must not be empty")
        by_observation_id: dict[str, HomeAssistantEntityDefinition] = {}
        by_entity_id: dict[str, HomeAssistantEntityDefinition] = {}
        for definition in definitions:
            if definition.observation_id in by_observation_id:
                raise HomeAssistantCatalogError(
                    f"duplicate observation_id {definition.observation_id!r}"
                )
            by_observation_id[definition.observation_id] = definition
            for entity_id in (
                definition.observed_entity_id,
                definition.simulated_entity_id,
            ):
                if entity_id is None:
                    continue
                if entity_id in by_entity_id:
                    raise HomeAssistantCatalogError(
                        f"duplicate Home Assistant entity_id {entity_id!r}"
                    )
                by_entity_id[entity_id] = definition
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(
            self, "_by_observation_id", MappingProxyType(by_observation_id)
        )
        object.__setattr__(self, "_by_entity_id", MappingProxyType(by_entity_id))

    @classmethod
    def from_definitions(
        cls,
        definitions: Iterable[HomeAssistantEntityDefinition],
    ) -> HomeAssistantEntityCatalog:
        return cls(tuple(definitions))

    def get_by_observation_id(
        self, observation_id: str
    ) -> HomeAssistantEntityDefinition | None:
        return self._by_observation_id.get(observation_id.strip())

    def get_by_entity_id(
        self, entity_id: str
    ) -> HomeAssistantEntityDefinition | None:
        return self._by_entity_id.get(entity_id.strip().lower())

    def observation_profile(self) -> HomeAssistantObservationProfile:
        bindings = tuple(
            binding
            for definition in self.definitions
            if (binding := definition.observation_binding()) is not None
        )
        if not bindings:
            raise HomeAssistantCatalogError("catalog has no observation bindings")
        return HomeAssistantObservationProfile(bindings)

    def publication_profile(self) -> HomeAssistantSimulationPublicationProfile:
        bindings = tuple(
            binding
            for definition in self.definitions
            if (binding := definition.publication_binding()) is not None
        )
        if not bindings:
            raise HomeAssistantCatalogError("catalog has no publication bindings")
        return HomeAssistantSimulationPublicationProfile(bindings)


def _optional_entity_id(value: str | None) -> str | None:
    if value is None:
        return None
    entity_id = value.strip().lower()
    if "." not in entity_id:
        raise HomeAssistantCatalogError("entity_id must be a Home Assistant entity ID")
    domain, object_id = entity_id.split(".", 1)
    if not domain or not object_id or any(character.isspace() for character in entity_id):
        raise HomeAssistantCatalogError("entity_id is invalid")
    return entity_id
