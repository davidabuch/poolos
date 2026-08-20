"""Read-only Home Assistant entity and attribute mapping for PoolOS commissioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from poolos.clock import FixedClock
from poolos.homeassistant.observations import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationMapper,
    HomeAssistantState,
    HomeAssistantValueType,
)
from poolos.observations import FreshnessPolicy, ObservationFreshness, PoolObservation

from .const import (
    CONF_AIR_TEMPERATURE_ENTITY,
    CONF_HEATER_ACTIVE_ENTITY,
    CONF_GRID_STATUS_ENTITY,
    CONF_JETS_ACTIVE_ENTITY,
    CONF_POOL_COMMAND_ENTITY,
    CONF_POOL_LIGHT_ENTITY,
    CONF_POOL_THERMOSTAT_ENTITY,
    CONF_PUMP_GPM_ENTITY,
    CONF_PUMP_POWER_ENTITY,
    CONF_PUMP_RPM_ENTITY,
    CONF_SLIDE_ACTIVE_ENTITY,
    CONF_SOLAR_ACTIVE_ENTITY,
    CONF_SOLAR_PREFERRED_ENTITY,
    CONF_SOLAR_TEMPERATURE_ENTITY,
    CONF_SPA_COMMAND_ENTITY,
    CONF_SPA_THERMOSTAT_ENTITY,
    CONF_WATERFALL_ACTIVE_ENTITY,
    CONF_WATER_TEMPERATURE_ENTITY,
    OBSERVATION_STALE_AFTER,
    REQUIRED_ENTITY_OPTIONS,
)


class ObservationConcept(str, Enum):
    """Canonical concepts commissioned from Home Assistant entities."""

    # Body enabled is deliberately distinct from heating demand.  The custom
    # HomeKit thermostat's HA mode ``heat`` means the body/pump is enabled; it
    # does not prove that heat is being applied.
    POOL_ACTIVE = "pool.active"
    SPA_ACTIVE = "spa.active"
    POOL_HEATING_DEMAND_ACTIVE = "pool.heating_demand_active"
    SPA_HEATING_DEMAND_ACTIVE = "spa.heating_demand_active"
    POOL_COMMAND_ACTIVE = "pool.command_active"
    SPA_COMMAND_ACTIVE = "spa.command_active"

    PUMP_RPM = "pump.rpm"
    PUMP_GPM = "pump.gpm"
    PUMP_POWER = "pump.power"

    POOL_TEMPERATURE = "pool.temperature"
    SPA_TEMPERATURE = "spa.temperature"
    WATER_TEMPERATURE = "water.temperature"
    POOL_TARGET_TEMPERATURE = "pool.target_temperature"
    SPA_TARGET_TEMPERATURE = "spa.target_temperature"
    SOLAR_TEMPERATURE = "solar.temperature"
    AIR_TEMPERATURE = "air.temperature"

    HEATER_ACTIVE = "heater.active"
    SOLAR_ACTIVE = "solar.active"
    SOLAR_PREFERRED_ACTIVE = "solar_preferred.active"
    WATERFALL_ACTIVE = "waterfall.active"
    JETS_ACTIVE = "jets.active"
    SLIDE_ACTIVE = "slide.active"
    GRID_AVAILABLE = "grid.available"
    GRID_OUTAGE_ACTIVE = "grid.outage_active"
    POOL_LIGHT_ACTIVE = "pool_light.active"
    POOL_LIGHT_COLOR_MODE = "pool_light.color_mode"
    POOL_LIGHT_EFFECT = "pool_light.effect"

    POOL_RAW_HVAC_MODE = "pool.raw_hvac_mode"
    SPA_RAW_HVAC_MODE = "spa.raw_hvac_mode"
    POOL_RAW_HVAC_ACTION = "pool.raw_hvac_action"
    SPA_RAW_HVAC_ACTION = "spa.raw_hvac_action"
    POOL_RAW_HEATER_ID = "pool.raw_heater_id"
    SPA_RAW_HEATER_ID = "spa.raw_heater_id"
    POOL_RAW_HTMODE = "pool.raw_htmode"
    SPA_RAW_HTMODE = "spa.raw_htmode"


@dataclass(frozen=True, slots=True)
class EntityMappingSpec:
    """Describe one configurable Home Assistant-to-PoolOS binding."""

    option_key: str
    concept: ObservationConcept
    value_type: HomeAssistantValueType
    unit: str | None
    required: bool
    attribute: str | None = None
    boolean_map: Mapping[str, bool] | None = None
    freshness_required: bool = False
    quality_required: bool = True


HEATING_ACTION_MAP = MappingProxyType({"heating": True, "idle": False, "off": False})
GRID_AVAILABLE_MAP = MappingProxyType({"on": True, "off": False})
GRID_OUTAGE_MAP = MappingProxyType({"on": False, "off": True})

MAPPING_SPECS: tuple[EntityMappingSpec, ...] = (
    # Pool thermostat: one HA entity yields distinct body, thermal-demand,
    # temperature, target, and raw controller-context observations.
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True, "Status"),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_HEATING_DEMAND_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True, "hvac_action", HEATING_ACTION_MAP),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True, "current_temperature", freshness_required=True),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_TARGET_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True, "temperature"),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_RAW_HVAC_MODE, HomeAssistantValueType.STRING, None, True),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_RAW_HVAC_ACTION, HomeAssistantValueType.STRING, None, True, "hvac_action"),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_RAW_HEATER_ID, HomeAssistantValueType.STRING, None, True, "HEATER"),
    EntityMappingSpec(CONF_POOL_THERMOSTAT_ENTITY, ObservationConcept.POOL_RAW_HTMODE, HomeAssistantValueType.STRING, None, True, "HTMODE"),

    # Spa thermostat uses the same semantics as pool: HA mode ``heat`` is body
    # enabled, while hvac_action ``heating`` represents actual heat demand.
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True, "Status"),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_HEATING_DEMAND_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True, "hvac_action", HEATING_ACTION_MAP),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True, "current_temperature", freshness_required=True),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_TARGET_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True, "temperature"),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_RAW_HVAC_MODE, HomeAssistantValueType.STRING, None, True),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_RAW_HVAC_ACTION, HomeAssistantValueType.STRING, None, True, "hvac_action"),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_RAW_HEATER_ID, HomeAssistantValueType.STRING, None, True, "HEATER"),
    EntityMappingSpec(CONF_SPA_THERMOSTAT_ENTITY, ObservationConcept.SPA_RAW_HTMODE, HomeAssistantValueType.STRING, None, True, "HTMODE"),

    # Physical/hydraulic/electrical truth.
    EntityMappingSpec(CONF_PUMP_RPM_ENTITY, ObservationConcept.PUMP_RPM, HomeAssistantValueType.INTEGER, "rpm", True, freshness_required=True),
    EntityMappingSpec(CONF_PUMP_GPM_ENTITY, ObservationConcept.PUMP_GPM, HomeAssistantValueType.FLOAT, "gpm", False, freshness_required=True),
    EntityMappingSpec(CONF_PUMP_POWER_ENTITY, ObservationConcept.PUMP_POWER, HomeAssistantValueType.FLOAT, "W", True, freshness_required=True),
    EntityMappingSpec(CONF_WATER_TEMPERATURE_ENTITY, ObservationConcept.WATER_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True, freshness_required=True),
    EntityMappingSpec(CONF_SOLAR_TEMPERATURE_ENTITY, ObservationConcept.SOLAR_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True),
    EntityMappingSpec(CONF_AIR_TEMPERATURE_ENTITY, ObservationConcept.AIR_TEMPERATURE, HomeAssistantValueType.FLOAT, "°F", True),

    # Actual equipment outcomes and explicit command/circuit context.
    EntityMappingSpec(CONF_SOLAR_ACTIVE_ENTITY, ObservationConcept.SOLAR_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_HEATER_ACTIVE_ENTITY, ObservationConcept.HEATER_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_POOL_COMMAND_ENTITY, ObservationConcept.POOL_COMMAND_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_SPA_COMMAND_ENTITY, ObservationConcept.SPA_COMMAND_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_GRID_STATUS_ENTITY, ObservationConcept.GRID_AVAILABLE, HomeAssistantValueType.BOOLEAN, None, True, boolean_map=GRID_AVAILABLE_MAP),
    EntityMappingSpec(CONF_GRID_STATUS_ENTITY, ObservationConcept.GRID_OUTAGE_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True, boolean_map=GRID_OUTAGE_MAP),
    EntityMappingSpec(CONF_POOL_LIGHT_ENTITY, ObservationConcept.POOL_LIGHT_ACTIVE, HomeAssistantValueType.BOOLEAN, None, True),
    EntityMappingSpec(CONF_POOL_LIGHT_ENTITY, ObservationConcept.POOL_LIGHT_COLOR_MODE, HomeAssistantValueType.STRING, None, True, "color_mode", quality_required=False),
    EntityMappingSpec(CONF_POOL_LIGHT_ENTITY, ObservationConcept.POOL_LIGHT_EFFECT, HomeAssistantValueType.STRING, None, True, "effect", quality_required=False),

    # Optional explanatory/hydraulic context.  Solar Preferred is recorded only
    # to explain Pentair behavior during learning; PoolOS does not depend on it.
    EntityMappingSpec(CONF_SOLAR_PREFERRED_ENTITY, ObservationConcept.SOLAR_PREFERRED_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
    EntityMappingSpec(CONF_WATERFALL_ACTIVE_ENTITY, ObservationConcept.WATERFALL_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
    EntityMappingSpec(CONF_JETS_ACTIVE_ENTITY, ObservationConcept.JETS_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
    EntityMappingSpec(CONF_SLIDE_ACTIVE_ENTITY, ObservationConcept.SLIDE_ACTIVE, HomeAssistantValueType.BOOLEAN, None, False),
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
    authoritative_source: str = "home_assistant"

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "missing_required", tuple(sorted(self.missing_required)))
        object.__setattr__(self, "unavailable_entities", tuple(sorted(set(self.unavailable_entities))))
        object.__setattr__(self, "stale_entities", tuple(sorted(set(self.stale_entities))))
        object.__setattr__(self, "mapped_entities", MappingProxyType(dict(sorted(self.mapped_entities.items()))))

    @property
    def healthy(self) -> bool:
        """Return whether every configured commissioning observation is usable."""

        return not self.missing_required and not self.unavailable_entities

    def diagnostics(self) -> dict[str, Any]:
        """Return stable diagnostics without exposing Home Assistant state values."""

        return {
            "generated_at": self.generated_at.isoformat(),
            "healthy": self.healthy,
            "observation_count": len(self.observations),
            "mapped_entities": dict(self.mapped_entities),
            "missing_required": list(self.missing_required),
            "unavailable_entities": list(self.unavailable_entities),
            "stale_entities": list(self.stale_entities),
            "freshness_warning": bool(self.stale_entities),
            "authoritative_source": self.authoritative_source,
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
    """Return normalized configured source entities, omitting blank optional entries."""

    mapping: dict[str, str] = {}
    option_keys = {spec.option_key for spec in MAPPING_SPECS}
    for option_key in sorted(option_keys):
        value = options.get(option_key)
        if isinstance(value, str) and value.strip():
            mapping[option_key] = value.strip().lower()
    return mapping


def configured_entity_ids(options: Mapping[str, Any]) -> tuple[str, ...]:
    """Return unique mapped HA entity IDs used for event subscriptions."""

    return tuple(sorted(set(configured_entity_mapping(options).values())))



def _active(values: Mapping[str, Any], concept: ObservationConcept) -> bool:
    """Return a normalized boolean controller/physical state observation."""

    return values.get(concept.value) is True


def _freshness_required_now(
    concept: ObservationConcept,
    values: Mapping[str, Any],
) -> bool:
    """Return whether this measurement is expected to be live in the current state.

    Pentair commonly stops republishing unchanged circulation-dependent values
    while the equipment is idle.  Those retained values remain valid historical
    context and must not make the entire commissioning snapshot unhealthy.
    Freshness becomes mandatory as soon as the relevant body/circuit or another
    hydraulic feature indicates that circulation should be active.
    """

    pool_active = _active(values, ObservationConcept.POOL_ACTIVE) or _active(
        values, ObservationConcept.POOL_COMMAND_ACTIVE
    )
    spa_active = _active(values, ObservationConcept.SPA_ACTIVE) or _active(
        values, ObservationConcept.SPA_COMMAND_ACTIVE
    )
    circulation_expected = any(
        (
            pool_active,
            spa_active,
            _active(values, ObservationConcept.SOLAR_ACTIVE),
            _active(values, ObservationConcept.HEATER_ACTIVE),
            _active(values, ObservationConcept.WATERFALL_ACTIVE),
            _active(values, ObservationConcept.JETS_ACTIVE),
            _active(values, ObservationConcept.SLIDE_ACTIVE),
        )
    )

    if concept is ObservationConcept.POOL_TEMPERATURE:
        return pool_active
    if concept is ObservationConcept.SPA_TEMPERATURE:
        return spa_active
    if concept in {
        ObservationConcept.PUMP_RPM,
        ObservationConcept.PUMP_GPM,
        ObservationConcept.PUMP_POWER,
        ObservationConcept.WATER_TEMPERATURE,
    }:
        return circulation_expected
    return True

def build_snapshot(
    *,
    options: Mapping[str, Any],
    states: Mapping[str, HomeAssistantState],
    now: datetime | None = None,
    stale_after: timedelta = OBSERVATION_STALE_AFTER,
) -> ObservationSnapshot:
    """Build canonical read-only observations from mapped HA states and attributes."""

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    mapping = configured_entity_mapping(options)
    missing_required = tuple(key for key in REQUIRED_ENTITY_OPTIONS if key not in mapping)
    unavailable: list[str] = []
    stale: list[str] = []
    observations: list[PoolObservation] = []
    freshness_candidates: list[tuple[EntityMappingSpec, str, PoolObservation]] = []
    mapper = HomeAssistantObservationMapper()
    freshness_policy = FreshnessPolicy(max_age=stale_after)
    clock = FixedClock(generated_at)

    for spec in MAPPING_SPECS:
        entity_id = mapping.get(spec.option_key)
        if entity_id is None:
            continue
        state = states.get(entity_id)
        if state is None:
            unavailable.append(entity_id)
            continue
        source_id = f"home_assistant:{entity_id}"
        if spec.attribute is not None:
            source_id = f"{source_id}#{spec.attribute}"
        binding = HomeAssistantObservationBinding(
            entity_id=entity_id,
            observation_id=spec.concept.value,
            value_type=spec.value_type,
            unit=spec.unit,
            attribute=spec.attribute,
            source_id=source_id,
            value_map=spec.boolean_map,
        )
        observation = mapper.map_state(state, binding)
        observations.append(observation)
        if observation.quality.value == "invalid" and spec.quality_required:
            unavailable.append(entity_id)
        elif spec.freshness_required:
            freshness_candidates.append((spec, entity_id, observation))

    observation_values = {item.observation_id: item.value for item in observations}
    for spec, entity_id, observation in freshness_candidates:
        if not _freshness_required_now(spec.concept, observation_values):
            continue
        if observation.freshness(clock=clock, policy=freshness_policy) is not ObservationFreshness.FRESH:
            stale.append(entity_id)

    return ObservationSnapshot(
        generated_at=generated_at,
        observations=tuple(sorted(observations, key=lambda item: item.observation_id)),
        missing_required=missing_required,
        unavailable_entities=tuple(unavailable),
        stale_entities=tuple(stale),
        mapped_entities=mapping,
    )
