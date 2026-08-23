"""Compose the authoritative PoolOS observation snapshot.

Controller-owned observations come directly from PoolOS's independent
IntelliCenter transport. Home Assistant remains authoritative only for
facts that are genuinely external to IntelliCenter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Mapping

from poolos.clock import FixedClock
from poolos.homeassistant.observations import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationMapper,
    HomeAssistantState,
    HomeAssistantValueType,
)
from poolos.intellicenter_readonly import NativeIntelliCenterObservationSnapshot
from poolos.observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    PoolObservation,
)

from .const import (
    CONF_GRID_STATUS_ENTITY,
    CONF_POOL_LIGHT_ENTITY,
    OBSERVATION_STALE_AFTER,
)
from .observation import (
    GRID_AVAILABLE_MAP,
    GRID_OUTAGE_MAP,
    ObservationConcept,
    ObservationSnapshot,
    configured_entity_mapping,
)


# Native concepts required for PoolOS controller observation health.
#
# Optional installed features such as GPM, waterfall, jets and slide
# remain useful native observations when present, but their
# absence must not make an otherwise healthy controller installation fail.
AUTHORITATIVE_REQUIRED_NATIVE_CONCEPTS = frozenset(
    {
        ObservationConcept.POOL_ACTIVE.value,
        ObservationConcept.SPA_ACTIVE.value,
        ObservationConcept.POOL_HEATING_DEMAND_ACTIVE.value,
        ObservationConcept.SPA_HEATING_DEMAND_ACTIVE.value,
        ObservationConcept.POOL_COMMAND_ACTIVE.value,
        ObservationConcept.SPA_COMMAND_ACTIVE.value,
        ObservationConcept.PUMP_RPM.value,
        ObservationConcept.PUMP_POWER.value,
        ObservationConcept.POOL_TEMPERATURE.value,
        ObservationConcept.SPA_TEMPERATURE.value,
        ObservationConcept.WATER_TEMPERATURE.value,
        ObservationConcept.POOL_TARGET_TEMPERATURE.value,
        ObservationConcept.SPA_TARGET_TEMPERATURE.value,
        ObservationConcept.SOLAR_TEMPERATURE.value,
        ObservationConcept.AIR_TEMPERATURE.value,
        ObservationConcept.HEATER_ACTIVE.value,
        ObservationConcept.SOLAR_ACTIVE.value,
        ObservationConcept.POOL_LIGHT_ACTIVE.value,
        ObservationConcept.POOL_RAW_HEATER_ID.value,
        ObservationConcept.SPA_RAW_HEATER_ID.value,
        ObservationConcept.POOL_RAW_HTMODE.value,
        ObservationConcept.SPA_RAW_HTMODE.value,
    }
)

AUTHORITATIVE_REQUIRED_EXTERNAL_CONCEPTS = frozenset(
    {
        ObservationConcept.GRID_AVAILABLE.value,
        ObservationConcept.GRID_OUTAGE_ACTIVE.value,
    }
)

# Native measurements where age matters while the equipment is expected
# to be live. The state-dependent gate mirrors the existing HA observation
# freshness semantics.
_NATIVE_FRESHNESS_CONCEPTS = frozenset(
    {
        ObservationConcept.POOL_TEMPERATURE.value,
        ObservationConcept.SPA_TEMPERATURE.value,
        ObservationConcept.WATER_TEMPERATURE.value,
        ObservationConcept.PUMP_RPM.value,
        ObservationConcept.PUMP_POWER.value,
    }
)


def _native_values(
    observations: tuple[PoolObservation, ...],
) -> dict[str, Any]:
    return {item.observation_id: item.value for item in observations}


def _active(values: Mapping[str, Any], concept: ObservationConcept) -> bool:
    return values.get(concept.value) is True


def _native_freshness_required_now(
    concept: str,
    values: Mapping[str, Any],
) -> bool:
    pool_active = _active(values, ObservationConcept.POOL_ACTIVE) or _active(
        values, ObservationConcept.POOL_COMMAND_ACTIVE
    )
    spa_active = _active(values, ObservationConcept.SPA_ACTIVE) or _active(
        values, ObservationConcept.SPA_COMMAND_ACTIVE
    )
    pump_rpm = values.get(ObservationConcept.PUMP_RPM.value)
    pump_running = (
        not isinstance(pump_rpm, bool)
        and isinstance(pump_rpm, (int, float))
        and pump_rpm > 0
    )

    circulation_expected = any(
        (
            pool_active,
            spa_active,
            pump_running,
            _active(values, ObservationConcept.SOLAR_ACTIVE),
            _active(values, ObservationConcept.HEATER_ACTIVE),
            _active(values, ObservationConcept.WATERFALL_ACTIVE),
            _active(values, ObservationConcept.JETS_ACTIVE),
            _active(values, ObservationConcept.SLIDE_ACTIVE),
        )
    )

    if concept == ObservationConcept.POOL_TEMPERATURE.value:
        return pool_active
    if concept == ObservationConcept.SPA_TEMPERATURE.value:
        return spa_active
    if concept in {
        ObservationConcept.PUMP_RPM.value,
        ObservationConcept.PUMP_POWER.value,
        ObservationConcept.WATER_TEMPERATURE.value,
    }:
        return circulation_expected
    return False


def _external_observations(
    *,
    options: Mapping[str, Any],
    states: Mapping[str, HomeAssistantState],
) -> tuple[
    tuple[PoolObservation, ...],
    tuple[str, ...],
    tuple[str, ...],
    Mapping[str, str],
]:
    """Map only genuinely external HA observations."""

    mapping = configured_entity_mapping(options)
    mapper = HomeAssistantObservationMapper()
    observations: list[PoolObservation] = []
    missing_required: list[str] = []
    unavailable: list[str] = []
    mapped_entities: dict[str, str] = {}

    grid_entity = mapping.get(CONF_GRID_STATUS_ENTITY)
    if grid_entity is None:
        missing_required.extend(sorted(AUTHORITATIVE_REQUIRED_EXTERNAL_CONCEPTS))
    else:
        mapped_entities[CONF_GRID_STATUS_ENTITY] = grid_entity
        state = states.get(grid_entity)
        if state is None:
            unavailable.append(grid_entity)
        else:
            for concept, value_map in (
                (ObservationConcept.GRID_AVAILABLE, GRID_AVAILABLE_MAP),
                (ObservationConcept.GRID_OUTAGE_ACTIVE, GRID_OUTAGE_MAP),
            ):
                observation = mapper.map_state(
                    state,
                    HomeAssistantObservationBinding(
                        entity_id=grid_entity,
                        observation_id=concept.value,
                        value_type=HomeAssistantValueType.BOOLEAN,
                        unit=None,
                        source_id=f"home_assistant:{grid_entity}",
                        value_map=value_map,
                    ),
                )
                observations.append(observation)
                if observation.quality is ObservationQuality.INVALID:
                    unavailable.append(grid_entity)

    # Pool-light on/off state is native-authoritative. HA light metadata is
    # retained only as optional descriptive context.
    light_entity = mapping.get(CONF_POOL_LIGHT_ENTITY)
    if light_entity is not None:
        mapped_entities[CONF_POOL_LIGHT_ENTITY] = light_entity
        state = states.get(light_entity)
        if state is not None:
            for concept, attribute in (
                (ObservationConcept.POOL_LIGHT_COLOR_MODE, "color_mode"),
                (ObservationConcept.POOL_LIGHT_EFFECT, "effect"),
            ):
                observations.append(
                    mapper.map_state(
                        state,
                        HomeAssistantObservationBinding(
                            entity_id=light_entity,
                            observation_id=concept.value,
                            value_type=HomeAssistantValueType.STRING,
                            unit=None,
                            attribute=attribute,
                            source_id=(f"home_assistant:{light_entity}#{attribute}"),
                        ),
                    )
                )

    return (
        tuple(observations),
        tuple(sorted(set(missing_required))),
        tuple(sorted(set(unavailable))),
        MappingProxyType(dict(sorted(mapped_entities.items()))),
    )


def build_authoritative_snapshot(
    *,
    native_snapshot: NativeIntelliCenterObservationSnapshot | None,
    options: Mapping[str, Any],
    states: Mapping[str, HomeAssistantState],
    now: datetime | None = None,
    stale_after: timedelta = OBSERVATION_STALE_AFTER,
) -> ObservationSnapshot:
    """Compose native controller truth with external HA observations.

    There is intentionally no fallback from missing/unavailable native
    IntelliCenter observations to legacy Pentair HA entities.
    """

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    external, external_missing, external_unavailable, mapped_entities = _external_observations(
        options=options,
        states=states,
    )

    native_observations: tuple[PoolObservation, ...] = ()
    missing_required = list(external_missing)
    unavailable = list(external_unavailable)
    stale: list[str] = []

    if native_snapshot is None or not native_snapshot.available:
        missing_required.extend(sorted(AUTHORITATIVE_REQUIRED_NATIVE_CONCEPTS))
        unavailable.append("poolos.independent_intellicenter")
    else:
        native_observations = tuple(native_snapshot.observations)
        by_concept = {item.observation_id: item for item in native_observations}

        for concept in sorted(AUTHORITATIVE_REQUIRED_NATIVE_CONCEPTS):
            observation = by_concept.get(concept)
            if observation is None:
                missing_required.append(concept)
                continue
            if observation.quality is not ObservationQuality.GOOD:
                unavailable.append(observation.source_id or concept)

        values = _native_values(native_observations)
        clock = FixedClock(generated_at)
        policy = FreshnessPolicy(max_age=stale_after)

        for concept in sorted(_NATIVE_FRESHNESS_CONCEPTS):
            observation = by_concept.get(concept)
            if observation is None:
                continue
            if not _native_freshness_required_now(concept, values):
                continue
            if observation.freshness(clock=clock, policy=policy) is not ObservationFreshness.FRESH:
                stale.append(observation.source_id or concept)

    combined: dict[str, PoolObservation] = {
        item.observation_id: item for item in native_observations
    }

    # External HA observations may only add concepts that IntelliCenter
    # fundamentally does not own. Never overwrite native controller truth.
    for observation in external:
        combined.setdefault(observation.observation_id, observation)

    composed_mapping = {
        "native_intellicenter": "poolos.independent_intellicenter",
        **dict(mapped_entities),
    }

    return ObservationSnapshot(
        generated_at=generated_at,
        observations=tuple(sorted(combined.values(), key=lambda item: item.observation_id)),
        missing_required=tuple(sorted(set(missing_required))),
        unavailable_entities=tuple(sorted(set(unavailable))),
        stale_entities=tuple(sorted(set(stale))),
        mapped_entities=composed_mapping,
        authoritative_source="native_intellicenter",
    )


__all__ = [
    "AUTHORITATIVE_REQUIRED_EXTERNAL_CONCEPTS",
    "AUTHORITATIVE_REQUIRED_NATIVE_CONCEPTS",
    "build_authoritative_snapshot",
]
