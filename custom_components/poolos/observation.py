"""Read-only Home Assistant entity mapping for PoolOS commissioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from poolos.homeassistant.observations import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationMapper,
    HomeAssistantState,
    HomeAssistantValueType,
)
from poolos.observations import ObservationFreshness, PoolObservation
from poolos.clock import FixedClock
from poolos.observations import FreshnessPolicy

from .const import (
    CONF_HEATER_ACTIVE_ENTITY,
    CONF_POOL_ACTIVE_ENTITY,
    CONF_POOL_TEMPERATURE_ENTITY,
    CONF_PUMP_POWER_ENTITY,
    CONF_PUMP_RPM_ENTITY,
    CONF_SOLAR_ACTIVE_ENTITY,
    CONF_SPA_ACTIVE_ENTITY,
    CONF_SPA_TEMPERATURE_ENTITY,
    OBSERVATION_STALE_AFTER,
    REQUIRED_ENTITY_OPTIONS,
)


class ObservationConcept(str, Enum):
    """Canonical concepts commissioned from Home Assistant entities."""

    POOL_ACTIVE = "pool.active"
    SPA_ACTIVE = "spa.active"
    PUMP_RPM = "pump.rpm"
    POOL_TEMPERATURE = "pool.temperature"
    SPA_TEMPERATURE = "spa.temperature"
    HEATER_ACTIVE = "heater.active"
    SOLAR_ACTIVE = "solar.active"
    PUMP_POWER = "pump.power"


@dataclass(frozen=True, slots=True)
class EntityMappingSpec:
    """Describe one configurable Home Assistant-to-PoolOS binding."""

    option_key: str
    concept: ObservationConcept
    value_type: HomeAssistantValueType
    unit: str | None
    required: bool


MAPPING_SPECS: tuple[EntityMappingSpec, ...] = (
    EntityMappingSpec(CONF_POOL_ACTIVE_ENTITY, ObservationConcept.POOL_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_SPA_ACTIVE_ENTITY, ObservationConcept.SPA_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_PUMP_RPM_ENTITY, ObservationConcept.PUMP_RPM, HomeAssistantValueType.INTEGER, "rpm", True),
    EntityMappingSpec(CONF_POOL_TEMPERATURE_ENTITY, ObservationConcept.POOL_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True),
    EntityMappingSpec(CONF_SPA_TEMPERATURE_ENTITY, ObservationConcept.SPA_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True),
    EntityMappingSpec(CONF_HEATER_ACTIVE_ENTITY, ObservationConcept.HEATER_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
    EntityMappingSpec(CONF_SOLAR_ACTIVE_ENTITY, ObservationConcept.SOLAR_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
    EntityMappingSpec(CONF_PUMP_POWER_ENTITY, ObservationConcept.PUMP_POWER, HomeAssistantValueType.FLOAT, "W", False),
)


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    """Immutable result of one read-only Home Assistant observation refresh."""

    generated_at: datetime
    observations: tuple[PoolObservation, ...]
    missing_required: tuple[str, ...]
    unavailable_entities: tuple[str, ...]
    stale_entities: tuple[str, ...]
    mapped_entities: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "missing_required", tuple(sorted(self.missing_required)))
        object.__setattr__(self, "unavailable_entities", tuple(sorted(self.unavailable_entities)))
        object.__setattr__(self, "stale_entities", tuple(sorted(self.stale_entities)))
        object.__setattr__(self, "mapped_entities", MappingProxyType(dict(sorted(self.mapped_entities.items()))))

    @property
    def healthy(self) -> bool:
        """Return whether every required mapping is present and usable."""

        return not self.missing_required and not self.unavailable_entities and not self.stale_entities

    def diagnostics(self) -> dict[str, Any]:
        """Return a stable diagnostics payload without Home Assistant state values."""

        return {
            "generated_at": self.generated_at.isoformat(),
            "healthy": self.healthy,
            "observation_count": len(self.observations),
            "mapped_entities": dict(self.mapped_entities),
            "missing_required": list(self.missing_required),
            "unavailable_entities": list(self.unavailable_entities),
            "stale_entities": list(self.stale_entities),
            "observations": [
                {
                    "observation_id": item.observation_id,
                    "quality": item.quality.value,
                    "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                    "source_id": item.source_id,
                }
                for item in self.observations
            ],
        }


def configured_entity_mapping(options: Mapping[str, Any]) -> dict[str, str]:
    """Return normalized configured mappings, omitting blank optional entries."""

    mapping: dict[str, str] = {}
    for spec in MAPPING_SPECS:
        value = options.get(spec.option_key)
        if isinstance(value, str) and value.strip():
            mapping[spec.option_key] = value.strip().lower()
    return mapping


def build_snapshot(
    *,
    options: Mapping[str, Any],
    states: Mapping[str, HomeAssistantState],
    now: datetime | None = None,
    stale_after: timedelta = OBSERVATION_STALE_AFTER,
) -> ObservationSnapshot:
    """Build one canonical read-only observation snapshot from mapped HA states."""

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    mapping = configured_entity_mapping(options)
    missing_required = tuple(key for key in REQUIRED_ENTITY_OPTIONS if key not in mapping)
    unavailable: list[str] = []
    stale: list[str] = []
    observations: list[PoolObservation] = []
    mapper = HomeAssistantObservationMapper()
    freshness_policy = FreshnessPolicy(max_age=stale_after)
    clock = FixedClock(generated_at)

    specs_by_key = {spec.option_key: spec for spec in MAPPING_SPECS}
    for option_key, entity_id in sorted(mapping.items()):
        spec = specs_by_key[option_key]
        state = states.get(entity_id)
        if state is None:
            unavailable.append(entity_id)
            continue
        binding = HomeAssistantObservationBinding(
            entity_id=entity_id,
            observation_id=spec.concept.value,
            value_type=spec.value_type,
            unit=spec.unit,
        )
        observation = mapper.map_state(state, binding)
        observations.append(observation)
        if observation.quality.value == "invalid":
            unavailable.append(entity_id)
        elif observation.freshness(clock=clock, policy=freshness_policy) is not ObservationFreshness.FRESH:
            stale.append(entity_id)

    return ObservationSnapshot(
        generated_at=generated_at,
        observations=tuple(sorted(observations, key=lambda item: item.observation_id)),
        missing_required=missing_required,
        unavailable_entities=tuple(unavailable),
        stale_entities=tuple(stale),
        mapped_entities=mapping,
    )
