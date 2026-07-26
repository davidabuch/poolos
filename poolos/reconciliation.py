"""Desired-versus-actual state reconciliation for PoolOS.

The reconciliation engine never talks to hardware and never executes commands.
It records successful intent, waits for an equipment-specific verification
window, compares normalized actual state, and returns structured outcomes plus
optional retry commands for the Runtime to process through authority,
constraints, and execution again.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4

from .clock import Clock, SystemClock
from .commands import Command
from .events import EventBus, PoolEvent
from .execution import ExecutionRecord, ExecutionStatus
from .kernel import PoolKernel


class DriftCategory(str, Enum):
    """High-level explanation for a desired/actual mismatch."""

    EXPECTED = "expected"
    MANUAL = "manual"
    CONSTRAINT = "constraint"
    HARDWARE = "hardware"
    COMMUNICATIONS = "communications"
    UNKNOWN = "unknown"


class ReconciliationDisposition(str, Enum):
    """Outcome of one verification attempt."""

    PENDING = "pending"
    STABLE = "stable"
    RETRY = "retry"
    EXHAUSTED = "exhausted"
    UNOBSERVABLE = "unobservable"


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    """Timing and retry policy for one logical target."""

    verification_delay: timedelta = timedelta(0)
    retry_delay: timedelta = timedelta(seconds=10)
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.verification_delay < timedelta(0):
            raise ValueError("verification_delay must not be negative")
        if self.retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """Normalized comparison returned by a target verifier."""

    matched: bool
    actual: Any = None
    detail: Optional[str] = None
    category: DriftCategory = DriftCategory.UNKNOWN


Verifier = Callable[[PoolKernel, Command], VerificationObservation]


@dataclass(frozen=True, slots=True)
class ReconciliationExpectation:
    """Tracked desired state waiting for verification."""

    expectation_id: str
    command: Command
    created_at: datetime
    verify_at: datetime
    attempts: int = 0
    last_checked_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    """Immutable audit record for one reconciliation transition."""

    expectation_id: str
    command: Command
    disposition: ReconciliationDisposition
    recorded_at: datetime
    attempts: int
    actual: Any = None
    detail: Optional[str] = None
    category: DriftCategory = DriftCategory.UNKNOWN
    retry_command: Optional[Command] = None


@dataclass(frozen=True, slots=True)
class ReconciliationEvaluation:
    """Result of one reconciliation pass."""

    records: tuple[ReconciliationRecord, ...]
    retry_commands: tuple[Command, ...]


@dataclass(frozen=True, slots=True)
class _VerifierRegistration:
    target: str
    verifier: Verifier
    policy: VerificationPolicy
    namespace: bool


@dataclass(slots=True)
class ReconciliationEngine:
    """Track desired state and compare it with normalized actual state."""

    clock: Clock = field(default_factory=SystemClock)
    events: Optional[EventBus] = None
    _registrations: list[_VerifierRegistration] = field(default_factory=list)
    _expectations: dict[str, ReconciliationExpectation] = field(default_factory=dict)
    _audit: list[ReconciliationRecord] = field(default_factory=list)

    def register_verifier(
        self,
        target: str,
        verifier: Verifier,
        *,
        policy: VerificationPolicy = VerificationPolicy(),
        namespace: bool = False,
        replace_existing: bool = False,
    ) -> None:
        """Register an exact-target or namespace verifier."""

        if not target.strip():
            raise ValueError("verifier target must not be empty")
        if not callable(verifier):
            raise TypeError("verifier must be callable")

        existing = [
            item
            for item in self._registrations
            if item.target == target and item.namespace is namespace
        ]
        if existing and not replace_existing:
            raise ValueError(f"verifier already registered for target: {target}")
        if existing:
            self._registrations = [
                item
                for item in self._registrations
                if not (item.target == target and item.namespace is namespace)
            ]

        self._registrations.append(
            _VerifierRegistration(target, verifier, policy, namespace)
        )
        self._registrations.sort(
            key=lambda item: (not item.namespace, len(item.target)), reverse=True
        )

    def requires_verification(self, command: Command) -> bool:
        """Return whether a verifier exists for ``command``."""

        return self._registration_for(command.target) is not None

    def track(self, record: ExecutionRecord) -> Optional[ReconciliationExpectation]:
        """Track a successfully executed command when a verifier exists."""

        if record.status is not ExecutionStatus.SUCCEEDED:
            return None
        if "reconciliation_expectation_id" in record.command.metadata:
            return None
        registration = self._registration_for(record.command.target)
        if registration is None:
            return None

        now = self._now()
        expectation = ReconciliationExpectation(
            expectation_id=str(uuid4()),
            command=record.command,
            created_at=now,
            verify_at=now + registration.policy.verification_delay,
        )
        self._expectations[expectation.expectation_id] = expectation
        self._publish(
            "reconciliation.expectation.created",
            expectation,
            {"verify_at": expectation.verify_at.isoformat()},
        )
        return expectation

    def evaluate(self, kernel: PoolKernel) -> ReconciliationEvaluation:
        """Verify all due expectations and return retry requests."""

        now = self._now()
        records: list[ReconciliationRecord] = []
        retries: list[Command] = []

        for expectation_id, expectation in tuple(self._expectations.items()):
            if now < expectation.verify_at:
                continue
            if expectation.next_retry_at is not None and now < expectation.next_retry_at:
                continue

            registration = self._registration_for(expectation.command.target)
            if registration is None:
                record = self._record(
                    expectation,
                    ReconciliationDisposition.UNOBSERVABLE,
                    detail="no verifier registered for target",
                )
                records.append(record)
                self._expectations.pop(expectation_id, None)
                continue

            try:
                observation = registration.verifier(kernel, expectation.command)
            except Exception as exc:
                observation = VerificationObservation(
                    matched=False,
                    detail=str(exc) or exc.__class__.__name__,
                    category=DriftCategory.COMMUNICATIONS,
                )

            attempts = expectation.attempts + 1
            checked = replace(
                expectation,
                attempts=attempts,
                last_checked_at=now,
            )

            if observation.matched:
                record = self._record(
                    checked,
                    ReconciliationDisposition.STABLE,
                    observation=observation,
                )
                records.append(record)
                self._expectations.pop(expectation_id, None)
                continue

            if attempts >= registration.policy.max_attempts:
                record = self._record(
                    checked,
                    ReconciliationDisposition.EXHAUSTED,
                    observation=observation,
                )
                records.append(record)
                self._expectations.pop(expectation_id, None)
                continue

            retry = self._retry_command(checked)
            retries.append(retry)
            next_retry_at = now + registration.policy.retry_delay
            self._expectations[expectation_id] = replace(
                checked,
                verify_at=next_retry_at,
                next_retry_at=next_retry_at,
            )
            record = self._record(
                checked,
                ReconciliationDisposition.RETRY,
                observation=observation,
                retry_command=retry,
            )
            records.append(record)

        return ReconciliationEvaluation(tuple(records), tuple(retries))

    def pending(self) -> tuple[ReconciliationExpectation, ...]:
        """Return a stable snapshot of active expectations."""

        return tuple(self._expectations.values())

    def audit_log(self) -> tuple[ReconciliationRecord, ...]:
        """Return all reconciliation transitions."""

        return tuple(self._audit)

    def _registration_for(self, target: str) -> Optional[_VerifierRegistration]:
        exact = [
            item for item in self._registrations
            if not item.namespace and item.target == target
        ]
        if exact:
            return exact[0]
        namespaces = [
            item for item in self._registrations
            if item.namespace and (target == item.target or target.startswith(f"{item.target}."))
        ]
        if not namespaces:
            return None
        return max(namespaces, key=lambda item: len(item.target))

    def _retry_command(self, expectation: ReconciliationExpectation) -> Command:
        metadata = dict(expectation.command.metadata)
        metadata.update(
            {
                "reconciliation_expectation_id": expectation.expectation_id,
                "retry_of": expectation.command.command_id,
                "retry_attempt": expectation.attempts,
            }
        )
        return replace(
            expectation.command,
            command_id=str(uuid4()),
            issued_at=self._now(),
            metadata=metadata,
        )

    def _record(
        self,
        expectation: ReconciliationExpectation,
        disposition: ReconciliationDisposition,
        *,
        observation: Optional[VerificationObservation] = None,
        detail: Optional[str] = None,
        retry_command: Optional[Command] = None,
    ) -> ReconciliationRecord:
        observation = observation or VerificationObservation(False)
        record = ReconciliationRecord(
            expectation_id=expectation.expectation_id,
            command=expectation.command,
            disposition=disposition,
            recorded_at=self._now(),
            attempts=expectation.attempts,
            actual=observation.actual,
            detail=detail if detail is not None else observation.detail,
            category=observation.category,
            retry_command=retry_command,
        )
        self._audit.append(record)
        self._publish(
            f"reconciliation.{disposition.value}",
            expectation,
            {
                "attempts": record.attempts,
                "detail": record.detail,
                "category": record.category.value,
            },
        )
        return record

    def _publish(
        self,
        topic: str,
        expectation: ReconciliationExpectation,
        payload: dict[str, Any],
    ) -> None:
        if self.events is None:
            return
        self.events.publish(
            PoolEvent(
                topic=topic,
                occurred_at=self._now(),
                source=expectation.command.target,
                payload={
                    "expectation_id": expectation.expectation_id,
                    "command_id": expectation.command.command_id,
                    **payload,
                },
            )
        )

    def _now(self) -> datetime:
        now = self.clock.now()
        if now.tzinfo is None:
            raise ValueError("reconciliation clock must return a timezone-aware datetime")
        return now
