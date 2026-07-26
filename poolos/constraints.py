"""Pluggable command constraints for PoolOS.

Constraints inspect intent after authority resolution and before execution. They
never execute hardware commands. Each constraint returns a structured decision
that may allow, modify, deny, defer, or escalate the command.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional, Protocol

from .commands import Command
from .events import EventBus, PoolEvent
from .kernel import PoolKernel


class ConstraintDisposition(str, Enum):
    """Possible outcomes from one constraint or a complete evaluation."""

    ALLOW = "allow"
    MODIFY = "modify"
    DENY = "deny"
    DEFER = "defer"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class ConstraintContext:
    """Read-only evaluation context supplied to every constraint."""

    kernel: PoolKernel
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("constraint evaluation timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ConstraintDecision:
    """One constraint's explicit decision for a command."""

    constraint_id: str
    disposition: ConstraintDisposition
    command: Command
    reason: str
    decided_at: datetime
    replacement: Optional[Command] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.constraint_id.strip():
            raise ValueError("constraint_id must not be empty")
        if not self.reason.strip():
            raise ValueError("constraint reason must not be empty")
        if self.decided_at.tzinfo is None:
            raise ValueError("constraint decision timestamp must be timezone-aware")
        if self.disposition is ConstraintDisposition.MODIFY and self.replacement is None:
            raise ValueError("MODIFY decisions require a replacement command")
        if self.disposition is not ConstraintDisposition.MODIFY and self.replacement is not None:
            raise ValueError("only MODIFY decisions may include a replacement command")
        object.__setattr__(self, "details", dict(self.details))

    @classmethod
    def allow(cls, constraint_id: str, command: Command, at: datetime, reason: str = "allowed") -> "ConstraintDecision":
        return cls(constraint_id, ConstraintDisposition.ALLOW, command, reason, at)

    @classmethod
    def modify(
        cls,
        constraint_id: str,
        command: Command,
        replacement: Command,
        at: datetime,
        reason: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> "ConstraintDecision":
        return cls(
            constraint_id,
            ConstraintDisposition.MODIFY,
            command,
            reason,
            at,
            replacement=replacement,
            details={} if details is None else details,
        )

    @classmethod
    def deny(cls, constraint_id: str, command: Command, at: datetime, reason: str) -> "ConstraintDecision":
        return cls(constraint_id, ConstraintDisposition.DENY, command, reason, at)

    @classmethod
    def defer(cls, constraint_id: str, command: Command, at: datetime, reason: str) -> "ConstraintDecision":
        return cls(constraint_id, ConstraintDisposition.DEFER, command, reason, at)

    @classmethod
    def escalate(
        cls,
        constraint_id: str,
        command: Command,
        at: datetime,
        reason: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> "ConstraintDecision":
        return cls(
            constraint_id,
            ConstraintDisposition.ESCALATE,
            command,
            reason,
            at,
            details={} if details is None else details,
        )


class Constraint(Protocol):
    """Protocol implemented by constraint plugins."""

    constraint_id: str
    priority: int

    def evaluate(self, command: Command, context: ConstraintContext) -> ConstraintDecision:
        """Evaluate one command without causing side effects."""


@dataclass(frozen=True, slots=True)
class ConstraintEvaluation:
    """Immutable audit record for a full constraint chain."""

    original_command: Command
    effective_command: Optional[Command]
    disposition: ConstraintDisposition
    decisions: tuple[ConstraintDecision, ...]
    evaluated_at: datetime

    @property
    def executable(self) -> bool:
        return self.disposition in {
            ConstraintDisposition.ALLOW,
            ConstraintDisposition.MODIFY,
        } and self.effective_command is not None


@dataclass(slots=True)
class ConstraintEngine:
    """Evaluate commands through an ordered, deterministic constraint chain."""

    events: EventBus = field(default_factory=EventBus)
    _constraints: dict[str, Constraint] = field(default_factory=dict)
    _audit: list[ConstraintEvaluation] = field(default_factory=list)
    _sequence: dict[str, int] = field(default_factory=dict)
    _next_sequence: int = 0

    def register(self, constraint: Constraint, *, replace_existing: bool = False) -> None:
        constraint_id = str(constraint.constraint_id).strip()
        if not constraint_id:
            raise ValueError("constraint_id must not be empty")
        if constraint_id in self._constraints and not replace_existing:
            raise ValueError(f"constraint already registered: {constraint_id}")
        if constraint_id not in self._sequence:
            self._sequence[constraint_id] = self._next_sequence
            self._next_sequence += 1
        self._constraints[constraint_id] = constraint

    def unregister(self, constraint_id: str) -> bool:
        removed = self._constraints.pop(constraint_id, None)
        return removed is not None

    def constraints(self) -> tuple[Constraint, ...]:
        return tuple(
            sorted(
                self._constraints.values(),
                key=lambda item: (
                    -int(getattr(item, "priority", 0)),
                    self._sequence[str(item.constraint_id)],
                    str(item.constraint_id),
                ),
            )
        )

    def evaluate(self, command: Command, kernel: PoolKernel) -> ConstraintEvaluation:
        at = kernel.clock.now()
        context = ConstraintContext(kernel=kernel, evaluated_at=at)
        current = command
        decisions: list[ConstraintDecision] = []
        modified = False
        terminal: Optional[ConstraintDisposition] = None

        for constraint in self.constraints():
            decision = constraint.evaluate(current, context)
            self._validate_decision(constraint, current, decision)
            decisions.append(decision)

            if decision.disposition is ConstraintDisposition.MODIFY:
                current = self._normalize_replacement(command, decision.replacement)
                modified = True
                self._publish_decision(decision, current)
                continue

            if decision.disposition is ConstraintDisposition.ALLOW:
                continue

            terminal = decision.disposition
            self._publish_decision(decision, None)
            break

        disposition = terminal or (
            ConstraintDisposition.MODIFY if modified else ConstraintDisposition.ALLOW
        )
        effective = current if disposition in {
            ConstraintDisposition.ALLOW,
            ConstraintDisposition.MODIFY,
        } else None
        evaluation = ConstraintEvaluation(
            original_command=command,
            effective_command=effective,
            disposition=disposition,
            decisions=tuple(decisions),
            evaluated_at=at,
        )
        self._audit.append(evaluation)
        return evaluation

    def audit_log(self) -> tuple[ConstraintEvaluation, ...]:
        return tuple(self._audit)

    @staticmethod
    def replace_command(command: Command, **changes: Any) -> Command:
        """Return a safe replacement while preserving command identity by default."""

        return replace(command, **changes)

    @staticmethod
    def _normalize_replacement(original: Command, replacement: Optional[Command]) -> Command:
        if replacement is None:
            raise ValueError("constraint replacement is required")
        # A transformed command remains the same logical request for scheduler,
        # deduplication, and audit correlation purposes.
        if replacement.command_id != original.command_id:
            replacement = replace(replacement, command_id=original.command_id)
        return replacement

    @staticmethod
    def _validate_decision(
        constraint: Constraint,
        command: Command,
        decision: ConstraintDecision,
    ) -> None:
        if decision.constraint_id != str(constraint.constraint_id):
            raise ValueError("constraint decision id does not match registered constraint")
        if decision.command != command:
            raise ValueError("constraint decision must reference the evaluated command")

    def _publish_decision(
        self,
        decision: ConstraintDecision,
        effective_command: Optional[Command],
    ) -> None:
        topic = f"constraint.command.{decision.disposition.value}d"
        if decision.disposition is ConstraintDisposition.MODIFY:
            topic = "constraint.command.modified"
        elif decision.disposition is ConstraintDisposition.DENY:
            topic = "constraint.command.denied"
        elif decision.disposition is ConstraintDisposition.DEFER:
            topic = "constraint.command.deferred"
        elif decision.disposition is ConstraintDisposition.ESCALATE:
            topic = "constraint.command.escalated"
        else:
            return
        self.events.publish(
            PoolEvent(
                topic=topic,
                occurred_at=decision.decided_at,
                source=decision.constraint_id,
                payload={
                    "command_id": decision.command.command_id,
                    "target": decision.command.target,
                    "reason": decision.reason,
                    "effective_command": effective_command,
                    "details": dict(decision.details),
                },
            )
        )
