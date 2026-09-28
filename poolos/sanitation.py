"""Deterministic Pool/Hot Tub sanitation-session lifecycle.

Sanitation is a first-class bounded maintenance purpose.  It owns no transport
and grants no physical authority by itself.  Home Assistant runtime code
persists the session, binds exact authority, and delivers one action at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256


class SanitationBody(StrEnum):
    POOL = "pool"
    HOT_TUB = "hot_tub"


class SanitationLifecycle(StrEnum):
    INACTIVE = "inactive"
    STARTING = "starting"
    ACTIVE = "active"
    PAUSED_OUTAGE = "paused_outage"
    PAUSED_PUMP_OVERRIDE = "paused_pump_override"
    CANCELLING = "cancelling"
    COMPLETING = "completing"
    FAILED = "failed"


class SanitationActionKind(StrEnum):
    HEAT_OFF = "heat_off"
    BODY_ON = "body_on"
    PUMP_SET = "pump_set"
    BODY_OFF = "body_off"


@dataclass(frozen=True, slots=True)
class SanitationAction:
    kind: SanitationActionKind
    body: SanitationBody
    requested_value: bool | int | str
    reason_code: str


@dataclass(frozen=True, slots=True)
class SanitationSession:
    session_id: str
    body: SanitationBody
    requested_at: datetime
    target_rpm: int
    configured_duration_seconds: int
    remaining_seconds: float
    lifecycle: SanitationLifecycle = SanitationLifecycle.STARTING
    last_qualified_at: datetime | None = None
    pump_override_external: bool = False
    cancel_reason: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("sanitation session_id must not be empty")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("sanitation requested_at must be timezone-aware")
        if self.target_rpm <= 0:
            raise ValueError("sanitation target_rpm must be positive")
        if self.configured_duration_seconds <= 0:
            raise ValueError("sanitation duration must be positive")
        if not 0 <= self.remaining_seconds <= self.configured_duration_seconds:
            raise ValueError("sanitation remaining_seconds is out of range")
        if self.last_qualified_at is not None and (
            self.last_qualified_at.tzinfo is None
            or self.last_qualified_at.utcoffset() is None
        ):
            raise ValueError("sanitation last_qualified_at must be timezone-aware")

    @classmethod
    def create(
        cls,
        *,
        body: SanitationBody,
        requested_at: datetime,
        target_rpm: int,
        duration_seconds: int,
    ) -> "SanitationSession":
        payload = (
            f"{body.value}|{requested_at.isoformat()}|{target_rpm}|{duration_seconds}"
        )
        digest = sha256(payload.encode("utf-8")).hexdigest()[:20]
        return cls(
            session_id=f"sanitation-{digest}",
            body=body,
            requested_at=requested_at,
            target_rpm=target_rpm,
            configured_duration_seconds=duration_seconds,
            remaining_seconds=float(duration_seconds),
        )

    @property
    def active(self) -> bool:
        return self.lifecycle not in {
            SanitationLifecycle.INACTIVE,
            SanitationLifecycle.FAILED,
        }

    def persistent_dict(self) -> dict[str, object]:
        """Serialize only durable intent/countdown state, never physical ownership."""

        return {
            "session_id": self.session_id,
            "body": self.body.value,
            "requested_at": self.requested_at.isoformat(),
            "target_rpm": self.target_rpm,
            "configured_duration_seconds": self.configured_duration_seconds,
            "remaining_seconds": self.remaining_seconds,
            "lifecycle": self.lifecycle.value,
            "pump_override_external": self.pump_override_external,
            "cancel_reason": self.cancel_reason,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_persistent_dict(cls, payload: dict[str, object]) -> "SanitationSession":
        lifecycle = SanitationLifecycle(str(payload.get("lifecycle", "starting")))
        # Restored sessions never regain prior live ownership or verified-time
        # continuity.  They resume from fresh evidence with the saved remaining
        # duration.
        if lifecycle in {
            SanitationLifecycle.ACTIVE,
            SanitationLifecycle.PAUSED_OUTAGE,
            SanitationLifecycle.PAUSED_PUMP_OVERRIDE,
        }:
            lifecycle = (
                SanitationLifecycle.PAUSED_PUMP_OVERRIDE
                if bool(payload.get("pump_override_external", False))
                else SanitationLifecycle.STARTING
            )
        return cls(
            session_id=str(payload["session_id"]),
            body=SanitationBody(str(payload["body"])),
            requested_at=datetime.fromisoformat(str(payload["requested_at"])),
            target_rpm=_stored_int(payload["target_rpm"], "target_rpm"),
            configured_duration_seconds=_stored_int(
                payload["configured_duration_seconds"],
                "configured_duration_seconds",
            ),
            remaining_seconds=_stored_float(
                payload["remaining_seconds"],
                "remaining_seconds",
            ),
            lifecycle=lifecycle,
            last_qualified_at=None,
            pump_override_external=bool(payload.get("pump_override_external", False)),
            cancel_reason=(
                None
                if payload.get("cancel_reason") is None
                else str(payload["cancel_reason"])
            ),
            failure_reason=(
                None
                if payload.get("failure_reason") is None
                else str(payload["failure_reason"])
            ),
        )


@dataclass(frozen=True, slots=True)
class SanitationObservation:
    observed_at: datetime
    grid_on: bool | None
    target_body_active: bool | None
    other_body_active: bool | None
    heat_source_id: str | None
    pump_rpm: float | None
    pump_evidence_usable: bool = True
    body_evidence_usable: bool = True
    thermal_evidence_usable: bool = True
    positive_manual_body_off: bool = False
    positive_manual_pump_change_rpm: int | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("sanitation observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SanitationAssessment:
    session: SanitationSession | None
    action: SanitationAction | None
    reason_code: str
    body_owner: str
    pump_owner: str
    thermal_owner: str

    @property
    def active(self) -> bool:
        return self.session is not None and self.session.active


@dataclass(slots=True)
class SanitationController:
    """Advance one mutually-exclusive sanitation session from fresh evidence."""

    pump_tolerance_rpm: int = 25
    session: SanitationSession | None = None

    def start(
        self,
        *,
        body: SanitationBody,
        requested_at: datetime,
        target_rpm: int,
        duration_seconds: int,
    ) -> SanitationAssessment:
        if self.session is not None and self.session.active:
            raise ValueError("another sanitation session is already active")
        self.session = SanitationSession.create(
            body=body,
            requested_at=requested_at,
            target_rpm=target_rpm,
            duration_seconds=duration_seconds,
        )
        return self._assessment("sanitation_requested")

    def restore(self, payload: dict[str, object]) -> SanitationAssessment:
        restored = SanitationSession.from_persistent_dict(payload)
        if restored.lifecycle in {
            SanitationLifecycle.INACTIVE,
            SanitationLifecycle.FAILED,
        }:
            self.session = None
            return self._assessment("sanitation_restore_inactive")
        self.session = restored
        return self._assessment("sanitation_restored_waiting_for_fresh_evidence")

    def abandon(self, *, reason: str) -> SanitationAssessment:
        """Retire durable sanitation intent for an explicit higher authority."""

        self.session = None
        return SanitationAssessment(
            None,
            None,
            reason,
            "none",
            "none",
            "none",
        )

    def request_cancel(self, *, reason: str) -> SanitationAssessment:
        session = self.session
        if session is None or not session.active:
            self.session = None
            return self._assessment("sanitation_already_inactive")
        self.session = replace(
            session,
            lifecycle=SanitationLifecycle.CANCELLING,
            last_qualified_at=None,
            cancel_reason=reason,
        )
        return self._assessment("sanitation_cancel_requested")

    def fail(self, *, reason: str) -> SanitationAssessment:
        session = self.session
        if session is None:
            return self._assessment(reason)
        self.session = replace(
            session,
            lifecycle=SanitationLifecycle.FAILED,
            last_qualified_at=None,
            failure_reason=reason,
        )
        return self._assessment(reason)

    def observe(self, observation: SanitationObservation) -> SanitationAssessment:
        session = self.session
        if session is None:
            return self._assessment("sanitation_inactive")

        if observation.positive_manual_body_off:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.CANCELLING,
                last_qualified_at=None,
                cancel_reason="manual_body_off",
            )
            session = self.session

        if session.lifecycle is SanitationLifecycle.CANCELLING:
            if observation.target_body_active is False:
                self.session = None
                return self._assessment("sanitation_cancelled")
            return self._action(
                SanitationActionKind.BODY_OFF,
                False,
                "sanitation_cancel_body_off",
            )

        if session.lifecycle is SanitationLifecycle.COMPLETING:
            if observation.target_body_active is False:
                self.session = None
                return self._assessment("sanitation_completed")
            return self._action(
                SanitationActionKind.BODY_OFF,
                False,
                "sanitation_duration_complete_body_off",
            )

        if observation.grid_on is None:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._assessment("sanitation_waiting_for_grid_evidence")
        if observation.grid_on is False:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.PAUSED_OUTAGE,
                last_qualified_at=None,
            )
            return self._assessment("sanitation_paused_grid_outage")

        session = self.session
        assert session is not None

        manual_pump = observation.positive_manual_pump_change_rpm
        if manual_pump is not None:
            if abs(manual_pump - session.target_rpm) <= self.pump_tolerance_rpm:
                session = replace(
                    session,
                    pump_override_external=False,
                    lifecycle=SanitationLifecycle.STARTING,
                    last_qualified_at=None,
                )
            else:
                session = replace(
                    session,
                    pump_override_external=True,
                    lifecycle=SanitationLifecycle.PAUSED_PUMP_OVERRIDE,
                    last_qualified_at=None,
                )
            self.session = session

        if session.pump_override_external:
            return self._assessment("sanitation_paused_manual_pump_override")

        if not (
            observation.body_evidence_usable
            and observation.thermal_evidence_usable
            and observation.pump_evidence_usable
        ):
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._assessment("sanitation_waiting_for_fresh_evidence")

        if observation.heat_source_id != "00000":
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._action(
                SanitationActionKind.HEAT_OFF,
                "00000",
                "sanitation_force_heat_off",
            )

        if observation.target_body_active is not True:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._action(
                SanitationActionKind.BODY_ON,
                True,
                "sanitation_activate_body",
            )

        if observation.other_body_active is True:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._assessment("sanitation_waiting_for_exclusive_hydraulics")

        pump_matches = (
            observation.pump_rpm is not None
            and abs(observation.pump_rpm - session.target_rpm)
            <= self.pump_tolerance_rpm
        )
        if not pump_matches:
            self.session = replace(
                session,
                lifecycle=SanitationLifecycle.STARTING,
                last_qualified_at=None,
            )
            return self._action(
                SanitationActionKind.PUMP_SET,
                session.target_rpm,
                "sanitation_set_pump_rpm",
            )

        remaining = session.remaining_seconds
        if session.last_qualified_at is not None:
            elapsed = max(
                0.0,
                (observation.observed_at - session.last_qualified_at).total_seconds(),
            )
            remaining = max(0.0, remaining - elapsed)

        if remaining <= 0:
            self.session = replace(
                session,
                remaining_seconds=0.0,
                lifecycle=SanitationLifecycle.COMPLETING,
                last_qualified_at=None,
            )
            return self._action(
                SanitationActionKind.BODY_OFF,
                False,
                "sanitation_duration_complete_body_off",
            )

        self.session = replace(
            session,
            remaining_seconds=remaining,
            lifecycle=SanitationLifecycle.ACTIVE,
            last_qualified_at=observation.observed_at,
        )
        return self._assessment("sanitation_active_verified")

    def observe_completion(self, *, body_active: bool | None) -> SanitationAssessment:
        session = self.session
        if session is None:
            return self._assessment("sanitation_inactive")
        if session.lifecycle is not SanitationLifecycle.COMPLETING:
            return self._assessment("sanitation_not_completing")
        if body_active is False:
            self.session = None
            return self._assessment("sanitation_completed")
        return self._action(
            SanitationActionKind.BODY_OFF,
            False,
            "sanitation_duration_complete_body_off",
        )

    def _action(
        self,
        kind: SanitationActionKind,
        requested_value: bool | int | str,
        reason_code: str,
    ) -> SanitationAssessment:
        assert self.session is not None
        return SanitationAssessment(
            self.session,
            SanitationAction(kind, self.session.body, requested_value, reason_code),
            reason_code,
            "poolos_sanitation",
            (
                "external"
                if self.session.pump_override_external
                else "poolos_sanitation"
            ),
            "poolos_sanitation",
        )

    def _assessment(self, reason_code: str) -> SanitationAssessment:
        session = self.session
        if session is None:
            return SanitationAssessment(
                None, None, reason_code, "none", "none", "none"
            )
        return SanitationAssessment(
            session,
            None,
            reason_code,
            "poolos_sanitation",
            (
                "external"
                if session.pump_override_external
                else "poolos_sanitation"
            ),
            "poolos_sanitation",
        )


def _stored_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be numeric")
    return int(value)


def _stored_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be numeric")
    return float(value)
