"""Immutable supervisory execution-domain models for PoolOS.

These models define the boundary between command-free decision orchestration and
future execution coordination. They contain canonical :class:`PoolOperation`
objects only; they do not translate, deliver, or verify commands themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .environment import RuntimeMode
from .integration import PoolOperation


def _require_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


class AuthorizationDisposition(str, Enum):
    """Whether a proposal may proceed to execution planning."""

    AUTHORIZED = "authorized"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class ExecutionLifecycleStatus(str, Enum):
    """Lifecycle state shared by execution plans and outcomes."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    PLANNED = "planned"
    EXECUTING = "executing"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"
    SUPERSEDED = "superseded"


class VerificationStatus(str, Enum):
    """Independent verification disposition for one execution step."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionProposal:
    """Immutable request to execute canonical operations for one decision.

    A proposal references the recorded decision and frozen evaluation context
    that produced it. It is not authorization and it performs no delivery.
    """

    proposal_id: str
    decision_id: str
    context_id: str
    objective_id: str
    created_at: datetime
    runtime_mode: RuntimeMode
    operations: tuple[PoolOperation, ...]
    reason: str
    expected_final_state: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposal_id", _require_identifier(self.proposal_id, "proposal_id")
        )
        object.__setattr__(
            self, "decision_id", _require_identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "context_id", _require_identifier(self.context_id, "context_id")
        )
        object.__setattr__(
            self, "objective_id", _require_identifier(self.objective_id, "objective_id")
        )
        object.__setattr__(self, "reason", _require_identifier(self.reason, "reason"))
        _require_aware(self.created_at, "created_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

        operations = tuple(self.operations)
        if not operations:
            raise ValueError("operations must not be empty")
        if any(not isinstance(operation, PoolOperation) for operation in operations):
            raise TypeError("operations must contain only PoolOperation instances")
        operation_ids = [operation.operation_id for operation in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operation IDs must be unique within a proposal")

        object.__setattr__(self, "operations", operations)
        object.__setattr__(
            self,
            "expected_final_state",
            _freeze_mapping(self.expected_final_state),
        )
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorization:
    """Immutable authorization result for one execution proposal."""

    authorization_id: str
    proposal_id: str
    evaluated_at: datetime
    disposition: AuthorizationDisposition
    reason: str
    blocking_reasons: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _require_identifier(self.authorization_id, "authorization_id"),
        )
        object.__setattr__(
            self, "proposal_id", _require_identifier(self.proposal_id, "proposal_id")
        )
        object.__setattr__(self, "reason", _require_identifier(self.reason, "reason"))
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

        blockers = tuple(self.blocking_reasons)
        if any(not blocker.strip() for blocker in blockers):
            raise ValueError("blocking reasons must not be empty")
        if self.disposition is AuthorizationDisposition.AUTHORIZED and blockers:
            raise ValueError("authorized disposition cannot contain blocking reasons")
        if self.disposition in {
            AuthorizationDisposition.DEFERRED,
            AuthorizationDisposition.REJECTED,
        } and not blockers:
            raise ValueError(
                f"{self.disposition.value} disposition requires a blocking reason"
            )

        object.__setattr__(self, "blocking_reasons", blockers)
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))

    @property
    def authorized(self) -> bool:
        """Return whether the proposal is authorized to proceed."""

        return self.disposition is AuthorizationDisposition.AUTHORIZED


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStep:
    """One ordered canonical operation in an execution plan."""

    step_id: str
    sequence: int
    operation: PoolOperation
    preconditions: Mapping[str, Any] = field(default_factory=dict)
    expected_observations: Mapping[str, Any] = field(default_factory=dict)
    verification_required: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _require_identifier(self.step_id, "step_id"))
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        if not isinstance(self.operation, PoolOperation):
            raise TypeError("operation must be a PoolOperation")
        object.__setattr__(
            self,
            "preconditions",
            _freeze_mapping(self.preconditions),
        )
        if self.verification_required and not self.expected_observations:
            raise ValueError(
                "verification-required steps must define expected observations"
            )
        object.__setattr__(
            self,
            "expected_observations",
            _freeze_mapping(self.expected_observations),
        )
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPlan:
    """Deterministic ordered plan derived from one authorized proposal."""

    plan_id: str
    proposal_id: str
    authorization_id: str
    decision_id: str
    context_id: str
    created_at: datetime
    steps: tuple[ExecutionStep, ...]
    status: ExecutionLifecycleStatus = ExecutionLifecycleStatus.AUTHORIZED
    expected_final_state: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "plan_id",
            "proposal_id",
            "authorization_id",
            "decision_id",
            "context_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        _require_aware(self.created_at, "created_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        if self.status not in {
            ExecutionLifecycleStatus.AUTHORIZED,
            ExecutionLifecycleStatus.PENDING,
        }:
            raise ValueError("new execution plans must be pending or authorized")

        steps = tuple(self.steps)
        if not steps:
            raise ValueError("steps must not be empty")
        expected_sequences = list(range(1, len(steps) + 1))
        actual_sequences = [step.sequence for step in steps]
        if actual_sequences != expected_sequences:
            raise ValueError("step sequences must be contiguous and ordered from 1")
        step_ids = [step.step_id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique within a plan")
        operation_ids = [step.operation.operation_id for step in steps]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operation IDs must be unique within a plan")

        object.__setattr__(self, "steps", steps)
        object.__setattr__(
            self,
            "expected_final_state",
            _freeze_mapping(self.expected_final_state),
        )
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class StepOutcome:
    """Immutable delivery and verification outcome for one execution step."""

    step_id: str
    status: ExecutionLifecycleStatus
    verification_status: VerificationStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    receipt_ids: tuple[str, ...] = ()
    failure_reason: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _require_identifier(self.step_id, "step_id"))
        if self.started_at is not None:
            _require_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            _require_aware(self.completed_at, "completed_at")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("completed_at requires started_at")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at")

        receipt_ids = tuple(self.receipt_ids)
        if any(not receipt_id.strip() for receipt_id in receipt_ids):
            raise ValueError("receipt IDs must not be empty")
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("receipt IDs must be unique")

        failure_states = {
            ExecutionLifecycleStatus.REJECTED,
            ExecutionLifecycleStatus.FAILED,
            ExecutionLifecycleStatus.TIMED_OUT,
            ExecutionLifecycleStatus.ABORTED,
            ExecutionLifecycleStatus.SUPERSEDED,
        }
        if self.status in failure_states and not self.failure_reason:
            raise ValueError("failure states require failure_reason")
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _require_identifier(self.failure_reason, "failure_reason"),
            )
        if (
            self.verification_status is VerificationStatus.NOT_REQUIRED
            and self.status is ExecutionLifecycleStatus.VERIFYING
        ):
            raise ValueError("a non-verified step cannot be verifying")

        object.__setattr__(self, "receipt_ids", receipt_ids)
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionOutcome:
    """Complete immutable supervisory result for one execution plan."""

    outcome_id: str
    plan_id: str
    proposal_id: str
    decision_id: str
    context_id: str
    status: ExecutionLifecycleStatus
    started_at: datetime
    completed_at: datetime | None = None
    step_outcomes: tuple[StepOutcome, ...] = ()
    failure_reason: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "outcome_id",
            "plan_id",
            "proposal_id",
            "decision_id",
            "context_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        _require_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            _require_aware(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

        step_outcomes = tuple(self.step_outcomes)
        step_ids = [outcome.step_id for outcome in step_outcomes]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step outcome IDs must be unique")

        terminal_states = {
            ExecutionLifecycleStatus.VERIFIED,
            ExecutionLifecycleStatus.REJECTED,
            ExecutionLifecycleStatus.FAILED,
            ExecutionLifecycleStatus.TIMED_OUT,
            ExecutionLifecycleStatus.ABORTED,
            ExecutionLifecycleStatus.SUPERSEDED,
        }
        failure_states = terminal_states - {ExecutionLifecycleStatus.VERIFIED}
        if self.status in terminal_states and self.completed_at is None:
            raise ValueError("terminal outcomes require completed_at")
        if self.status not in terminal_states and self.completed_at is not None:
            raise ValueError("non-terminal outcomes cannot have completed_at")
        if self.status in failure_states and not self.failure_reason:
            raise ValueError("failure outcomes require failure_reason")
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _require_identifier(self.failure_reason, "failure_reason"),
            )

        object.__setattr__(self, "step_outcomes", step_outcomes)
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))
