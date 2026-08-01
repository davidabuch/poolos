"""Canonical immutable operational-context model for PoolOS.

The context is the minimum command-free snapshot required by operational
routing.  It intentionally excludes observations, forecasts, policies,
planning details, commands, receipts, and delivery state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionLifecycleStatus


_ACTIVE_PLAN_STATUSES = frozenset(
    {
        ExecutionLifecycleStatus.PENDING,
        ExecutionLifecycleStatus.AUTHORIZED,
        ExecutionLifecycleStatus.PLANNED,
        ExecutionLifecycleStatus.EXECUTING,
    }
)


class PendingOperationalAction(str, Enum):
    """Work already handed to another operational subsystem."""

    NONE = "none"
    WAITING = "waiting"
    SUBMITTING = "submitting"
    CANCELLING = "cancelling"
    REPLACING = "replacing"
    SCHEDULING_REEVALUATION = "scheduling_reevaluation"


class ReevaluationState(str, Enum):
    """Summary of deferred reevaluation state, not a scheduler lifecycle."""

    NONE = "none"
    SCHEDULED = "scheduled"
    OVERDUE = "overdue"


class OperationalExecutionState(str, Enum):
    """Small operational summary of execution, not another plan lifecycle."""

    IDLE = "idle"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    FAILED = "failed"
    COMPLETED = "completed"


class OperationalMode(str, Enum):
    """High-level operational posture suitable for routing and diagnostics."""

    NORMAL = "normal"
    WAITING = "waiting"
    BLOCKED = "blocked"
    MANUAL_OVERRIDE = "manual_override"
    SAFE_MODE = "safe_mode"


class OperationalSafetyState(str, Enum):
    """Canonical safety posture visible to operational routing."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    FAULTED = "faulted"
    LOCKED_OUT = "locked_out"


@dataclass(frozen=True, slots=True)
class ActivePlanSummary:
    """Minimal immutable view of one active execution plan."""

    plan_id: str
    lifecycle_state: ExecutionLifecycleStatus
    current_step_id: str | None
    remaining_steps: int
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must not be empty")
        if self.lifecycle_state not in _ACTIVE_PLAN_STATUSES:
            raise ValueError("active plan summary requires an active lifecycle state")
        if self.current_step_id is not None and not self.current_step_id.strip():
            raise ValueError("current_step_id must not be empty when provided")
        if self.remaining_steps < 0:
            raise ValueError("remaining_steps must not be negative")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.lifecycle_state is ExecutionLifecycleStatus.EXECUTING:
            if self.current_step_id is None:
                raise ValueError("executing plan requires current_step_id")
            if self.remaining_steps < 1:
                raise ValueError("executing plan requires at least one remaining step")


@dataclass(frozen=True, slots=True)
class OperationalContext:
    """Complete immutable operational snapshot for one routing evaluation."""

    evaluation_id: str
    captured_at: datetime
    active_plan: ActivePlanSummary | None
    pending_action: PendingOperationalAction
    reevaluation_state: ReevaluationState
    execution_state: OperationalExecutionState
    operational_mode: OperationalMode
    safety_state: OperationalSafetyState
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id must not be empty")
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")

        reasons = tuple(self.blocked_reasons)
        if any(not reason.strip() for reason in reasons):
            raise ValueError("blocked reasons must not be empty")
        if self.operational_mode is OperationalMode.BLOCKED and not reasons:
            raise ValueError("blocked operational mode requires blocked reasons")
        if (
            self.operational_mode
            not in {OperationalMode.BLOCKED, OperationalMode.SAFE_MODE}
            and reasons
        ):
            raise ValueError("blocked reasons require blocked or safe operational mode")

        if self.active_plan is None and self.execution_state in {
            OperationalExecutionState.EXECUTING,
            OperationalExecutionState.VERIFYING,
        }:
            raise ValueError("active execution state requires active_plan")
        if self.active_plan is not None:
            if (
                self.active_plan.lifecycle_state is ExecutionLifecycleStatus.EXECUTING
                and self.execution_state
                not in {
                    OperationalExecutionState.EXECUTING,
                    OperationalExecutionState.VERIFYING,
                }
            ):
                raise ValueError(
                    "executing plan requires executing or verifying operational state"
                )

        if self.pending_action is PendingOperationalAction.SCHEDULING_REEVALUATION:
            if self.reevaluation_state is not ReevaluationState.NONE:
                raise ValueError(
                    "reevaluation cannot already be scheduled while scheduling is pending"
                )

        if self.safety_state is OperationalSafetyState.LOCKED_OUT:
            if self.operational_mode is not OperationalMode.SAFE_MODE:
                raise ValueError("locked-out safety state requires safe mode")
        if self.operational_mode is OperationalMode.SAFE_MODE:
            if self.safety_state not in {
                OperationalSafetyState.FAULTED,
                OperationalSafetyState.LOCKED_OUT,
            }:
                raise ValueError("safe mode requires faulted or locked-out safety state")

        object.__setattr__(self, "blocked_reasons", reasons)
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class OperationalContextFactory:
    """Single authority for constructing normalized operational snapshots."""

    def create(
        self,
        *,
        evaluation_id: str,
        captured_at: datetime,
        active_plan: ActivePlanSummary | None = None,
        pending_action: PendingOperationalAction = PendingOperationalAction.NONE,
        reevaluation_state: ReevaluationState = ReevaluationState.NONE,
        execution_state: OperationalExecutionState = OperationalExecutionState.IDLE,
        safety_state: OperationalSafetyState = OperationalSafetyState.NORMAL,
        manual_override: bool = False,
        blocked_reasons: tuple[str, ...] = (),
        diagnostics: Mapping[str, str] | None = None,
    ) -> OperationalContext:
        """Create one deterministic context and derive its operational mode."""

        reasons = tuple(blocked_reasons)
        mode = self._derive_mode(
            pending_action=pending_action,
            reevaluation_state=reevaluation_state,
            safety_state=safety_state,
            manual_override=manual_override,
            blocked_reasons=reasons,
        )
        normalized_diagnostics = {
            **dict(diagnostics or {}),
            "active_plan_id": active_plan.plan_id if active_plan else "none",
            "pending_action": pending_action.value,
            "reevaluation_state": reevaluation_state.value,
            "execution_state": execution_state.value,
            "operational_mode": mode.value,
            "safety_state": safety_state.value,
        }
        return OperationalContext(
            evaluation_id=evaluation_id,
            captured_at=captured_at,
            active_plan=active_plan,
            pending_action=pending_action,
            reevaluation_state=reevaluation_state,
            execution_state=execution_state,
            operational_mode=mode,
            safety_state=safety_state,
            blocked_reasons=reasons,
            diagnostics=normalized_diagnostics,
        )

    @staticmethod
    def _derive_mode(
        *,
        pending_action: PendingOperationalAction,
        reevaluation_state: ReevaluationState,
        safety_state: OperationalSafetyState,
        manual_override: bool,
        blocked_reasons: tuple[str, ...],
    ) -> OperationalMode:
        if safety_state in {
            OperationalSafetyState.FAULTED,
            OperationalSafetyState.LOCKED_OUT,
        }:
            return OperationalMode.SAFE_MODE
        if blocked_reasons:
            return OperationalMode.BLOCKED
        if manual_override:
            return OperationalMode.MANUAL_OVERRIDE
        if (
            pending_action is PendingOperationalAction.WAITING
            or reevaluation_state is not ReevaluationState.NONE
        ):
            return OperationalMode.WAITING
        return OperationalMode.NORMAL
