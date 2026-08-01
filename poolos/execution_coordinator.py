"""Pure execution-plan coordination for PoolOS.

The coordinator admits an immutable execution plan, advances its lifecycle
through planning and execution readiness, selects exactly one current step,
and records explicit step-completion signals. It does not translate operations,
deliver commands, verify observations, or contact external systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from .execution_state_machine import (
    ExecutionLifecycle,
    ExecutionStateMachine,
    ExecutionStateTransition,
)


def _require_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


class CoordinationDisposition(str, Enum):
    """Result of one coordinator request."""

    ADVANCED = "advanced"
    READY = "ready"
    STOPPED = "stopped"
    REJECTED = "rejected"


class CoordinationEventKind(str, Enum):
    """Auditable coordinator events independent from lifecycle transitions."""

    PLAN_ADMITTED = "plan_admitted"
    EXECUTION_STARTED = "execution_started"
    STEP_SELECTED = "step_selected"
    STEP_COMPLETED = "step_completed"
    PLAN_STEPS_EXHAUSTED = "plan_steps_exhausted"
    PLAN_COMPLETED = "plan_completed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCoordinationEvent:
    """Immutable audit record for one accepted coordinator action."""

    event_id: str
    plan_id: str
    kind: CoordinationEventKind
    occurred_at: datetime
    reason: str
    step_id: str | None = None
    lifecycle_transition_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _require_identifier(self.event_id, "event_id")
        )
        object.__setattr__(
            self, "plan_id", _require_identifier(self.plan_id, "plan_id")
        )
        object.__setattr__(self, "reason", _require_identifier(self.reason, "reason"))
        _require_aware(self.occurred_at, "occurred_at")
        if self.step_id is not None:
            object.__setattr__(
                self, "step_id", _require_identifier(self.step_id, "step_id")
            )
        if self.lifecycle_transition_id is not None:
            object.__setattr__(
                self,
                "lifecycle_transition_id",
                _require_identifier(
                    self.lifecycle_transition_id, "lifecycle_transition_id"
                ),
            )
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCoordinationSession:
    """Immutable coordinator cursor for one execution plan."""

    plan_id: str
    lifecycle: ExecutionLifecycle
    current_step_sequence: int | None
    completed_step_ids: tuple[str, ...]
    stopped: bool
    stop_reason: str | None
    initialized_at: datetime
    updated_at: datetime
    events: tuple[ExecutionCoordinationEvent, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _require_identifier(self.plan_id, "plan_id")
        )
        if self.lifecycle.plan_id != self.plan_id:
            raise ValueError("lifecycle must reference the session plan")
        _require_aware(self.initialized_at, "initialized_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.initialized_at:
            raise ValueError("updated_at cannot precede initialized_at")
        if self.current_step_sequence is not None and self.current_step_sequence < 1:
            raise ValueError("current_step_sequence must be at least 1")
        completed = tuple(self.completed_step_ids)
        if any(not step_id.strip() for step_id in completed):
            raise ValueError("completed step IDs must not be empty")
        if len(completed) != len(set(completed)):
            raise ValueError("completed step IDs must be unique")
        if self.stopped and not self.stop_reason:
            raise ValueError("stopped sessions require stop_reason")
        if not self.stopped and self.stop_reason is not None:
            raise ValueError("active sessions cannot contain stop_reason")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")

        events = tuple(self.events)
        event_ids: set[str] = set()
        previous_time = self.initialized_at
        for event in events:
            if event.plan_id != self.plan_id:
                raise ValueError("all events must reference the session plan")
            if event.event_id in event_ids:
                raise ValueError("coordination event IDs must be unique")
            if event.occurred_at < previous_time:
                raise ValueError("coordination events must be chronologically ordered")
            event_ids.add(event.event_id)
            previous_time = event.occurred_at
        if events and events[-1].occurred_at != self.updated_at:
            raise ValueError("updated_at must match the final coordination event")
        if not events and self.updated_at != self.initialized_at:
            raise ValueError("an event-free session cannot change updated_at")

        object.__setattr__(self, "completed_step_ids", completed)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCoordinationResult:
    """Immutable result of one coordinator action."""

    disposition: CoordinationDisposition
    session: ExecutionCoordinationSession
    current_step: ExecutionStep | None = None
    event: ExecutionCoordinationEvent | None = None
    lifecycle_transition: ExecutionStateTransition | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.disposition is CoordinationDisposition.REJECTED:
            if not self.rejection_reason:
                raise ValueError("rejected coordination requires rejection_reason")
            if self.event is not None or self.lifecycle_transition is not None:
                raise ValueError(
                    "rejected coordination cannot contain accepted artifacts"
                )
        elif self.rejection_reason is not None:
            raise ValueError("accepted coordination cannot contain rejection_reason")

    @property
    def accepted(self) -> bool:
        """Return whether the coordinator accepted the request."""

        return self.disposition is not CoordinationDisposition.REJECTED


@dataclass(frozen=True, slots=True)
class ExecutionCoordinator:
    """Coordinate one plan without translating, delivering, or verifying it."""

    state_machine: ExecutionStateMachine = field(default_factory=ExecutionStateMachine)
    actor: str = "execution-coordinator"

    def __post_init__(self) -> None:
        if not self.actor.strip():
            raise ValueError("actor must not be empty")

    def admit(
        self,
        plan: ExecutionPlan,
        *,
        occurred_at: datetime,
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionCoordinationResult:
        """Admit one authorized plan and transition it to ``PLANNED``."""

        _require_aware(occurred_at, "occurred_at")
        lifecycle = self.state_machine.initialize(plan)
        if lifecycle.status is not ExecutionLifecycleStatus.AUTHORIZED:
            return self._rejected_session(
                plan,
                lifecycle,
                occurred_at,
                "plan_not_authorized",
            )
        transition_result = self.state_machine.transition(
            lifecycle,
            to_status=ExecutionLifecycleStatus.PLANNED,
            occurred_at=occurred_at,
            reason="Execution plan admitted by coordinator.",
            actor=self.actor,
            metadata={"coordination_action": "admit"},
        )
        if not transition_result.applied or transition_result.transition is None:
            return self._rejected_session(
                plan,
                lifecycle,
                occurred_at,
                transition_result.rejection_reason or "plan_admission_rejected",
            )
        event = self._event(
            plan_id=plan.plan_id,
            kind=CoordinationEventKind.PLAN_ADMITTED,
            occurred_at=occurred_at,
            reason="Authorized plan admitted for deterministic coordination.",
            lifecycle_transition_id=transition_result.transition.transition_id,
            metadata=metadata,
        )
        session = ExecutionCoordinationSession(
            plan_id=plan.plan_id,
            lifecycle=transition_result.lifecycle,
            current_step_sequence=None,
            completed_step_ids=(),
            stopped=False,
            stop_reason=None,
            initialized_at=plan.created_at,
            updated_at=occurred_at,
            events=(event,),
            metadata={
                "proposal_id": plan.proposal_id,
                "decision_id": plan.decision_id,
                "context_id": plan.context_id,
            },
        )
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.ADVANCED,
            session=session,
            event=event,
            lifecycle_transition=transition_result.transition,
        )

    def start(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        *,
        occurred_at: datetime,
    ) -> ExecutionCoordinationResult:
        """Start deterministic coordination and select the first step."""

        rejection = self._validate(plan, session, occurred_at)
        if rejection is not None:
            return self._rejected(session, rejection)
        if session.lifecycle.status is not ExecutionLifecycleStatus.PLANNED:
            return self._rejected(session, "session_not_planned")
        transition_result = self.state_machine.transition(
            session.lifecycle,
            to_status=ExecutionLifecycleStatus.EXECUTING,
            occurred_at=occurred_at,
            reason="Execution coordination started.",
            actor=self.actor,
            metadata={"coordination_action": "start"},
        )
        if not transition_result.applied or transition_result.transition is None:
            return self._rejected(
                session,
                transition_result.rejection_reason or "execution_start_rejected",
            )
        first_step = plan.steps[0]
        event = self._event(
            plan_id=plan.plan_id,
            kind=CoordinationEventKind.EXECUTION_STARTED,
            occurred_at=occurred_at,
            reason="Coordinator selected the first plan step.",
            step_id=first_step.step_id,
            lifecycle_transition_id=transition_result.transition.transition_id,
        )
        updated = self._updated_session(
            session,
            lifecycle=transition_result.lifecycle,
            current_step_sequence=1,
            occurred_at=occurred_at,
            event=event,
        )
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.READY,
            session=updated,
            current_step=first_step,
            event=event,
            lifecycle_transition=transition_result.transition,
        )

    def complete_plan(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        *,
        occurred_at: datetime,
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionCoordinationResult:
        """Complete a stopped plan only after every step was acknowledged."""

        rejection = self._validate(plan, session, occurred_at)
        if rejection is not None:
            return self._rejected(session, rejection)
        if not session.stopped or session.stop_reason != "plan_steps_exhausted":
            return self._rejected(session, "plan_steps_not_exhausted")
        if tuple(session.completed_step_ids) != tuple(step.step_id for step in plan.steps):
            return self._rejected(session, "plan_steps_not_all_completed")
        if session.lifecycle.status is not ExecutionLifecycleStatus.EXECUTING:
            return self._rejected(session, "session_not_executing")
        transition_result = self.state_machine.transition(
            session.lifecycle,
            to_status=ExecutionLifecycleStatus.COMPLETED,
            occurred_at=occurred_at,
            reason="All execution-plan steps completed after verification.",
            actor=self.actor,
            metadata={"coordination_action": "complete_plan"},
        )
        if not transition_result.applied or transition_result.transition is None:
            return self._rejected(
                session,
                transition_result.rejection_reason or "plan_completion_rejected",
            )
        event = self._event(
            plan_id=plan.plan_id,
            kind=CoordinationEventKind.PLAN_COMPLETED,
            occurred_at=occurred_at,
            reason="Coordinator completed the fully verified execution plan.",
            lifecycle_transition_id=transition_result.transition.transition_id,
            metadata=metadata,
        )
        updated = self._updated_session(
            session,
            lifecycle=transition_result.lifecycle,
            current_step_sequence=None,
            completed_step_ids=session.completed_step_ids,
            stopped=True,
            stop_reason="plan_completed",
            occurred_at=occurred_at,
            event=event,
        )
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.STOPPED,
            session=updated,
            event=event,
            lifecycle_transition=transition_result.transition,
        )

    def current_step(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
    ) -> ExecutionCoordinationResult:
        """Return the one currently selected step without mutating the session."""

        rejection = self._validate_plan_session(plan, session)
        if rejection is not None:
            return self._rejected(session, rejection)
        if session.stopped:
            return ExecutionCoordinationResult(
                disposition=CoordinationDisposition.STOPPED,
                session=session,
            )
        if session.lifecycle.status is not ExecutionLifecycleStatus.EXECUTING:
            return self._rejected(session, "session_not_executing")
        if session.current_step_sequence is None:
            return self._rejected(session, "current_step_not_selected")
        if session.current_step_sequence > len(plan.steps):
            return self._rejected(session, "current_step_out_of_range")
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.READY,
            session=session,
            current_step=plan.steps[session.current_step_sequence - 1],
        )

    def acknowledge_step_completion(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        *,
        step_id: str,
        occurred_at: datetime,
        reason: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionCoordinationResult:
        """Advance the cursor after an external component reports completion.

        This method records the completion signal but does not determine whether
        delivery or verification actually succeeded. Those responsibilities
        belong to later execution-pipeline components.
        """

        rejection = self._validate(plan, session, occurred_at)
        if rejection is not None:
            return self._rejected(session, rejection)
        if session.stopped:
            return self._rejected(session, "session_already_stopped")
        if session.lifecycle.status is not ExecutionLifecycleStatus.EXECUTING:
            return self._rejected(session, "session_not_executing")
        if session.current_step_sequence is None:
            return self._rejected(session, "current_step_not_selected")
        current_step = plan.steps[session.current_step_sequence - 1]
        normalized_step_id = _require_identifier(step_id, "step_id")
        if normalized_step_id != current_step.step_id:
            return self._rejected(session, "step_completion_out_of_order")
        if normalized_step_id in session.completed_step_ids:
            return self._rejected(session, "step_already_completed")

        normalized_reason = _require_identifier(reason, "reason")
        completed = (*session.completed_step_ids, normalized_step_id)
        if session.current_step_sequence == len(plan.steps):
            event = self._event(
                plan_id=plan.plan_id,
                kind=CoordinationEventKind.PLAN_STEPS_EXHAUSTED,
                occurred_at=occurred_at,
                reason=normalized_reason,
                step_id=normalized_step_id,
                metadata=metadata,
            )
            updated = self._updated_session(
                session,
                current_step_sequence=None,
                completed_step_ids=completed,
                stopped=True,
                stop_reason="plan_steps_exhausted",
                occurred_at=occurred_at,
                event=event,
            )
            return ExecutionCoordinationResult(
                disposition=CoordinationDisposition.STOPPED,
                session=updated,
                event=event,
            )

        next_sequence = session.current_step_sequence + 1
        next_step = plan.steps[next_sequence - 1]
        event = self._event(
            plan_id=plan.plan_id,
            kind=CoordinationEventKind.STEP_COMPLETED,
            occurred_at=occurred_at,
            reason=normalized_reason,
            step_id=normalized_step_id,
            metadata={
                **dict(metadata or {}),
                "next_step_id": next_step.step_id,
            },
        )
        updated = self._updated_session(
            session,
            current_step_sequence=next_sequence,
            completed_step_ids=completed,
            occurred_at=occurred_at,
            event=event,
        )
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.READY,
            session=updated,
            current_step=next_step,
            event=event,
        )

    @staticmethod
    def _validate_plan_session(
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
    ) -> str | None:
        if session.plan_id != plan.plan_id:
            return "session_plan_mismatch"
        completed_ids = set(session.completed_step_ids)
        plan_ids = {step.step_id for step in plan.steps}
        if not completed_ids.issubset(plan_ids):
            return "completed_step_not_in_plan"
        return None

    def _validate(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        occurred_at: datetime,
    ) -> str | None:
        _require_aware(occurred_at, "occurred_at")
        mismatch = self._validate_plan_session(plan, session)
        if mismatch is not None:
            return mismatch
        if occurred_at < session.updated_at:
            return "coordination_time_precedes_current_state"
        if session.lifecycle.terminal:
            return "terminal_lifecycle_cannot_coordinate"
        return None

    def _event(
        self,
        *,
        plan_id: str,
        kind: CoordinationEventKind,
        occurred_at: datetime,
        reason: str,
        step_id: str | None = None,
        lifecycle_transition_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ExecutionCoordinationEvent:
        event_metadata = dict(metadata or {})
        payload = {
            "plan_id": plan_id,
            "kind": kind.value,
            "occurred_at": occurred_at.isoformat(),
            "reason": reason,
            "step_id": step_id,
            "lifecycle_transition_id": lifecycle_transition_id,
            "metadata": event_metadata,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()[:20]
        event_id = f"coordination-event:{digest}"
        return ExecutionCoordinationEvent(
            event_id=event_id,
            plan_id=plan_id,
            kind=kind,
            occurred_at=occurred_at,
            reason=reason,
            step_id=step_id,
            lifecycle_transition_id=lifecycle_transition_id,
            metadata=event_metadata,
        )

    @staticmethod
    def _updated_session(
        session: ExecutionCoordinationSession,
        *,
        occurred_at: datetime,
        event: ExecutionCoordinationEvent,
        lifecycle: ExecutionLifecycle | None = None,
        current_step_sequence: int | None = None,
        completed_step_ids: tuple[str, ...] | None = None,
        stopped: bool | None = None,
        stop_reason: str | None = None,
    ) -> ExecutionCoordinationSession:
        return ExecutionCoordinationSession(
            plan_id=session.plan_id,
            lifecycle=lifecycle or session.lifecycle,
            current_step_sequence=current_step_sequence,
            completed_step_ids=(
                session.completed_step_ids
                if completed_step_ids is None
                else completed_step_ids
            ),
            stopped=session.stopped if stopped is None else stopped,
            stop_reason=(session.stop_reason if stopped is None else stop_reason),
            initialized_at=session.initialized_at,
            updated_at=occurred_at,
            events=(*session.events, event),
            metadata=session.metadata,
        )

    @staticmethod
    def _rejected(
        session: ExecutionCoordinationSession,
        reason: str,
    ) -> ExecutionCoordinationResult:
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.REJECTED,
            session=session,
            rejection_reason=reason,
        )

    @staticmethod
    def _rejected_session(
        plan: ExecutionPlan,
        lifecycle: ExecutionLifecycle,
        occurred_at: datetime,
        reason: str,
    ) -> ExecutionCoordinationResult:
        session = ExecutionCoordinationSession(
            plan_id=plan.plan_id,
            lifecycle=lifecycle,
            current_step_sequence=None,
            completed_step_ids=(),
            stopped=False,
            stop_reason=None,
            initialized_at=plan.created_at,
            updated_at=plan.created_at,
            metadata={
                "proposal_id": plan.proposal_id,
                "decision_id": plan.decision_id,
                "context_id": plan.context_id,
            },
        )
        del occurred_at
        return ExecutionCoordinationResult(
            disposition=CoordinationDisposition.REJECTED,
            session=session,
            rejection_reason=reason,
        )
