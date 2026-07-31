"""Deterministic execution-plan construction for PoolOS.

This module converts one authorized :class:`ExecutionProposal` into an
immutable, ordered :class:`ExecutionPlan`. It performs no translation,
delivery, verification, Home Assistant calls, or Pentair calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionPlan,
    ExecutionProposal,
    ExecutionStep,
)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


def _canonical_mapping(value: Mapping[str, Any], label: str) -> str:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must contain JSON-serializable values") from exc


class PlanBuildDisposition(str, Enum):
    """Whether deterministic plan construction succeeded."""

    BUILT = "built"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStepSpecification:
    """Planning annotations for one proposal operation.

    Specifications are keyed by operation ID. The builder always preserves the
    operation order already established by the proposal, regardless of the
    order in which specifications are supplied.
    """

    operation_id: str
    preconditions: Mapping[str, Any] = field(default_factory=dict)
    expected_observations: Mapping[str, Any] = field(default_factory=dict)
    verification_required: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operation_id = self.operation_id.strip()
        if not operation_id:
            raise ValueError("operation_id must not be empty")
        if self.verification_required and not self.expected_observations:
            raise ValueError(
                "verification-required specifications must define expected observations"
            )
        _canonical_mapping(self.preconditions, "preconditions")
        _canonical_mapping(self.expected_observations, "expected_observations")
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(
            self, "preconditions", _freeze_mapping(self.preconditions)
        )
        object.__setattr__(
            self,
            "expected_observations",
            _freeze_mapping(self.expected_observations),
        )
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPlanBuildRequest:
    """Inputs required to construct one deterministic execution plan."""

    proposal: ExecutionProposal
    authorization: ExecutionAuthorization
    step_specifications: tuple[ExecutionStepSpecification, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        specifications = tuple(self.step_specifications)
        if any(
            not isinstance(specification, ExecutionStepSpecification)
            for specification in specifications
        ):
            raise TypeError(
                "step_specifications must contain ExecutionStepSpecification instances"
            )
        object.__setattr__(self, "step_specifications", specifications)
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPlanBuildResult:
    """Immutable result of deterministic execution-plan construction."""

    disposition: PlanBuildDisposition
    proposal_id: str
    authorization_id: str
    plan: Optional[ExecutionPlan] = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("proposal_id must not be empty")
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be empty")
        reasons = tuple(self.reasons)
        if any(not reason.strip() for reason in reasons):
            raise ValueError("reasons must not contain empty values")
        if self.disposition is PlanBuildDisposition.BUILT:
            if self.plan is None:
                raise ValueError("built result requires a plan")
            if reasons:
                raise ValueError("built result cannot contain rejection reasons")
            if self.plan.proposal_id != self.proposal_id:
                raise ValueError("plan proposal_id must match result proposal_id")
            if self.plan.authorization_id != self.authorization_id:
                raise ValueError(
                    "plan authorization_id must match result authorization_id"
                )
        else:
            if self.plan is not None:
                raise ValueError("rejected result cannot contain a plan")
            if not reasons:
                raise ValueError("rejected result requires at least one reason")
        object.__setattr__(self, "reasons", reasons)

    @property
    def built(self) -> bool:
        """Return whether plan construction succeeded."""

        return self.disposition is PlanBuildDisposition.BUILT


@dataclass(frozen=True, slots=True)
class DeterministicExecutionPlanBuilder:
    """Build immutable plans without translating or delivering operations."""

    plan_id_prefix: str = "execution-plan"

    def __post_init__(self) -> None:
        if not self.plan_id_prefix.strip():
            raise ValueError("plan_id_prefix must not be empty")

    def build(self, request: ExecutionPlanBuildRequest) -> ExecutionPlanBuildResult:
        """Build a plan only for a matching authorized proposal."""

        proposal = request.proposal
        authorization = request.authorization
        rejected: list[str] = []

        if authorization.disposition is not AuthorizationDisposition.AUTHORIZED:
            rejected.append("authorization_not_authorized")
        if authorization.proposal_id != proposal.proposal_id:
            rejected.append("authorization_proposal_mismatch")
        if authorization.evaluated_at < proposal.created_at:
            rejected.append("authorization_precedes_proposal")

        specifications = request.step_specifications
        specification_ids = [spec.operation_id for spec in specifications]
        duplicate_ids = sorted(
            operation_id
            for operation_id in set(specification_ids)
            if specification_ids.count(operation_id) > 1
        )
        rejected.extend(
            f"duplicate_step_specification:{operation_id}"
            for operation_id in duplicate_ids
        )

        proposal_ids = [operation.operation_id for operation in proposal.operations]
        proposal_id_set = set(proposal_ids)
        specification_id_set = set(specification_ids)
        rejected.extend(
            f"missing_step_specification:{operation_id}"
            for operation_id in proposal_ids
            if operation_id not in specification_id_set
        )
        rejected.extend(
            f"unknown_step_specification:{operation_id}"
            for operation_id in sorted(specification_id_set - proposal_id_set)
        )

        rejected_reasons = tuple(dict.fromkeys(rejected))
        if rejected_reasons:
            return ExecutionPlanBuildResult(
                disposition=PlanBuildDisposition.REJECTED,
                proposal_id=proposal.proposal_id,
                authorization_id=authorization.authorization_id,
                reasons=rejected_reasons,
            )

        specification_by_id = {
            specification.operation_id: specification
            for specification in specifications
        }
        plan_id = self._plan_id(request)
        steps = tuple(
            ExecutionStep(
                step_id=f"{plan_id}:step:{sequence}",
                sequence=sequence,
                operation=operation,
                preconditions=specification_by_id[
                    operation.operation_id
                ].preconditions,
                expected_observations=specification_by_id[
                    operation.operation_id
                ].expected_observations,
                verification_required=specification_by_id[
                    operation.operation_id
                ].verification_required,
                metadata=specification_by_id[operation.operation_id].metadata,
            )
            for sequence, operation in enumerate(proposal.operations, start=1)
        )
        plan = ExecutionPlan(
            plan_id=plan_id,
            proposal_id=proposal.proposal_id,
            authorization_id=authorization.authorization_id,
            decision_id=proposal.decision_id,
            context_id=proposal.context_id,
            created_at=authorization.evaluated_at,
            steps=steps,
            expected_final_state=proposal.expected_final_state,
            metadata={
                **dict(request.metadata),
                "runtime_mode": proposal.runtime_mode.value,
                "operation_count": str(len(proposal.operations)),
                "deterministic_builder": "true",
            },
        )
        return ExecutionPlanBuildResult(
            disposition=PlanBuildDisposition.BUILT,
            proposal_id=proposal.proposal_id,
            authorization_id=authorization.authorization_id,
            plan=plan,
        )

    def _plan_id(self, request: ExecutionPlanBuildRequest) -> str:
        specifications = {
            specification.operation_id: {
                "preconditions": dict(specification.preconditions),
                "expected_observations": dict(
                    specification.expected_observations
                ),
                "verification_required": specification.verification_required,
                "metadata": dict(specification.metadata),
            }
            for specification in request.step_specifications
        }
        payload = {
            "proposal_id": request.proposal.proposal_id,
            "authorization_id": request.authorization.authorization_id,
            "operations": [
                operation.operation_id for operation in request.proposal.operations
            ],
            "specifications": specifications,
            "metadata": dict(request.metadata),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return f"{self.plan_id_prefix}:{request.proposal.proposal_id}:{digest}"
