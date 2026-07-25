"""Synchronous, hardware-independent PoolOS execution engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from .clock import Clock, SystemClock
from .commands import Command


class ExecutionStatus(str, Enum):
    """Lifecycle state recorded for a submitted command."""

    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Immutable audit record for one command lifecycle transition."""

    command: Command
    status: ExecutionStatus
    recorded_at: datetime
    detail: Optional[str] = None
    result: Any = None


class CommandExecutor(Protocol):
    """Adapter boundary used to carry out one normalized command."""

    def execute(self, command: Command) -> Any:
        ...


CommandValidator = Callable[[Command], None]


@dataclass(slots=True)
class ExecutionEngine:
    """Validate, prioritize, deduplicate, dispatch, and audit commands.

    The engine is deliberately synchronous. Home Assistant or another host can
    decide when to call :meth:`run_next` or :meth:`drain` and may place adapter
    I/O behind its own asynchronous boundary.
    """

    clock: Clock = field(default_factory=SystemClock)
    _executors: dict[str, CommandExecutor] = field(default_factory=dict)
    _validators: list[CommandValidator] = field(default_factory=list)
    _queue: list[tuple[int, int, Command]] = field(default_factory=list)
    _audit: list[ExecutionRecord] = field(default_factory=list)
    _submitted_ids: set[str] = field(default_factory=set)
    _sequence: int = 0

    def register_executor(
        self,
        target: str,
        executor: CommandExecutor,
        *,
        replace: bool = False,
    ) -> None:
        """Register the executor for one logical target.

        Accidental replacement is rejected because silently changing the
        adapter responsible for a target can route commands to the wrong
        hardware. Callers must opt in with ``replace=True``.
        """

        if not isinstance(target, str) or not target.strip():
            raise ValueError("executor target must not be empty")
        if target in self._executors and not replace:
            raise ValueError(f"executor already registered for target: {target}")
        self._executors[target] = executor

    def add_validator(self, validator: CommandValidator) -> None:
        """Append a validator that runs before commands enter the queue."""

        if not callable(validator):
            raise TypeError("validator must be callable")
        self._validators.append(validator)

    def submit(self, command: Command) -> ExecutionRecord:
        """Validate and queue a command.

        A newer pending command with the same target and action supersedes the
        older one. Different actions for the same target remain independently
        queued because they may represent distinct intent.
        """

        if command.command_id in self._submitted_ids:
            return self._record(
                command,
                ExecutionStatus.REJECTED,
                detail=f"duplicate command_id: {command.command_id}",
            )

        self._submitted_ids.add(command.command_id)
        try:
            for validator in tuple(self._validators):
                validator(command)
        except Exception as exc:
            return self._record(
                command,
                ExecutionStatus.REJECTED,
                detail=str(exc) or exc.__class__.__name__,
            )

        self._supersede_pending(command)
        self._sequence += 1
        self._queue.append((-int(command.priority), self._sequence, command))
        self._queue.sort(key=lambda item: (item[0], item[1]))
        return self._record(command, ExecutionStatus.QUEUED)

    def run_next(self) -> Optional[ExecutionRecord]:
        """Execute the highest-priority pending command, if one exists."""

        if not self._queue:
            return None

        _, _, command = self._queue.pop(0)
        executor = self._executors.get(command.target)
        if executor is None:
            return self._record(
                command,
                ExecutionStatus.REJECTED,
                detail=f"no executor registered for target: {command.target}",
            )

        try:
            result = executor.execute(command)
        except Exception as exc:
            return self._record(
                command,
                ExecutionStatus.FAILED,
                detail=str(exc) or exc.__class__.__name__,
            )

        return self._record(command, ExecutionStatus.SUCCEEDED, result=result)

    def drain(self, *, limit: Optional[int] = None) -> tuple[ExecutionRecord, ...]:
        """Execute pending commands until empty or ``limit`` is reached."""

        if limit is not None and limit < 0:
            raise ValueError("limit must be zero or greater")

        completed: list[ExecutionRecord] = []
        while self._queue and (limit is None or len(completed) < limit):
            record = self.run_next()
            if record is not None:
                completed.append(record)
        return tuple(completed)

    def pending(self) -> tuple[Command, ...]:
        """Return pending commands in execution order."""

        return tuple(item[2] for item in self._queue)

    def audit_log(self) -> tuple[ExecutionRecord, ...]:
        """Return a stable snapshot of all lifecycle records."""

        return tuple(self._audit)

    def _supersede_pending(self, incoming: Command) -> None:
        retained: list[tuple[int, int, Command]] = []
        for item in self._queue:
            existing = item[2]
            if existing.deduplication_key == incoming.deduplication_key:
                self._record(
                    existing,
                    ExecutionStatus.SUPERSEDED,
                    detail=f"superseded by command {incoming.command_id}",
                )
            else:
                retained.append(item)
        self._queue = retained

    def _record(
        self,
        command: Command,
        status: ExecutionStatus,
        *,
        detail: Optional[str] = None,
        result: Any = None,
    ) -> ExecutionRecord:
        recorded_at = self.clock.now()
        if recorded_at.tzinfo is None:
            raise ValueError("execution clock must return a timezone-aware datetime")
        record = ExecutionRecord(
            command=command,
            status=status,
            recorded_at=recorded_at,
            detail=detail,
            result=result,
        )
        self._audit.append(record)
        return record
