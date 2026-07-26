"""Control-source and scoped authority resolution for PoolOS.

Milestone 9.2 separates *who may express intent* from safety constraints.
Home Assistant and other user interfaces emit ordinary PoolOS commands; they do
not become competing hardware controllers. Local-panel/manual control is
represented by explicit, expiring authority leases. Service mode suspends
normal automation without bypassing future safety constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import Callable, Optional
from uuid import uuid4

from .clock import Clock, SystemClock
from .commands import Command
from .events import EventBus, PoolEvent


class ControlSourceType(str, Enum):
    """Hardware-independent categories of command origin."""

    AUTOMATIC = "automatic"
    USER_INTERFACE = "user_interface"
    LOCAL_PANEL = "local_panel"
    SERVICE = "service"
    INTERNAL = "internal"
    SIMULATION = "simulation"


class AuthorityLevel(IntEnum):
    """Relative authority before safety constraints are applied."""

    AUTOMATIC = 100
    USER_REQUEST = 200
    MANUAL_OVERRIDE = 300
    SERVICE_MODE = 400


@dataclass(frozen=True, slots=True)
class ControlSource:
    """A registered producer of PoolOS commands or observed control intent."""

    source_id: str
    source_type: ControlSourceType
    display_name: Optional[str] = None
    user_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("control source id must not be empty")


@dataclass(frozen=True, slots=True)
class AuthorityLease:
    """Temporary ownership of a logical target or target namespace."""

    source_id: str
    scope: str
    level: AuthorityLevel
    acquired_at: datetime
    expires_at: Optional[datetime] = None
    lease_id: str = field(default_factory=lambda: str(uuid4()))
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.scope.strip():
            raise ValueError("lease source and scope must not be empty")
        if self.acquired_at.tzinfo is None:
            raise ValueError("lease acquired_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("lease expires_at must be timezone-aware")
            if self.expires_at <= self.acquired_at:
                raise ValueError("lease expiration must follow acquisition")

    def is_active(self, at: datetime) -> bool:
        return self.expires_at is None or at < self.expires_at

    def covers(self, target: str) -> bool:
        """Match an exact target or a dot-delimited namespace scope."""

        return target == self.scope or target.startswith(f"{self.scope}.")


class AuthorityDecisionReason(str, Enum):
    ALLOWED = "allowed"
    UNKNOWN_SOURCE = "unknown_source"
    MANUAL_OVERRIDE_ACTIVE = "manual_override_active"
    SERVICE_MODE_ACTIVE = "service_mode_active"
    SOURCE_OWNS_SCOPE = "source_owns_scope"


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    """Immutable explanation of one authority resolution."""

    command: Command
    source_id: str
    allowed: bool
    reason: AuthorityDecisionReason
    decided_at: datetime
    controlling_source_id: Optional[str] = None
    lease_id: Optional[str] = None


@dataclass(slots=True)
class ControlAuthority:
    """Resolve command authority deterministically by source and target scope."""

    clock: Clock = field(default_factory=SystemClock)
    events: EventBus = field(default_factory=EventBus)
    _sources: dict[str, ControlSource] = field(default_factory=dict)
    _leases: dict[str, AuthorityLease] = field(default_factory=dict)
    _service_lease_id: Optional[str] = None
    _audit: list[AuthorityDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.register_source(
            ControlSource("poolos", ControlSourceType.AUTOMATIC, "PoolOS"),
            replace=True,
        )

    def register_source(self, source: ControlSource, *, replace: bool = False) -> None:
        if source.source_id in self._sources and not replace:
            raise ValueError(f"control source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def source(self, source_id: str) -> ControlSource:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown control source: {source_id}") from exc

    def sources(self) -> tuple[ControlSource, ...]:
        return tuple(self._sources.values())

    def acquire_override(
        self,
        *,
        source_id: str,
        scope: str,
        duration: Optional[timedelta] = None,
        reason: Optional[str] = None,
    ) -> AuthorityLease:
        source = self.source(source_id)
        if source.source_type not in {
            ControlSourceType.LOCAL_PANEL,
            ControlSourceType.SERVICE,
        }:
            raise ValueError("manual overrides require a local-panel or service source")
        now = self._now()
        if duration is not None and duration <= timedelta(0):
            raise ValueError("override duration must be positive")
        lease = AuthorityLease(
            source_id=source_id,
            scope=scope,
            level=AuthorityLevel.MANUAL_OVERRIDE,
            acquired_at=now,
            expires_at=None if duration is None else now + duration,
            reason=reason,
        )
        self._leases[lease.lease_id] = lease
        self._publish("authority.override.acquired", source_id, lease)
        return lease

    def release(self, lease_id: str, *, reason: Optional[str] = None) -> bool:
        lease = self._leases.pop(lease_id, None)
        if lease is None:
            return False
        if self._service_lease_id == lease_id:
            self._service_lease_id = None
        self._publish(
            "authority.lease.released",
            lease.source_id,
            {"lease": lease, "reason": reason},
        )
        return True

    def enter_service_mode(self, *, source_id: str, reason: Optional[str] = None) -> AuthorityLease:
        source = self.source(source_id)
        if source.source_type is not ControlSourceType.SERVICE:
            raise ValueError("service mode requires a service control source")
        if self.service_mode_active:
            raise ValueError("service mode is already active")
        now = self._now()
        lease = AuthorityLease(
            source_id=source_id,
            scope="*",
            level=AuthorityLevel.SERVICE_MODE,
            acquired_at=now,
            reason=reason,
        )
        self._leases[lease.lease_id] = lease
        self._service_lease_id = lease.lease_id
        self._publish("authority.service_mode.entered", source_id, lease)
        return lease

    def exit_service_mode(self, *, reason: Optional[str] = None) -> bool:
        if self._service_lease_id is None:
            return False
        lease_id = self._service_lease_id
        lease = self._leases.pop(lease_id)
        self._service_lease_id = None
        self._publish(
            "authority.service_mode.exited",
            lease.source_id,
            {"lease": lease, "reason": reason},
        )
        return True

    @property
    def service_mode_active(self) -> bool:
        return self._service_lease_id in self._leases

    def expire_leases(self) -> tuple[AuthorityLease, ...]:
        now = self._now()
        expired = tuple(
            lease for lease in self._leases.values() if not lease.is_active(now)
        )
        for lease in expired:
            self._leases.pop(lease.lease_id, None)
            if self._service_lease_id == lease.lease_id:
                self._service_lease_id = None
            self._publish("authority.lease.expired", lease.source_id, lease)
        return expired

    def active_leases(self) -> tuple[AuthorityLease, ...]:
        self.expire_leases()
        return tuple(self._leases.values())

    def resolve(self, command: Command) -> AuthorityDecision:
        """Resolve authority only; safety constraints are intentionally later."""

        now = self._now()
        self.expire_leases()
        source_id = self._command_source_id(command)
        source = self._sources.get(source_id)
        if source is None:
            return self._record(command, source_id, False, AuthorityDecisionReason.UNKNOWN_SOURCE, now)

        service = self._service_lease()
        if service is not None:
            allowed = source_id == service.source_id
            return self._record(
                command,
                source_id,
                allowed,
                AuthorityDecisionReason.SOURCE_OWNS_SCOPE if allowed else AuthorityDecisionReason.SERVICE_MODE_ACTIVE,
                now,
                service,
            )

        lease = self._winning_lease(command.target)
        if lease is not None:
            allowed = source_id == lease.source_id
            return self._record(
                command,
                source_id,
                allowed,
                AuthorityDecisionReason.SOURCE_OWNS_SCOPE if allowed else AuthorityDecisionReason.MANUAL_OVERRIDE_ACTIVE,
                now,
                lease,
            )

        return self._record(command, source_id, True, AuthorityDecisionReason.ALLOWED, now)

    def audit_log(self) -> tuple[AuthorityDecision, ...]:
        return tuple(self._audit)

    def _winning_lease(self, target: str) -> Optional[AuthorityLease]:
        matching = [
            lease
            for lease in self._leases.values()
            if lease.level is AuthorityLevel.MANUAL_OVERRIDE and lease.covers(target)
        ]
        if not matching:
            return None
        return max(
            matching,
            key=lambda lease: (lease.level, len(lease.scope), lease.acquired_at, lease.lease_id),
        )

    def _service_lease(self) -> Optional[AuthorityLease]:
        if self._service_lease_id is None:
            return None
        return self._leases.get(self._service_lease_id)

    @staticmethod
    def _command_source_id(command: Command) -> str:
        value = command.metadata.get("control_source_id", command.requested_by)
        return str(value)

    def _record(
        self,
        command: Command,
        source_id: str,
        allowed: bool,
        reason: AuthorityDecisionReason,
        at: datetime,
        lease: Optional[AuthorityLease] = None,
    ) -> AuthorityDecision:
        decision = AuthorityDecision(
            command=command,
            source_id=source_id,
            allowed=allowed,
            reason=reason,
            decided_at=at,
            controlling_source_id=None if lease is None else lease.source_id,
            lease_id=None if lease is None else lease.lease_id,
        )
        self._audit.append(decision)
        if not allowed:
            self.events.publish(
                PoolEvent(
                    topic="authority.command.denied",
                    occurred_at=at,
                    source=source_id,
                    payload=decision,
                )
            )
        return decision

    def _publish(self, topic: str, source: str, payload: object) -> None:
        self.events.publish(
            PoolEvent(topic=topic, occurred_at=self._now(), source=source, payload=payload)
        )

    def _now(self) -> datetime:
        now = self.clock.now()
        if now.tzinfo is None:
            raise ValueError("authority clock must return a timezone-aware datetime")
        return now
