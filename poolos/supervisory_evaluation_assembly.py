"""Deterministic assembly of supervisory evaluation inputs.

The boundary converts one successful runtime-trigger coalescing batch plus
explicit immutable planning facts into the existing ``DecisionEvaluationContext``
and ``DecisionOrchestrationRequest`` models. It does not evaluate a decision,
invoke the Decision Orchestrator, access storage, schedule work, or perform I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .decision_flight_recorder import DecisionFlightRecord
from .decision_orchestrator import DecisionOrchestrationRequest
from .decision_planning import DecisionPlanningRequest
from .evaluation_context import DecisionEvaluationContext, EvaluationRuntimeMode
from .planning import PlanObjective
from .runtime_trigger_coalescing import (
    RuntimeTriggerCoalescingBatch,
    RuntimeTriggerCoalescingOutcome,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _normalize_json(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        _require_aware(value, "identity datetime")
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("identity mappings require string keys")
            normalized[key] = _normalize_json(item)
        return dict(sorted(normalized.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_normalize_json(item) for item in value)
    raise TypeError(
        "evaluation assembly identity evidence must be JSON-compatible; "
        f"unsupported value: {type(value).__name__}"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        _normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _derived_id(prefix: str, payload: object) -> str:
    return prefix + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationAssemblyRequest:
    """Explicit immutable facts required to assemble one evaluation request."""

    coalescing_batch: RuntimeTriggerCoalescingBatch
    evaluated_at: datetime
    runtime_mode: EvaluationRuntimeMode
    goals: tuple[PlanObjective, ...]
    planning: DecisionPlanningRequest
    observation: Mapping[str, Any] = field(default_factory=dict)
    forecast: Mapping[str, Any] = field(default_factory=dict)
    active_policy_ids: tuple[str, ...] = ()
    freshness: Mapping[str, str] = field(default_factory=dict)
    previous_decision_id: str | None = None
    active_record: DecisionFlightRecord | None = None
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        goals = tuple(sorted(self.goals, key=lambda item: item.objective_id))
        goal_ids = tuple(item.objective_id for item in goals)
        if not goals:
            raise ValueError("at least one goal is required")
        if len(set(goal_ids)) != len(goal_ids):
            raise ValueError("goal objective IDs must be unique")
        if self.planning.objective not in goals:
            raise ValueError("planning objective must be present in goals")
        policies = tuple(sorted(self.active_policy_ids))
        if any(not item.strip() for item in policies):
            raise ValueError("active policy IDs must not be empty")
        if len(set(policies)) != len(policies):
            raise ValueError("active policy IDs must be unique")
        blockers = tuple(sorted(self.blockers))
        if any(not item.strip() for item in blockers):
            raise ValueError("blockers must not be empty")
        if self.previous_decision_id is not None and not self.previous_decision_id.strip():
            raise ValueError("previous_decision_id must not be empty when supplied")
        if self.active_record is not None:
            active_id = self.active_record.decision.decision_id
            if self.previous_decision_id != active_id:
                raise ValueError(
                    "active record must match explicit previous_decision_id"
                )
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.freshness.items()
        ):
            raise ValueError("freshness must contain string pairs")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise ValueError("metadata must contain string pairs")
        _normalize_json(self.observation)
        _normalize_json(self.forecast)
        object.__setattr__(self, "goals", goals)
        object.__setattr__(self, "active_policy_ids", policies)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "observation", MappingProxyType(dict(self.observation)))
        object.__setattr__(self, "forecast", MappingProxyType(dict(self.forecast)))
        object.__setattr__(self, "freshness", MappingProxyType(dict(self.freshness)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationAssemblyResult:
    """Immutable evidence and existing models assembled for orchestration."""

    assembly_id: str
    assembled_at: datetime
    coalescing_batch_id: str
    context: DecisionEvaluationContext
    orchestration_request: DecisionOrchestrationRequest
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.assembly_id.strip():
            raise ValueError("assembly_id must not be empty")
        _require_aware(self.assembled_at, "assembled_at")
        if not self.coalescing_batch_id.strip():
            raise ValueError("coalescing_batch_id must not be empty")
        if self.orchestration_request.context is not self.context:
            raise ValueError("orchestration request must use the assembled context")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationInputAssembler:
    """Build existing evaluation models without invoking evaluation."""

    boundary_name: str = "poolos.supervisory_evaluation_input_assembler"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def assemble(
        self,
        request: SupervisoryEvaluationAssemblyRequest,
    ) -> SupervisoryEvaluationAssemblyResult:
        """Assemble deterministic context and orchestration request evidence."""

        batch = request.coalescing_batch
        if batch.coalesced_trigger is None:
            raise ValueError("successful coalesced trigger evidence is required")
        consumed = tuple(
            item
            for item in batch.results
            if item.outcome is RuntimeTriggerCoalescingOutcome.CONSUMED
        )
        if not consumed:
            raise ValueError("at least one consumed submission is required")
        if batch.coalesced_at > request.evaluated_at:
            raise ValueError("coalescing evidence cannot be from the future")

        context_id = _derived_id(
            "decision-evaluation-context-",
            {
                "active_policy_ids": request.active_policy_ids,
                "blockers": request.blockers,
                "coalescing_batch_id": batch.batch_id,
                "consumed_submission_ids": batch.consumed_submission_ids,
                "evaluated_at": request.evaluated_at,
                "forecast": request.forecast,
                "freshness": request.freshness,
                "goals": tuple(goal.to_dict() for goal in request.goals),
                "metadata": request.metadata,
                "observation": request.observation,
                "planning_objective_id": request.planning.objective.objective_id,
                "previous_decision_id": request.previous_decision_id,
                "runtime_mode": request.runtime_mode,
                "trigger": batch.coalesced_trigger.trigger,
            },
        )
        context = DecisionEvaluationContext(
            context_id=context_id,
            evaluated_at=request.evaluated_at,
            trigger=batch.coalesced_trigger.trigger,
            runtime_mode=request.runtime_mode,
            goals=request.goals,
            observation=request.observation,
            forecast=request.forecast,
            active_policy_ids=request.active_policy_ids,
            freshness=request.freshness,
            previous_decision_id=request.previous_decision_id,
            blockers=request.blockers,
            metadata={
                **dict(request.metadata),
                "runtime_trigger_coalescing_batch_id": batch.batch_id,
                "runtime_trigger_consumed_submission_count": str(len(consumed)),
            },
        )
        orchestration_request = DecisionOrchestrationRequest(
            context=context,
            planning=request.planning,
            active_record=request.active_record,
            coalesced_trigger=batch.coalesced_trigger,
        )
        assembly_id = _derived_id(
            "supervisory-evaluation-assembly-",
            {
                "boundary_name": self.boundary_name,
                "coalescing_batch_id": batch.batch_id,
                "context_id": context_id,
                "planning_objective_id": request.planning.objective.objective_id,
                "previous_decision_id": request.previous_decision_id,
            },
        )
        return SupervisoryEvaluationAssemblyResult(
            assembly_id=assembly_id,
            assembled_at=request.evaluated_at,
            coalescing_batch_id=batch.batch_id,
            context=context,
            orchestration_request=orchestration_request,
            provenance={
                "supervisory_evaluation_assembly_id": assembly_id,
                "supervisory_evaluation_assembly_boundary": self.boundary_name,
                "supervisory_evaluation_context_id": context_id,
                "runtime_trigger_coalescing_batch_id": batch.batch_id,
                "runtime_trigger_consumed_submission_ids": ",".join(
                    batch.consumed_submission_ids
                ),
            },
        )
