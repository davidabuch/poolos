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

from .operating_baselines import PumpOperatingBaselines


_THERMAL_BASELINES = PumpOperatingBaselines()


class PhysicalRequestSource(StrEnum):
    """Origin category for one PoolOS physical mutation request."""

    MANUAL = "manual"
    AUTONOMOUS = "autonomous"
    AUTOMATIC_THERMAL = "automatic_thermal"
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
    AUTOMATIC_THERMAL_GATE_DISABLED = "automatic_thermal_gate_disabled"
    THERMAL_LIVE_GATE_DISABLED = "thermal_live_gate_disabled"
    AUTOMATIC_THERMAL_SCOPE_DISABLED = "automatic_thermal_scope_disabled"
    AUTOMATIC_THERMAL_SCOPE_MISMATCH = "automatic_thermal_scope_mismatch"
    AUTOMATIC_THERMAL_CONTEXT_MISSING = "automatic_thermal_context_missing"
    AUTOMATIC_THERMAL_CONTEXT_STALE = "automatic_thermal_context_stale"
    AUTOMATIC_THERMAL_DRIVER_UNLOADED = "automatic_thermal_driver_unloaded"
    AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED = (
        "automatic_thermal_operation_unauthorized"
    )


class AutomaticThermalDispatchPurpose(StrEnum):
    """Final-gateway authority class for normal work versus reduction only."""

    NORMAL = "normal"
    TERMINATION = "termination"


@dataclass(frozen=True, slots=True)
class AutomaticThermalDispatchContext:
    """Restrictive one-epoch authority proof for automatic thermal delivery."""

    generation: int
    epoch_identity: str
    session_identity: str
    body: str
    purpose: AutomaticThermalDispatchPurpose = AutomaticThermalDispatchPurpose.NORMAL

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("automatic thermal generation must be positive")
        for name in ("epoch_identity", "session_identity", "body"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.body not in {"pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal body")
        object.__setattr__(
            self,
            "purpose",
            AutomaticThermalDispatchPurpose(self.purpose),
        )


@dataclass(frozen=True, slots=True)
class PhysicalCommandRequest:
    """Immutable identity of one proposed physical mutation."""

    operation: str
    target: str
    source: PhysicalRequestSource
    requested_value: bool | int | float | str
    request_id: str = field(default_factory=lambda: str(uuid4()))
    automatic_thermal_context: AutomaticThermalDispatchContext | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.target.strip():
            raise ValueError("physical command operation and target are required")
        if not self.request_id.strip():
            raise ValueError("physical command request_id is required")
        if (
            self.source is not PhysicalRequestSource.AUTOMATIC_THERMAL
            and self.automatic_thermal_context is not None
        ):
            raise ValueError(
                "automatic thermal context requires automatic thermal source"
            )


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
    _automatic_thermal_driver_enabled: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_thermal_live_enabled: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_thermal_scope: str = field(
        default="disabled", init=False, repr=False
    )
    _automatic_thermal_loaded: bool = field(default=True, init=False, repr=False)
    _automatic_thermal_generation: int = field(default=0, init=False, repr=False)
    _automatic_thermal_epoch_identity: str | None = field(
        default=None, init=False, repr=False
    )
    _automatic_thermal_session_identity: str | None = field(
        default=None, init=False, repr=False
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

    def configure_automatic_thermal(
        self,
        *,
        driver_enabled: bool,
        thermal_live_enabled: bool,
        commissioning_scope: str,
    ) -> None:
        """Set restrictive automatic gates and invalidate queued authority."""

        scope = str(commissioning_scope).strip().casefold()
        if scope not in {"disabled", "pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal commissioning scope")
        changed = (
            self._automatic_thermal_driver_enabled != bool(driver_enabled)
            or self._automatic_thermal_live_enabled != bool(thermal_live_enabled)
            or self._automatic_thermal_scope != scope
        )
        self._automatic_thermal_driver_enabled = bool(driver_enabled)
        self._automatic_thermal_live_enabled = bool(thermal_live_enabled)
        self._automatic_thermal_scope = scope
        if changed:
            self._invalidate_automatic_thermal_context()

    def begin_automatic_thermal_epoch(self, epoch_identity: str) -> None:
        """Invalidate older queued work at each authoritative runtime epoch."""

        if not epoch_identity.strip():
            raise ValueError("automatic thermal epoch identity must not be empty")
        if epoch_identity == self._automatic_thermal_epoch_identity:
            return
        self._automatic_thermal_generation += 1
        self._automatic_thermal_epoch_identity = epoch_identity
        self._automatic_thermal_session_identity = None

    def bind_automatic_thermal_dispatch(
        self,
        *,
        epoch_identity: str,
        session_identity: str,
        body: str,
        purpose: AutomaticThermalDispatchPurpose = AutomaticThermalDispatchPurpose.NORMAL,
    ) -> AutomaticThermalDispatchContext:
        """Bind one current session to the latest authoritative epoch."""

        if epoch_identity != self._automatic_thermal_epoch_identity:
            raise ValueError("automatic thermal epoch is not current")
        if not session_identity.strip():
            raise ValueError("automatic thermal session identity must not be empty")
        if body not in {"pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal body")
        self._automatic_thermal_session_identity = session_identity
        return AutomaticThermalDispatchContext(
            generation=self._automatic_thermal_generation,
            epoch_identity=epoch_identity,
            session_identity=session_identity,
            body=body,
            purpose=purpose,
        )

    def unload_automatic_thermal_driver(self) -> None:
        """Make all late automatic work inert without issuing cleanup."""

        self._automatic_thermal_loaded = False
        self._invalidate_automatic_thermal_context()

    def _invalidate_automatic_thermal_context(self) -> None:
        self._automatic_thermal_generation += 1
        self._automatic_thermal_epoch_identity = None
        self._automatic_thermal_session_identity = None
        self.invalidate_expectations()

    def assess(self, request: PhysicalCommandRequest) -> PhysicalAuthorityDecision:
        """Answer whether this request may physically dispatch right now."""

        reason = self.base_authority_reason
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source is PhysicalRequestSource.AUTOMATIC_THERMAL
        ):
            reason = self._automatic_thermal_reason(request)
        return PhysicalAuthorityDecision(
            allowed=reason is PhysicalAuthorityReason.ALLOWED,
            reason=reason,
            request=request,
            maintenance_mode=self._maintenance_mode,
            controller_mode=self._controller_mode,
        )

    @property
    def base_authority_reason(self) -> PhysicalAuthorityReason:
        """Return current Maintenance/controller authority without a request."""

        if self._maintenance_mode is None:
            return PhysicalAuthorityReason.AUTHORITY_UNRESOLVED
        if self._maintenance_mode:
            return PhysicalAuthorityReason.MAINTENANCE_MODE
        if self._controller_mode is None:
            return PhysicalAuthorityReason.CONTROLLER_MODE_UNRESOLVED
        if self._controller_mode == "service":
            return PhysicalAuthorityReason.CONTROLLER_SERVICE_MODE
        if self._controller_mode == "timeout":
            return PhysicalAuthorityReason.CONTROLLER_TIMEOUT_MODE
        return PhysicalAuthorityReason.ALLOWED

    def _automatic_thermal_reason(
        self,
        request: PhysicalCommandRequest,
    ) -> PhysicalAuthorityReason:
        context = request.automatic_thermal_context
        if not self._automatic_thermal_loaded:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_DRIVER_UNLOADED
        if not self._automatic_thermal_driver_enabled:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_GATE_DISABLED
        if not self._automatic_thermal_live_enabled:
            return PhysicalAuthorityReason.THERMAL_LIVE_GATE_DISABLED
        if self._automatic_thermal_scope == "disabled":
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_SCOPE_DISABLED
        if context is None:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_MISSING
        if not _automatic_thermal_request_matches_context(request, context):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
        if self._automatic_thermal_scope != context.body:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_SCOPE_MISMATCH
        if (
            context.generation != self._automatic_thermal_generation
            or context.epoch_identity != self._automatic_thermal_epoch_identity
            or context.session_identity != self._automatic_thermal_session_identity
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        return PhysicalAuthorityReason.ALLOWED

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
                "automatic_thermal_driver_enabled": (
                    self._automatic_thermal_driver_enabled
                ),
                "automatic_thermal_live_enabled": self._automatic_thermal_live_enabled,
                "automatic_thermal_scope": self._automatic_thermal_scope,
                "automatic_thermal_loaded": self._automatic_thermal_loaded,
                "automatic_thermal_generation": self._automatic_thermal_generation,
            }
        )


def _automatic_thermal_request_matches_context(
    request: PhysicalCommandRequest,
    context: AutomaticThermalDispatchContext,
) -> bool:
    body_target = "B1101" if context.body == "pool" else "B1202"
    if context.purpose is AutomaticThermalDispatchPurpose.TERMINATION:
        return (
            context.body == "pool"
            and request.operation == "body_heat_source"
            and request.target == "B1101"
            and request.requested_value == "00000"
        )
    if request.operation == "body_active":
        return request.target == body_target and request.requested_value is True
    if request.operation == "body_heat_source":
        return (
            request.target == body_target
            and request.requested_value in {"00000", "H0001", "H0002"}
        )
    if request.operation == "pump_circuit_speed":
        return (
            request.target == "p0102"
            and not isinstance(request.requested_value, bool)
            and request.requested_value
            in {
                _THERMAL_BASELINES.solar_heating_rpm,
                _THERMAL_BASELINES.gas_heating_rpm,
                _THERMAL_BASELINES.priming_rpm,
            }
        )
    return False


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
    "AutomaticThermalDispatchPurpose",
    "AutomaticThermalDispatchContext",
    "ExpectedNativeConsequence",
    "NativeConsequenceAttribution",
    "PhysicalAuthorityDecision",
    "PhysicalAuthorityReason",
    "PhysicalCommandDeniedError",
    "PhysicalCommandRequest",
    "PhysicalRequestSource",
    "PoolOSPhysicalCommandAuthority",
]
