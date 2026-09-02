"""Fail-closed authority and native-consequence correlation for physical writes.

This boundary is vendor-neutral.  It owns no transport and cannot deliver a
command.  Delivery adapters use it twice: once before queueing and again at the
physical dispatch edge.  Native observation code consumes the bounded
expectations without changing authoritative equipment truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


class PhysicalRequestSource(StrEnum):
    """Origin category for one PoolOS physical mutation request."""

    MANUAL = "manual"
    AUTONOMOUS = "autonomous"
    RECONCILIATION = "reconciliation"
    SAFETY_INTERLOCK = "safety_interlock"


class PhysicalAuthorityReason(StrEnum):
    """Stable reason for a physical authority decision."""

    ALLOWED = "allowed"
    AUTHORITY_UNRESOLVED = "authority_unresolved"
    MAINTENANCE_MODE = "maintenance_mode"
    CONTROLLER_MODE_UNRESOLVED = "controller_mode_unresolved"
    CONTROLLER_SERVICE_MODE = "controller_service_mode"
    CONTROLLER_TIMEOUT_MODE = "controller_timeout_mode"


@dataclass(frozen=True, slots=True)
class PhysicalCommandRequest:
    """Immutable identity of one proposed physical mutation."""

    operation: str
    target: str
    source: PhysicalRequestSource
    requested_value: bool | int | float | str
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.target.strip():
            raise ValueError("physical command operation and target are required")
        if not self.request_id.strip():
            raise ValueError("physical command request_id is required")


@dataclass(frozen=True, slots=True)
class ExpectedNativeConsequence:
    """One authoritative native value expected after a PoolOS command."""

    concept: str
    native_object_id: str
    expected_value: bool | int | float | str
    numeric_tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not self.concept.strip() or not self.native_object_id.strip():
            raise ValueError("native consequence concept and object are required")
        if not math.isfinite(self.numeric_tolerance) or self.numeric_tolerance < 0:
            raise ValueError("native consequence tolerance must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PhysicalAuthorityDecision:
    """One deterministic current authority result."""

    allowed: bool
    reason: PhysicalAuthorityReason
    request: PhysicalCommandRequest
    maintenance_mode: bool | None
    controller_mode: str | None


@dataclass(frozen=True, slots=True)
class NativeConsequenceAttribution:
    """Evidence that an authoritative transition matched a PoolOS expectation."""

    expectation_id: str
    request_id: str
    request_source: PhysicalRequestSource
    operation: str
    target: str


@dataclass(slots=True)
class _PendingExpectation:
    expectation_id: str
    request: PhysicalCommandRequest
    consequence: ExpectedNativeConsequence
    reserved_at: datetime
    expires_at: datetime
    dispatch_started: bool = False


class PhysicalCommandDeniedError(RuntimeError):
    """Raised when current central authority denies physical delivery."""

    def __init__(self, decision: PhysicalAuthorityDecision) -> None:
        self.decision = decision
        super().__init__(f"physical command denied:{decision.reason.value}")


@dataclass(slots=True)
class PoolOSPhysicalCommandAuthority:
    """Central, fail-closed authority and bounded correlation registry."""

    expectation_ttl: timedelta = timedelta(seconds=45)
    expectation_limit: int = 64
    _maintenance_mode: bool | None = field(default=None, init=False, repr=False)
    _controller_mode: str | None = field(default=None, init=False, repr=False)
    _expectations: dict[str, _PendingExpectation] = field(
        default_factory=dict, init=False, repr=False
    )
    _native_truth: dict[tuple[str, str], Any] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.expectation_ttl <= timedelta(0):
            raise ValueError("expectation_ttl must be positive")
        if self.expectation_limit <= 0:
            raise ValueError("expectation_limit must be positive")

    @property
    def maintenance_resolved(self) -> bool:
        return self._maintenance_mode is not None

    @property
    def maintenance_mode(self) -> bool | None:
        return self._maintenance_mode

    @property
    def controller_mode(self) -> str | None:
        return self._controller_mode

    def resolve_maintenance(self, enabled: bool) -> None:
        """Resolve persisted state or change the global physical kill switch."""

        changed = self._maintenance_mode is None or self._maintenance_mode != bool(enabled)
        self._maintenance_mode = bool(enabled)
        if changed:
            self.invalidate_expectations()

    def set_controller_mode(self, mode: str | None) -> None:
        """Accept only canonical native controller mode evidence."""

        normalized = None if mode is None else str(mode).strip().casefold()
        accepted = (
            normalized if normalized in {"auto", "service", "timeout"} else None
        )
        changed = accepted != self._controller_mode
        self._controller_mode = accepted
        if changed:
            self.invalidate_expectations()

    def assess(self, request: PhysicalCommandRequest) -> PhysicalAuthorityDecision:
        """Answer whether this request may physically dispatch right now."""

        if self._maintenance_mode is None:
            reason = PhysicalAuthorityReason.AUTHORITY_UNRESOLVED
        elif self._maintenance_mode:
            reason = PhysicalAuthorityReason.MAINTENANCE_MODE
        elif self._controller_mode is None:
            reason = PhysicalAuthorityReason.CONTROLLER_MODE_UNRESOLVED
        elif self._controller_mode == "service":
            reason = PhysicalAuthorityReason.CONTROLLER_SERVICE_MODE
        elif self._controller_mode == "timeout":
            reason = PhysicalAuthorityReason.CONTROLLER_TIMEOUT_MODE
        else:
            reason = PhysicalAuthorityReason.ALLOWED
        return PhysicalAuthorityDecision(
            allowed=reason is PhysicalAuthorityReason.ALLOWED,
            reason=reason,
            request=request,
            maintenance_mode=self._maintenance_mode,
            controller_mode=self._controller_mode,
        )

    def require_allowed(self, request: PhysicalCommandRequest) -> None:
        decision = self.assess(request)
        if not decision.allowed:
            raise PhysicalCommandDeniedError(decision)

    def reserve(
        self,
        request: PhysicalCommandRequest,
        consequence: ExpectedNativeConsequence,
        *,
        now: datetime,
    ) -> str | None:
        """Reserve a transition correlation unless native truth is already equal."""

        _require_aware(now)
        self.require_allowed(request)
        self.expire(now=now)
        current = self._native_truth.get(
            (consequence.concept, consequence.native_object_id)
        )
        if current is not None and _matches(consequence, current):
            return None
        if len(self._expectations) >= self.expectation_limit:
            raise RuntimeError("native consequence expectation capacity exhausted")
        expectation_id = str(uuid4())
        self._expectations[expectation_id] = _PendingExpectation(
            expectation_id=expectation_id,
            request=request,
            consequence=consequence,
            reserved_at=now,
            expires_at=now + self.expectation_ttl,
        )
        return expectation_id

    def mark_dispatch_started(self, expectation_id: str) -> None:
        self._expectations[expectation_id].dispatch_started = True

    def cancel(self, expectation_id: str) -> bool:
        return self._expectations.pop(expectation_id, None) is not None

    def invalidate_expectations(self) -> None:
        self._expectations.clear()

    def replace_native_truth(
        self,
        values: Mapping[tuple[str, str], Any],
    ) -> None:
        """Replace the bounded authoritative truth used only for no-op detection."""

        self._native_truth = {
            (str(concept), str(native_object_id)): value
            for (concept, native_object_id), value in values.items()
            if concept and native_object_id
        }

    def expire(self, *, now: datetime) -> int:
        _require_aware(now)
        expired = [
            key for key, item in self._expectations.items() if item.expires_at <= now
        ]
        for key in expired:
            self._expectations.pop(key, None)
        return len(expired)

    def correlate(
        self,
        *,
        concept: str,
        native_object_id: str | None,
        value: Any,
        observed_at: datetime,
    ) -> NativeConsequenceAttribution | None:
        """Consume the oldest dispatched expectation matching native truth."""

        _require_aware(observed_at)
        self.expire(now=observed_at)
        candidates = sorted(
            self._expectations.values(), key=lambda item: (item.reserved_at, item.expectation_id)
        )
        for item in candidates:
            expected = item.consequence
            if not item.dispatch_started:
                continue
            if expected.concept != concept:
                continue
            if expected.native_object_id != native_object_id:
                continue
            if observed_at < item.reserved_at or not _matches(expected, value):
                continue
            self._expectations.pop(item.expectation_id, None)
            return NativeConsequenceAttribution(
                expectation_id=item.expectation_id,
                request_id=item.request.request_id,
                request_source=item.request.source,
                operation=item.request.operation,
                target=item.request.target,
            )
        return None

    def diagnostics(self, *, now: datetime) -> Mapping[str, Any]:
        self.expire(now=now)
        return MappingProxyType(
            {
                "maintenance_resolved": self.maintenance_resolved,
                "maintenance_mode": self._maintenance_mode,
                "controller_mode": self._controller_mode,
                "physical_commands_allowed": (
                    self._maintenance_mode is False and self._controller_mode == "auto"
                ),
                "pending_expectation_count": len(self._expectations),
                "pending_expectation_limit": self.expectation_limit,
                "expectation_ttl_seconds": self.expectation_ttl.total_seconds(),
            }
        )


def _matches(expected: ExpectedNativeConsequence, value: Any) -> bool:
    if expected.numeric_tolerance:
        if isinstance(value, bool) or isinstance(expected.expected_value, bool):
            return False
        try:
            return abs(float(value) - float(expected.expected_value)) <= expected.numeric_tolerance
        except (TypeError, ValueError):
            return False
    return value == expected.expected_value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "ExpectedNativeConsequence",
    "NativeConsequenceAttribution",
    "PhysicalAuthorityDecision",
    "PhysicalAuthorityReason",
    "PhysicalCommandDeniedError",
    "PhysicalCommandRequest",
    "PhysicalRequestSource",
    "PoolOSPhysicalCommandAuthority",
]
