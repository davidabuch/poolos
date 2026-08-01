"""Canonical per-step execution lifecycle for closed-loop execution.

Plan lifecycle describes the whole plan.  This module describes one step and
prevents delivery and verification states from replacing the plan's
``EXECUTING`` state while additional steps remain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping


class ExecutionStepStatus(str, Enum):
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStepTransition:
    transition_id: str
    plan_id: str
    step_id: str
    from_status: ExecutionStepStatus
    to_status: ExecutionStepStatus
    occurred_at: datetime
    reason: str
    actor: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("transition_id", "plan_id", "step_id", "reason", "actor"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.from_status is self.to_status:
            raise ValueError("step transition must change status")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStepLifecycle:
    plan_id: str
    step_id: str
    status: ExecutionStepStatus
    initialized_at: datetime
    updated_at: datetime
    transitions: tuple[ExecutionStepTransition, ...] = ()

    def __post_init__(self) -> None:
        for name in ("plan_id", "step_id"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.initialized_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("step lifecycle timestamps must be timezone-aware")
        if self.updated_at < self.initialized_at:
            raise ValueError("updated_at cannot precede initialized_at")
        transitions = tuple(self.transitions)
        previous = self.initialized_at
        status = ExecutionStepStatus.PENDING
        seen: set[str] = set()
        for transition in transitions:
            if transition.plan_id != self.plan_id or transition.step_id != self.step_id:
                raise ValueError("step transition lineage mismatch")
            if transition.transition_id in seen:
                raise ValueError("step transition IDs must be unique")
            if transition.occurred_at < previous:
                raise ValueError("step transitions must be chronologically ordered")
            if transition.from_status is not status:
                raise ValueError("step transition history is not contiguous")
            seen.add(transition.transition_id)
            previous = transition.occurred_at
            status = transition.to_status
        if status is not self.status:
            raise ValueError("status must match final step transition")
        if transitions and self.updated_at != transitions[-1].occurred_at:
            raise ValueError("updated_at must match final step transition")
        if not transitions and self.status is not ExecutionStepStatus.PENDING:
            raise ValueError("new step lifecycle must be pending")
        object.__setattr__(self, "transitions", transitions)

    @property
    def terminal(self) -> bool:
        return self.status in {
            ExecutionStepStatus.VERIFIED,
            ExecutionStepStatus.FAILED,
            ExecutionStepStatus.TIMED_OUT,
            ExecutionStepStatus.ABORTED,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStepTransitionResult:
    lifecycle: ExecutionStepLifecycle
    transition: ExecutionStepTransition | None
    rejection_reason: str | None = None

    @property
    def applied(self) -> bool:
        return self.transition is not None


@dataclass(frozen=True, slots=True)
class ExecutionStepStateMachine:
    LEGAL_TRANSITIONS = MappingProxyType(
        {
            ExecutionStepStatus.PENDING: frozenset(
                {ExecutionStepStatus.DELIVERING, ExecutionStepStatus.ABORTED}
            ),
            ExecutionStepStatus.DELIVERING: frozenset(
                {
                    ExecutionStepStatus.DELIVERED,
                    ExecutionStepStatus.FAILED,
                    ExecutionStepStatus.TIMED_OUT,
                    ExecutionStepStatus.ABORTED,
                }
            ),
            ExecutionStepStatus.DELIVERED: frozenset(
                {
                    ExecutionStepStatus.VERIFYING,
                    ExecutionStepStatus.VERIFIED,
                    ExecutionStepStatus.FAILED,
                    ExecutionStepStatus.TIMED_OUT,
                    ExecutionStepStatus.ABORTED,
                }
            ),
            ExecutionStepStatus.VERIFYING: frozenset(
                {
                    ExecutionStepStatus.VERIFIED,
                    ExecutionStepStatus.FAILED,
                    ExecutionStepStatus.TIMED_OUT,
                    ExecutionStepStatus.ABORTED,
                }
            ),
        }
    )

    def initialize(
        self, *, plan_id: str, step_id: str, initialized_at: datetime
    ) -> ExecutionStepLifecycle:
        return ExecutionStepLifecycle(
            plan_id=plan_id,
            step_id=step_id,
            status=ExecutionStepStatus.PENDING,
            initialized_at=initialized_at,
            updated_at=initialized_at,
        )

    def transition(
        self,
        lifecycle: ExecutionStepLifecycle,
        *,
        to_status: ExecutionStepStatus,
        occurred_at: datetime,
        reason: str,
        actor: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionStepTransitionResult:
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if lifecycle.terminal:
            return ExecutionStepTransitionResult(
                lifecycle=lifecycle, transition=None, rejection_reason="terminal_step_cannot_transition"
            )
        if occurred_at < lifecycle.updated_at:
            return ExecutionStepTransitionResult(
                lifecycle=lifecycle,
                transition=None,
                rejection_reason="transition_time_precedes_step_state",
            )
        allowed = self.LEGAL_TRANSITIONS.get(lifecycle.status, frozenset())
        if to_status not in allowed:
            return ExecutionStepTransitionResult(
                lifecycle=lifecycle,
                transition=None,
                rejection_reason=f"illegal_step_transition:{lifecycle.status.value}->{to_status.value}",
            )
        data = {
            "plan_id": lifecycle.plan_id,
            "step_id": lifecycle.step_id,
            "from": lifecycle.status.value,
            "to": to_status.value,
            "occurred_at": occurred_at.isoformat(),
            "reason": reason,
            "actor": actor,
            "metadata": dict(metadata or {}),
        }
        digest = sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
        transition = ExecutionStepTransition(
            transition_id=f"step-transition:{digest}",
            plan_id=lifecycle.plan_id,
            step_id=lifecycle.step_id,
            from_status=lifecycle.status,
            to_status=to_status,
            occurred_at=occurred_at,
            reason=reason,
            actor=actor,
            metadata=dict(metadata or {}),
        )
        updated = ExecutionStepLifecycle(
            plan_id=lifecycle.plan_id,
            step_id=lifecycle.step_id,
            status=to_status,
            initialized_at=lifecycle.initialized_at,
            updated_at=occurred_at,
            transitions=(*lifecycle.transitions, transition),
        )
        return ExecutionStepTransitionResult(lifecycle=updated, transition=transition)
