"""Authoritative execution lifecycle state machine for PoolOS.

The state machine is a pure domain component. It validates and records
execution lifecycle transitions but does not coordinate steps, translate
operations, deliver commands, inspect Home Assistant, or contact equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionLifecycleStatus, ExecutionPlan


class TransitionDisposition(str, Enum):
    """Result of requesting one lifecycle transition."""

    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStateTransition:
    """Immutable audit record for one accepted lifecycle transition."""

    transition_id: str
    plan_id: str
    from_status: ExecutionLifecycleStatus
    to_status: ExecutionLifecycleStatus
    occurred_at: datetime
    reason: str
    actor: str = "execution-state-machine"
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in ("transition_id", "plan_id", "reason", "actor"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.from_status is self.to_status:
            raise ValueError("a transition must change lifecycle status")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionLifecycle:
    """Immutable current lifecycle state and accepted transition history."""

    plan_id: str
    initial_status: ExecutionLifecycleStatus
    status: ExecutionLifecycleStatus
    initialized_at: datetime
    updated_at: datetime
    transitions: tuple[ExecutionStateTransition, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        plan_id = self.plan_id.strip()
        if not plan_id:
            raise ValueError("plan_id must not be empty")
        object.__setattr__(self, "plan_id", plan_id)
        if self.initialized_at.tzinfo is None:
            raise ValueError("initialized_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.updated_at < self.initialized_at:
            raise ValueError("updated_at cannot precede initialized_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

        transitions = tuple(self.transitions)
        previous_status: ExecutionLifecycleStatus = self.initial_status
        previous_time = self.initialized_at
        transition_ids: set[str] = set()
        for transition in transitions:
            if transition.plan_id != self.plan_id:
                raise ValueError("all transitions must reference the lifecycle plan")
            if transition.transition_id in transition_ids:
                raise ValueError("transition IDs must be unique")
            if transition.occurred_at < previous_time:
                raise ValueError("transitions must be chronologically ordered")
            if transition.from_status is not previous_status:
                raise ValueError("transition history must be status-contiguous")
            transition_ids.add(transition.transition_id)
            previous_status = transition.to_status
            previous_time = transition.occurred_at

        if transitions:
            if transitions[-1].to_status is not self.status:
                raise ValueError("lifecycle status must match the final transition")
            if transitions[-1].occurred_at != self.updated_at:
                raise ValueError("updated_at must match the final transition time")
        else:
            if self.status is not self.initial_status:
                raise ValueError("an untransitioned lifecycle must remain at initial_status")
            if self.updated_at != self.initialized_at:
                raise ValueError("an untransitioned lifecycle cannot change updated_at")

        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def terminal(self) -> bool:
        """Return whether no further lifecycle transition is permitted."""

        return self.status in ExecutionStateMachine.TERMINAL_STATUSES


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionTransitionResult:
    """Result of applying or rejecting a requested transition."""

    disposition: TransitionDisposition
    lifecycle: ExecutionLifecycle
    transition: ExecutionStateTransition | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.disposition is TransitionDisposition.APPLIED:
            if self.transition is None or self.rejection_reason is not None:
                raise ValueError("applied transitions require a transition record only")
        else:
            if self.transition is not None or not self.rejection_reason:
                raise ValueError("rejected transitions require a rejection reason only")

    @property
    def applied(self) -> bool:
        """Return whether the requested transition was accepted."""

        return self.disposition is TransitionDisposition.APPLIED


@dataclass(frozen=True, slots=True)
class ExecutionStateMachine:
    """Validate and record the canonical execution lifecycle."""

    LEGAL_TRANSITIONS = MappingProxyType(
        {
            ExecutionLifecycleStatus.PENDING: frozenset(
                {
                    ExecutionLifecycleStatus.AUTHORIZED,
                    ExecutionLifecycleStatus.REJECTED,
                    ExecutionLifecycleStatus.ABORTED,
                    ExecutionLifecycleStatus.SUPERSEDED,
                }
            ),
            ExecutionLifecycleStatus.AUTHORIZED: frozenset(
                {
                    ExecutionLifecycleStatus.PLANNED,
                    ExecutionLifecycleStatus.REJECTED,
                    ExecutionLifecycleStatus.ABORTED,
                    ExecutionLifecycleStatus.SUPERSEDED,
                }
            ),
            ExecutionLifecycleStatus.PLANNED: frozenset(
                {
                    ExecutionLifecycleStatus.EXECUTING,
                    ExecutionLifecycleStatus.ABORTED,
                    ExecutionLifecycleStatus.SUPERSEDED,
                }
            ),
            ExecutionLifecycleStatus.EXECUTING: frozenset(
                {
                    ExecutionLifecycleStatus.DELIVERING,
                    ExecutionLifecycleStatus.FAILED,
                    ExecutionLifecycleStatus.TIMED_OUT,
                    ExecutionLifecycleStatus.ABORTED,
                    ExecutionLifecycleStatus.SUPERSEDED,
                }
            ),
            ExecutionLifecycleStatus.DELIVERING: frozenset(
                {
                    ExecutionLifecycleStatus.DELIVERED,
                    ExecutionLifecycleStatus.FAILED,
                    ExecutionLifecycleStatus.TIMED_OUT,
                    ExecutionLifecycleStatus.ABORTED,
                }
            ),
            ExecutionLifecycleStatus.DELIVERED: frozenset(
                {
                    ExecutionLifecycleStatus.VERIFYING,
                    ExecutionLifecycleStatus.VERIFIED,
                    ExecutionLifecycleStatus.FAILED,
                    ExecutionLifecycleStatus.TIMED_OUT,
                    ExecutionLifecycleStatus.ABORTED,
                }
            ),
            ExecutionLifecycleStatus.VERIFYING: frozenset(
                {
                    ExecutionLifecycleStatus.VERIFIED,
                    ExecutionLifecycleStatus.FAILED,
                    ExecutionLifecycleStatus.TIMED_OUT,
                    ExecutionLifecycleStatus.ABORTED,
                }
            ),
            ExecutionLifecycleStatus.VERIFIED: frozenset(
                {ExecutionLifecycleStatus.COMPLETED}
            ),
        }
    )

    TERMINAL_STATUSES = frozenset(
        {
            ExecutionLifecycleStatus.COMPLETED,
            ExecutionLifecycleStatus.REJECTED,
            ExecutionLifecycleStatus.FAILED,
            ExecutionLifecycleStatus.TIMED_OUT,
            ExecutionLifecycleStatus.ABORTED,
            ExecutionLifecycleStatus.SUPERSEDED,
        }
    )

    def initialize(self, plan: ExecutionPlan) -> ExecutionLifecycle:
        """Create lifecycle state for a newly built execution plan."""

        return ExecutionLifecycle(
            plan_id=plan.plan_id,
            initial_status=plan.status,
            status=plan.status,
            initialized_at=plan.created_at,
            updated_at=plan.created_at,
            metadata={
                "proposal_id": plan.proposal_id,
                "authorization_id": plan.authorization_id,
                "decision_id": plan.decision_id,
                "context_id": plan.context_id,
            },
        )

    def allowed_targets(
        self, status: ExecutionLifecycleStatus
    ) -> frozenset[ExecutionLifecycleStatus]:
        """Return the legal next statuses from ``status``."""

        return self.LEGAL_TRANSITIONS.get(status, frozenset())

    def can_transition(
        self,
        from_status: ExecutionLifecycleStatus,
        to_status: ExecutionLifecycleStatus,
    ) -> bool:
        """Return whether the requested status change is legal."""

        return to_status in self.allowed_targets(from_status)

    def transition(
        self,
        lifecycle: ExecutionLifecycle,
        *,
        to_status: ExecutionLifecycleStatus,
        occurred_at: datetime,
        reason: str,
        actor: str = "execution-state-machine",
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionTransitionResult:
        """Apply one legal transition or return an explicit rejection."""

        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if occurred_at < lifecycle.updated_at:
            return self._rejected(lifecycle, "transition_time_precedes_current_state")
        if lifecycle.terminal:
            return self._rejected(lifecycle, "terminal_state_cannot_transition")
        if to_status is lifecycle.status:
            return self._rejected(lifecycle, "status_unchanged")
        if not self.can_transition(lifecycle.status, to_status):
            return self._rejected(
                lifecycle,
                f"illegal_transition:{lifecycle.status.value}->{to_status.value}",
            )

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason must not be empty")
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise ValueError("actor must not be empty")
        transition_metadata = dict(metadata or {})
        transition_id = self._transition_id(
            lifecycle=lifecycle,
            to_status=to_status,
            occurred_at=occurred_at,
            reason=normalized_reason,
            actor=normalized_actor,
            metadata=transition_metadata,
        )
        transition = ExecutionStateTransition(
            transition_id=transition_id,
            plan_id=lifecycle.plan_id,
            from_status=lifecycle.status,
            to_status=to_status,
            occurred_at=occurred_at,
            reason=normalized_reason,
            actor=normalized_actor,
            metadata=transition_metadata,
        )
        updated = ExecutionLifecycle(
            plan_id=lifecycle.plan_id,
            initial_status=lifecycle.initial_status,
            status=to_status,
            initialized_at=lifecycle.initialized_at,
            updated_at=occurred_at,
            transitions=(*lifecycle.transitions, transition),
            metadata=lifecycle.metadata,
        )
        return ExecutionTransitionResult(
            disposition=TransitionDisposition.APPLIED,
            lifecycle=updated,
            transition=transition,
        )

    @staticmethod
    def _rejected(
        lifecycle: ExecutionLifecycle, reason: str
    ) -> ExecutionTransitionResult:
        return ExecutionTransitionResult(
            disposition=TransitionDisposition.REJECTED,
            lifecycle=lifecycle,
            rejection_reason=reason,
        )

    @staticmethod
    def _transition_id(
        *,
        lifecycle: ExecutionLifecycle,
        to_status: ExecutionLifecycleStatus,
        occurred_at: datetime,
        reason: str,
        actor: str,
        metadata: Mapping[str, str],
    ) -> str:
        payload = {
            "plan_id": lifecycle.plan_id,
            "from_status": lifecycle.status.value,
            "to_status": to_status.value,
            "occurred_at": occurred_at.isoformat(),
            "reason": reason,
            "actor": actor,
            "transition_number": len(lifecycle.transitions) + 1,
            "metadata": dict(metadata),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = sha256(canonical.encode("utf-8")).hexdigest()[:20]
        return f"execution-transition:{lifecycle.plan_id}:{digest}"
