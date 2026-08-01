"""Deterministic simulator fault injection and non-retrying recovery policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping


class SimulatorFaultKind(str, Enum):
    DELIVERY_REJECTED = "delivery_rejected"
    DELIVERY_FAILED = "delivery_failed"
    DELIVERY_TIMED_OUT = "delivery_timed_out"
    OBSERVATION_MISSING = "observation_missing"
    OBSERVATION_STALE = "observation_stale"
    OBSERVATION_MISMATCH = "observation_mismatch"
    VERIFICATION_TIMEOUT = "verification_timeout"


class SimulatorFaultRecoveryAction(str, Enum):
    TERMINATE_STEP = "terminate_step"
    TERMINATE_PLAN = "terminate_plan"
    REEVALUATE = "reevaluate"
    AWAIT_OPERATOR = "await_operator"


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatorFaultRule:
    rule_id: str
    step_id: str
    kind: SimulatorFaultKind
    observation_id: str | None = None
    replacement_value: Any | None = None
    stale_by: timedelta = timedelta(minutes=5)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("rule_id", "step_id"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.observation_id is not None:
            value = self.observation_id.strip()
            if not value:
                raise ValueError("observation_id must not be empty")
            object.__setattr__(self, "observation_id", value)
        if self.stale_by <= timedelta(0):
            raise ValueError("stale_by must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SimulatorFaultPlan:
    rules: tuple[SimulatorFaultRule, ...] = ()

    def __post_init__(self) -> None:
        rules = tuple(self.rules)
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("fault rule IDs must be unique")
        step_kinds = [(rule.step_id, rule.kind) for rule in rules]
        if len(step_kinds) != len(set(step_kinds)):
            raise ValueError("only one fault of each kind may target a step")
        object.__setattr__(self, "rules", rules)

    def for_step(self, step_id: str) -> tuple[SimulatorFaultRule, ...]:
        return tuple(rule for rule in self.rules if rule.step_id == step_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatorFaultRecord:
    record_id: str
    rule_id: str
    plan_id: str
    step_id: str
    kind: SimulatorFaultKind
    occurred_at: datetime
    recovery_actions: tuple[SimulatorFaultRecoveryAction, ...]
    reason: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("record_id", "rule_id", "plan_id", "step_id", "reason"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        actions = tuple(self.recovery_actions)
        if not actions or len(actions) != len(set(actions)):
            raise ValueError("recovery_actions must be non-empty and unique")
        object.__setattr__(self, "recovery_actions", actions)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def recovery_actions(kind: SimulatorFaultKind) -> tuple[SimulatorFaultRecoveryAction, ...]:
    if kind in {
        SimulatorFaultKind.DELIVERY_REJECTED,
        SimulatorFaultKind.DELIVERY_FAILED,
        SimulatorFaultKind.DELIVERY_TIMED_OUT,
    }:
        return (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.AWAIT_OPERATOR,
        )
    return (
        SimulatorFaultRecoveryAction.TERMINATE_STEP,
        SimulatorFaultRecoveryAction.TERMINATE_PLAN,
        SimulatorFaultRecoveryAction.REEVALUATE,
    )


def build_fault_record(
    rule: SimulatorFaultRule, *, plan_id: str, occurred_at: datetime, reason: str
) -> SimulatorFaultRecord:
    payload = {
        "rule_id": rule.rule_id,
        "plan_id": plan_id,
        "step_id": rule.step_id,
        "kind": rule.kind.value,
        "occurred_at": occurred_at.isoformat(),
        "reason": reason,
        "metadata": dict(rule.metadata),
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:20]
    return SimulatorFaultRecord(
        record_id=f"simulator-fault:{digest}",
        rule_id=rule.rule_id,
        plan_id=plan_id,
        step_id=rule.step_id,
        kind=rule.kind,
        occurred_at=occurred_at,
        recovery_actions=recovery_actions(rule.kind),
        reason=reason,
        metadata=rule.metadata,
    )


__all__ = [
    "SimulatorFaultKind",
    "SimulatorFaultPlan",
    "SimulatorFaultRecord",
    "SimulatorFaultRecoveryAction",
    "SimulatorFaultRule",
    "build_fault_record",
    "recovery_actions",
]
