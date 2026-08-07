"""Canonical immutable operational-intent model for PoolOS.

Operational intents describe what an operator or trusted subsystem wants PoolOS
to accomplish. They are declarative evidence only: this module performs no
arbitration, planning, command generation, Home Assistant I/O, or actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, IntEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping


class OperationalIntentType(str, Enum):
    MAINTAIN_CIRCULATION = "maintain_circulation"
    MAINTAIN_SANITATION = "maintain_sanitation"
    MAINTAIN_CHEMISTRY = "maintain_chemistry"
    HEAT_POOL = "heat_pool"
    HEAT_SPA = "heat_spa"
    MAXIMIZE_SOLAR = "maximize_solar"
    MINIMIZE_ENERGY = "minimize_energy"
    FREEZE_PROTECTION = "freeze_protection"
    PROTECT_EQUIPMENT = "protect_equipment"
    QUIET_HOURS = "quiet_hours"
    SCHEDULED_OPERATION = "scheduled_operation"
    MANUAL_OPERATOR_REQUEST = "manual_operator_request"
    MAINTENANCE_MODE = "maintenance_mode"
    COMMISSIONING_MODE = "commissioning_mode"


class OperationalIntentSource(str, Enum):
    OPERATOR = "operator"
    SCHEDULE = "schedule"
    HOME_ASSISTANT_AUTOMATION = "home_assistant_automation"
    WEATHER = "weather"
    CHEMISTRY = "chemistry"
    EQUIPMENT = "equipment"
    SAFETY = "safety"
    COMMISSIONING = "commissioning"
    LEARNING_ENGINE = "learning_engine"


class OperationalIntentPriority(IntEnum):
    ADVISORY = 10
    LOW = 20
    NORMAL = 30
    HIGH = 40
    CRITICAL = 50
    SAFETY = 60


class OperationalIntentLifecycle(str, Enum):
    REQUESTED = "requested"
    ACTIVE = "active"
    SATISFIED = "satisfied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OperationalIntentSafetyClass(str, Enum):
    INFORMATIONAL = "informational"
    NORMAL = "normal"
    PROTECTIVE = "protective"
    SAFETY_CRITICAL = "safety_critical"


_ALLOWED_TRANSITIONS: Mapping[OperationalIntentLifecycle, frozenset[OperationalIntentLifecycle]] = {
    OperationalIntentLifecycle.REQUESTED: frozenset(
        {
            OperationalIntentLifecycle.ACTIVE,
            OperationalIntentLifecycle.EXPIRED,
            OperationalIntentLifecycle.CANCELLED,
        }
    ),
    OperationalIntentLifecycle.ACTIVE: frozenset(
        {
            OperationalIntentLifecycle.SATISFIED,
            OperationalIntentLifecycle.EXPIRED,
            OperationalIntentLifecycle.CANCELLED,
        }
    ),
    OperationalIntentLifecycle.SATISFIED: frozenset(),
    OperationalIntentLifecycle.EXPIRED: frozenset(),
    OperationalIntentLifecycle.CANCELLED: frozenset(),
}


def _require_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc(value, "datetime").isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(_canonical_value(payload), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class IntentCriterion:
    """One declarative precondition, constraint, success, or failure criterion."""

    code: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_text(self.code, "criterion code"))
        object.__setattr__(self, "description", _require_text(self.description, "criterion description"))
        canonical = _canonical_value(self.parameters)
        object.__setattr__(self, "parameters", MappingProxyType(dict(canonical)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IntentCriterion":
        return cls(
            code=str(payload["code"]),
            description=str(payload["description"]),
            parameters=dict(payload.get("parameters", {})),
        )


@dataclass(frozen=True, slots=True)
class OperationalIntent:
    """Immutable, declarative statement of desired operational purpose."""

    intent_type: OperationalIntentType
    source: OperationalIntentSource
    priority: OperationalIntentPriority
    description: str
    requested_at: datetime
    source_reference: str
    safety_class: OperationalIntentSafetyClass = OperationalIntentSafetyClass.NORMAL
    lifecycle: OperationalIntentLifecycle = OperationalIntentLifecycle.REQUESTED
    preconditions: tuple[IntentCriterion, ...] = ()
    constraints: tuple[IntentCriterion, ...] = ()
    success_criteria: tuple[IntentCriterion, ...] = ()
    failure_criteria: tuple[IntentCriterion, ...] = ()
    explanation_template: str = "{description}"
    expires_at: datetime | None = None
    supersedes_intent_id: str | None = None
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "description", _require_text(self.description, "description"))
        object.__setattr__(self, "source_reference", _require_text(self.source_reference, "source_reference"))
        object.__setattr__(
            self,
            "explanation_template",
            _require_text(self.explanation_template, "explanation_template"),
        )
        requested_at = _utc(self.requested_at, "requested_at")
        object.__setattr__(self, "requested_at", requested_at)
        if self.expires_at is not None:
            expires_at = _utc(self.expires_at, "expires_at")
            if expires_at <= requested_at:
                raise ValueError("expires_at must be after requested_at")
            object.__setattr__(self, "expires_at", expires_at)
        if self.supersedes_intent_id is not None:
            object.__setattr__(
                self,
                "supersedes_intent_id",
                _require_text(self.supersedes_intent_id, "supersedes_intent_id"),
            )
        for name in (
            "preconditions",
            "constraints",
            "success_criteria",
            "failure_criteria",
        ):
            criteria = tuple(getattr(self, name))
            codes = [criterion.code for criterion in criteria]
            if len(codes) != len(set(codes)):
                raise ValueError(f"{name} contains duplicate criterion codes")
            object.__setattr__(self, name, criteria)
        if self.source is OperationalIntentSource.SAFETY and (
            self.priority is not OperationalIntentPriority.SAFETY
            or self.safety_class is not OperationalIntentSafetyClass.SAFETY_CRITICAL
        ):
            raise ValueError("safety-source intents require SAFETY priority and SAFETY_CRITICAL classification")
        identity_payload = self._payload(include_lifecycle=False)
        digest = sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()[:24]
        object.__setattr__(self, "intent_id", f"operational-intent-{digest}")

    def _payload(self, *, include_lifecycle: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "intent_type": self.intent_type.value,
            "source": self.source.value,
            "priority": self.priority.name.lower(),
            "description": self.description,
            "requested_at": self.requested_at,
            "source_reference": self.source_reference,
            "safety_class": self.safety_class.value,
            "preconditions": [item.to_dict() for item in self.preconditions],
            "constraints": [item.to_dict() for item in self.constraints],
            "success_criteria": [item.to_dict() for item in self.success_criteria],
            "failure_criteria": [item.to_dict() for item in self.failure_criteria],
            "explanation_template": self.explanation_template,
            "expires_at": self.expires_at,
            "supersedes_intent_id": self.supersedes_intent_id,
        }
        if include_lifecycle:
            payload["lifecycle"] = self.lifecycle.value
            payload["intent_id"] = self.intent_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(self._payload())

    def to_json(self) -> str:
        return _canonical_json(self._payload())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationalIntent":
        def dt(name: str) -> datetime | None:
            raw = payload.get(name)
            if raw is None:
                return None
            text = str(raw).replace("Z", "+00:00")
            return datetime.fromisoformat(text)

        requested_at = dt("requested_at")
        if requested_at is None:
            raise ValueError("requested_at is required")

        intent = cls(
            intent_type=OperationalIntentType(str(payload["intent_type"])),
            source=OperationalIntentSource(str(payload["source"])),
            priority=OperationalIntentPriority[str(payload["priority"]).upper()],
            description=str(payload["description"]),
            requested_at=requested_at,
            source_reference=str(payload["source_reference"]),
            safety_class=OperationalIntentSafetyClass(str(payload["safety_class"])),
            lifecycle=OperationalIntentLifecycle(str(payload.get("lifecycle", "requested"))),
            preconditions=tuple(IntentCriterion.from_dict(item) for item in payload.get("preconditions", ())),
            constraints=tuple(IntentCriterion.from_dict(item) for item in payload.get("constraints", ())),
            success_criteria=tuple(IntentCriterion.from_dict(item) for item in payload.get("success_criteria", ())),
            failure_criteria=tuple(IntentCriterion.from_dict(item) for item in payload.get("failure_criteria", ())),
            explanation_template=str(payload.get("explanation_template", "{description}")),
            expires_at=dt("expires_at"),
            supersedes_intent_id=(
                str(payload["supersedes_intent_id"])
                if payload.get("supersedes_intent_id") is not None
                else None
            ),
        )
        supplied_id = payload.get("intent_id")
        if supplied_id is not None and supplied_id != intent.intent_id:
            raise ValueError("intent_id does not match canonical intent content")
        return intent

    @classmethod
    def from_json(cls, value: str) -> "OperationalIntent":
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("operational intent JSON must contain an object")
        return cls.from_dict(payload)

    def transition_to(self, lifecycle: OperationalIntentLifecycle) -> "OperationalIntent":
        if lifecycle not in _ALLOWED_TRANSITIONS[self.lifecycle]:
            raise ValueError(f"invalid operational intent transition: {self.lifecycle.value} -> {lifecycle.value}")
        return replace(self, lifecycle=lifecycle)

    def explain(self) -> str:
        try:
            rendered = self.explanation_template.format(
                description=self.description,
                intent_type=self.intent_type.value,
                source=self.source.value,
                priority=self.priority.name.lower(),
                safety_class=self.safety_class.value,
            )
        except KeyError as exc:
            raise ValueError(f"unknown explanation placeholder: {exc.args[0]}") from exc
        return _require_text(rendered, "rendered explanation")


def canonical_intent_order(intents: tuple[OperationalIntent, ...]) -> tuple[OperationalIntent, ...]:
    """Return deterministic highest-priority-first ordering without arbitration."""

    return tuple(
        sorted(
            intents,
            key=lambda intent: (
                -int(intent.priority),
                intent.requested_at,
                intent.intent_id,
            ),
        )
    )
