"""Translate Home Assistant state snapshots into canonical PoolOS observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:
    from .catalog import HomeAssistantEntityCatalog

from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
    TruthLevel,
)


class HomeAssistantObservationError(ValueError):
    """Raised when Home Assistant observation input cannot be translated safely."""


class HomeAssistantValueType(str, Enum):
    """Supported conversions from Home Assistant's string state representation."""

    STRING = "string"
    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"


@dataclass(frozen=True, slots=True)
class HomeAssistantState:
    """Transport-neutral snapshot of one Home Assistant entity state."""

    entity_id: str
    state: str
    last_changed: datetime
    last_updated: datetime
    last_reported: datetime | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        entity_id = _entity_id(self.entity_id)
        if self.last_changed.tzinfo is None or self.last_updated.tzinfo is None:
            raise HomeAssistantObservationError(
                "Home Assistant timestamps must be timezone-aware"
            )
        if self.last_reported is not None and self.last_reported.tzinfo is None:
            raise HomeAssistantObservationError("last_reported must be timezone-aware")
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> HomeAssistantState:
        """Parse the stable subset of a Home Assistant REST/WebSocket state payload."""

        try:
            entity_id = payload["entity_id"]
            state = payload["state"]
            last_changed = payload["last_changed"]
            last_updated = payload["last_updated"]
        except KeyError as exc:
            raise HomeAssistantObservationError(
                f"Home Assistant state payload is missing {exc.args[0]!r}"
            ) from exc
        if not isinstance(entity_id, str) or not isinstance(state, str):
            raise HomeAssistantObservationError("entity_id and state must be strings")
        attributes = payload.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise HomeAssistantObservationError("attributes must be a mapping")
        return cls(
            entity_id=entity_id,
            state=state,
            last_changed=_timestamp(last_changed, "last_changed"),
            last_updated=_timestamp(last_updated, "last_updated"),
            last_reported=(
                _timestamp(payload["last_reported"], "last_reported")
                if payload.get("last_reported") is not None
                else None
            ),
            attributes=attributes,
        )


@dataclass(frozen=True, slots=True)
class HomeAssistantObservationBinding:
    """Bind one HA entity to one PoolOS-native observation identity."""

    entity_id: str
    observation_id: str
    value_type: HomeAssistantValueType
    unit: str | None = None
    attribute: str | None = None
    source_kind: ObservationSourceKind = ObservationSourceKind.LIVE
    source_id: str | None = None
    truth_level: TruthLevel = TruthLevel.MEASURED
    confidence: float = 1.0
    value_map: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _entity_id(self.entity_id))
        observation_id = self.observation_id.strip()
        if not observation_id:
            raise HomeAssistantObservationError("observation_id must not be empty")
        object.__setattr__(self, "observation_id", observation_id)
        if self.attribute is not None:
            attribute = self.attribute.strip()
            if not attribute:
                raise HomeAssistantObservationError("attribute must not be empty")
            object.__setattr__(self, "attribute", attribute)
        if self.source_id is not None and not self.source_id.strip():
            raise HomeAssistantObservationError("source_id must not be empty")
        if self.value_map is not None:
            normalized = {str(key).strip().lower(): value for key, value in self.value_map.items()}
            if any(not key for key in normalized):
                raise HomeAssistantObservationError("value_map keys must not be empty")
            object.__setattr__(self, "value_map", MappingProxyType(normalized))
        if not 0.0 <= self.confidence <= 1.0:
            raise HomeAssistantObservationError("confidence must be between 0 and 1")

    @property
    def resolved_source_id(self) -> str:
        """Return an opaque producer identity while keeping HA IDs in this adapter."""

        return self.source_id or f"home_assistant:{self.entity_id}"


@dataclass(frozen=True, slots=True)
class HomeAssistantObservationProfile:
    """Validated set of entity bindings used by one observation bridge."""

    bindings: tuple[HomeAssistantObservationBinding, ...]

    def __post_init__(self) -> None:
        bindings = tuple(self.bindings)
        if not bindings:
            raise HomeAssistantObservationError("observation bindings must not be empty")
        entity_ids: set[str] = set()
        source_keys: set[tuple[str, ObservationSourceKind, str]] = set()
        for binding in bindings:
            if binding.entity_id in entity_ids:
                raise HomeAssistantObservationError(
                    f"duplicate Home Assistant entity binding {binding.entity_id!r}"
                )
            entity_ids.add(binding.entity_id)
            key = (
                binding.observation_id,
                binding.source_kind,
                binding.resolved_source_id,
            )
            if key in source_keys:
                raise HomeAssistantObservationError(
                    "duplicate canonical observation source binding"
                )
            source_keys.add(key)
        object.__setattr__(self, "bindings", bindings)


@dataclass(frozen=True, slots=True)
class HomeAssistantObservationMapper:
    """Convert validated HA snapshots into canonical PoolObservation values."""

    def map_state(
        self,
        state: HomeAssistantState,
        binding: HomeAssistantObservationBinding,
    ) -> PoolObservation:
        if state.entity_id != binding.entity_id:
            raise HomeAssistantObservationError(
                f"state {state.entity_id!r} does not match binding {binding.entity_id!r}"
            )
        raw_value = (
            state.attributes.get(binding.attribute)
            if binding.attribute is not None
            else state.state
        )
        if binding.value_map is not None and isinstance(raw_value, str):
            mapped = binding.value_map.get(raw_value.strip().lower())
            if mapped is not None:
                raw_value = mapped
        quality = _quality(state.state, raw_value)
        value: Any = raw_value
        confidence = binding.confidence
        if quality is ObservationQuality.GOOD:
            try:
                value = _convert(raw_value, binding.value_type)
            except (TypeError, ValueError):
                quality = ObservationQuality.INVALID
                confidence = 0.0
        else:
            confidence = 0.0

        return PoolObservation(
            observation_id=binding.observation_id,
            value=value,
            unit=binding.unit,
            truth_level=binding.truth_level,
            observed_at=state.last_reported or state.last_updated,
            source_kind=binding.source_kind,
            source_id=binding.resolved_source_id,
            quality=quality,
            confidence=confidence,
        )


@dataclass(slots=True)
class HomeAssistantObservationBridge:
    """Ingest HA snapshots into an ObservationStore through explicit bindings."""

    profile: HomeAssistantObservationProfile
    store: ObservationStore
    mapper: HomeAssistantObservationMapper = field(
        default_factory=HomeAssistantObservationMapper
    )
    _bindings_by_entity: dict[str, HomeAssistantObservationBinding] = field(
        init=False,
        repr=False,
    )

    @classmethod
    def from_catalog(
        cls,
        catalog: "HomeAssistantEntityCatalog",
        store: ObservationStore,
    ) -> "HomeAssistantObservationBridge":
        """Create an inbound bridge from the canonical entity catalog."""

        return cls(profile=catalog.observation_profile(), store=store)

    def __post_init__(self) -> None:
        self._bindings_by_entity = {
            binding.entity_id: binding for binding in self.profile.bindings
        }

    def ingest(self, state: HomeAssistantState) -> PoolObservation | None:
        """Ingest one bound state; silently ignore unrelated HA entities."""

        binding = self._bindings_by_entity.get(state.entity_id)
        if binding is None:
            return None
        observation = self.mapper.map_state(state, binding)
        self.store.put(observation)
        return observation

    def ingest_many(
        self,
        states: Iterable[HomeAssistantState],
    ) -> tuple[PoolObservation, ...]:
        accepted: list[PoolObservation] = []
        for state in states:
            observation = self.ingest(state)
            if observation is not None:
                accepted.append(observation)
        return tuple(accepted)


def _entity_id(value: str) -> str:
    entity_id = value.strip().lower()
    if "." not in entity_id:
        raise HomeAssistantObservationError("entity_id must be a Home Assistant entity ID")
    domain, object_id = entity_id.split(".", 1)
    if not domain or not object_id or any(character.isspace() for character in entity_id):
        raise HomeAssistantObservationError("entity_id is invalid")
    return entity_id


def _timestamp(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HomeAssistantObservationError(f"{name} must be ISO-8601") from exc
    else:
        raise HomeAssistantObservationError(f"{name} must be a datetime or ISO-8601 string")
    if timestamp.tzinfo is None:
        raise HomeAssistantObservationError(f"{name} must be timezone-aware")
    return timestamp


def _quality(entity_state: str, raw_value: object) -> ObservationQuality:
    if entity_state.lower() in {"unavailable", "unknown"}:
        return ObservationQuality.INVALID
    if raw_value is None:
        return ObservationQuality.INVALID
    return ObservationQuality.GOOD


def _convert(value: object, value_type: HomeAssistantValueType) -> Any:
    if value_type is HomeAssistantValueType.STRING:
        if not isinstance(value, str):
            raise TypeError("string observation requires string value")
        return value
    if value_type is HomeAssistantValueType.FLOAT:
        if isinstance(value, bool):
            raise TypeError("boolean is not a float observation")
        return float(value)  # type: ignore[arg-type]
    if value_type is HomeAssistantValueType.INTEGER:
        if isinstance(value, bool):
            raise TypeError("boolean is not an integer observation")
        numeric = float(value)  # type: ignore[arg-type]
        if not numeric.is_integer():
            raise ValueError("integer observation must be integral")
        return int(numeric)
    if value_type is HomeAssistantValueType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"on", "true", "yes", "1", "connected"}:
                return True
            if normalized in {"off", "false", "no", "0", "disconnected"}:
                return False
        raise ValueError("boolean observation has unsupported value")
    raise AssertionError(f"unsupported value type {value_type!r}")


__all__ = [
    "HomeAssistantObservationBinding",
    "HomeAssistantObservationBridge",
    "HomeAssistantObservationError",
    "HomeAssistantObservationMapper",
    "HomeAssistantObservationProfile",
    "HomeAssistantState",
    "HomeAssistantValueType",
]
