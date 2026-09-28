"""Home Assistant runtime for durable PoolOS sanitation sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any, Callable, Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from poolos.external_change import ExternalChangeBatch
from poolos.grid_outage_confirmation import GridOutageDisposition
from poolos.hal import CommandReceipt, CommandStatus
from poolos.intellicenter_readonly import (
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
)
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.sanitation import (
    SanitationAction,
    SanitationActionKind,
    SanitationAssessment,
    SanitationBody,
    SanitationController,
    SanitationLifecycle,
    SanitationObservation,
)
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrationAssessment

from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterControl
from .observation import ObservationSnapshot
from .sanitation_delivery import ManualIntelliCenterSanitationDelivery
from .thermal_runtime import PoolOSThermalRuntime

LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_PERSIST_GRANULARITY_SECONDS = 60.0


@dataclass(slots=True)
class PoolOSSanitationRuntime:
    """Own one mutually-exclusive, restart-durable sanitation session."""

    hass: HomeAssistant
    entry_id: str
    coordinator: PoolOSCoordinator
    thermal_runtime: PoolOSThermalRuntime
    authority: PoolOSPhysicalCommandAuthority
    manual: ManualIntelliCenterControl | None
    default_rpm: int
    pool_duration_seconds: int
    hot_tub_duration_seconds: int
    authority_boundary_changed: Callable[[datetime, bool], None] | None = None
    controller: SanitationController = field(default_factory=SanitationController)
    assessment: SanitationAssessment | None = None
    _task: asyncio.Task[CommandReceipt] | None = field(
        default=None, init=False, repr=False
    )
    _pending: tuple[
        ObservationSnapshot,
        ThermalRuntimeOrchestrationAssessment,
        ExternalChangeBatch,
    ] | None = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)
    _last_persisted_remaining: float | None = field(
        default=None, init=False, repr=False
    )
    _last_persisted_lifecycle: str | None = field(
        default=None, init=False, repr=False
    )
    _last_delivery_error: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.default_rpm <= 0:
            raise ValueError("sanitation RPM must be positive")
        if self.pool_duration_seconds <= 0 or self.hot_tub_duration_seconds <= 0:
            raise ValueError("sanitation durations must be positive")

    @property
    def store(self) -> Store[dict[str, Any]]:
        return Store(
            self.hass,
            _STORAGE_VERSION,
            f"poolos.sanitation.{self.entry_id}",
        )

    @property
    def active(self) -> bool:
        session = self.controller.session
        return session is not None and session.active

    @property
    def active_body(self) -> SanitationBody | None:
        session = self.controller.session
        return None if session is None or not session.active else session.body

    def is_active(self, body: SanitationBody) -> bool:
        return self.active_body is body

    async def async_restore(self) -> None:
        """Restore durable intent/countdown only; live authority starts fresh."""

        payload = await self.store.async_load()
        if not isinstance(payload, Mapping):
            return
        session_payload = payload.get("session")
        if not isinstance(session_payload, Mapping):
            return
        try:
            self.assessment = self.controller.restore(dict(session_payload))
        except (KeyError, TypeError, ValueError):
            LOGGER.exception("PoolOS sanitation restore failed closed")
            await self.store.async_save({})
            return
        session = self.controller.session
        if session is None or not session.active:
            return
        self.authority.begin_sanitation_session(
            body=session.body.value,
            session_id=session.session_id,
            sanitation_rpm=session.target_rpm,
        )
        if self.authority_boundary_changed is not None:
            self.authority_boundary_changed(datetime.now(UTC), True)
        self._last_persisted_remaining = session.remaining_seconds
        self._last_persisted_lifecycle = session.lifecycle.value

    async def async_start(self, body: SanitationBody) -> None:
        """Start one explicit sanitation session and request fresh evidence."""

        if self._unloaded:
            raise RuntimeError("sanitation runtime is unloaded")
        now = datetime.now(UTC)
        duration = (
            self.pool_duration_seconds
            if body is SanitationBody.POOL
            else self.hot_tub_duration_seconds
        )
        self.assessment = self.controller.start(
            body=body,
            requested_at=now,
            target_rpm=self.default_rpm,
            duration_seconds=duration,
        )
        session = self.controller.session
        assert session is not None
        self.authority.begin_sanitation_session(
            body=body.value,
            session_id=session.session_id,
            sanitation_rpm=session.target_rpm,
        )
        if self.authority_boundary_changed is not None:
            self.authority_boundary_changed(now, True)
        self._last_delivery_error = None
        await self._persist(force=True)
        await self.coordinator.async_request_refresh()
        self.coordinator.async_update_listeners()

    def note_manual_body_off(self, body: SanitationBody) -> bool:
        """Convert ordinary manual BODY Off into sanitation cancellation intent."""

        session = self.controller.session
        if session is None or not session.active or session.body is not body:
            return False
        self.assessment = self.controller.request_cancel(
            reason="manual_body_off",
        )
        self.hass.async_create_task(
            self._persist(force=True),
            "Persist manual PoolOS sanitation cancellation",
        )
        self.coordinator.async_update_listeners()
        return True

    async def async_abandon_for_higher_authority(self, *, reason: str) -> None:
        """Retire sanitation intent without issuing commands; caller owns reduction."""

        session = self.controller.session
        if session is None:
            return
        prior_session_id = session.session_id
        self.assessment = self.controller.abandon(reason=reason)
        self.authority.end_sanitation_session(session_id=prior_session_id)
        if self.authority_boundary_changed is not None:
            self.authority_boundary_changed(datetime.now(UTC), False)
        await self._persist(force=True)
        self.coordinator.async_update_listeners()

    async def async_cancel(self, body: SanitationBody, *, reason: str) -> None:
        """Request deterministic sanitation cancellation for the active body."""

        session = self.controller.session
        if session is None or not session.active:
            return
        if session.body is not body:
            raise ValueError("requested sanitation body is not active")
        self.assessment = self.controller.request_cancel(reason=reason)
        await self._persist(force=True)
        await self.coordinator.async_request_refresh()
        self.coordinator.async_update_listeners()

    def observe(
        self,
        snapshot: ObservationSnapshot,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        external_changes: ExternalChangeBatch,
    ) -> None:
        """Advance sanitation from one authoritative frame and schedule one action."""

        if self._unloaded or not self.active:
            return
        if self._task is not None:
            self._pending = (snapshot, orchestration, external_changes)
            return
        self._process_frame(snapshot, orchestration, external_changes)

    def _process_frame(
        self,
        snapshot: ObservationSnapshot,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        external_changes: ExternalChangeBatch,
    ) -> None:
        session_before = self.controller.session
        if session_before is None:
            return

        values = {item.observation_id: item for item in snapshot.observations}
        prefix = "pool" if session_before.body is SanitationBody.POOL else "spa"
        other_prefix = "spa" if prefix == "pool" else "pool"
        pump_concept = (
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
            if session_before.body is SanitationBody.POOL
            else SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
        )

        manual_body_off = any(
            event.concept == f"{prefix}.active"
            and event.new_value is False
            and event.observed_at == snapshot.generated_at
            and event.positive_operator_evidence is not None
            for event in external_changes.events
        )
        manual_pump_change = next(
            (
                int(round(float(event.new_value)))
                for event in external_changes.events
                if event.concept == pump_concept
                and event.observed_at == snapshot.generated_at
                and event.positive_operator_evidence is not None
                and isinstance(event.new_value, (int, float))
                and not isinstance(event.new_value, bool)
            ),
            None,
        )

        outage = orchestration.outage
        grid_on: bool | None
        if outage is None:
            grid_on = None
        elif outage.disposition is GridOutageDisposition.ON_GRID:
            grid_on = True
        elif outage.disposition is GridOutageDisposition.CONFIRMED_OUTAGE:
            grid_on = False
        else:
            grid_on = None

        observation = SanitationObservation(
            observed_at=snapshot.generated_at,
            grid_on=grid_on,
            target_body_active=_bool_value(values.get(f"{prefix}.active")),
            other_body_active=_bool_value(values.get(f"{other_prefix}.active")),
            heat_source_id=_str_value(values.get(f"{prefix}.raw_heater_id")),
            pump_rpm=_number_value(values.get("pump.rpm")),
            body_evidence_usable=(
                _usable(values.get(f"{prefix}.active"), snapshot)
                and _usable(values.get(f"{other_prefix}.active"), snapshot)
            ),
            thermal_evidence_usable=_usable(
                values.get(f"{prefix}.raw_heater_id"), snapshot
            ),
            pump_evidence_usable=_usable(values.get("pump.rpm"), snapshot),
            positive_manual_body_off=manual_body_off,
            positive_manual_pump_change_rpm=manual_pump_change,
        )
        self.assessment = self.controller.observe(observation)

        session_after = self.controller.session
        if session_after is None:
            self.authority.end_sanitation_session(
                session_id=session_before.session_id
            )
            if self.authority_boundary_changed is not None:
                self.authority_boundary_changed(snapshot.generated_at, False)
            self._last_delivery_error = None
            self.hass.async_create_task(
                self._persist(force=True),
                "Persist completed PoolOS sanitation session",
            )
            # Ending sanitation is a legitimate fresh policy boundary.
            self.coordinator.async_update_listeners()
            return

        self.hass.async_create_task(
            self._persist(force=False),
            "Persist PoolOS sanitation progress",
        )

        action = self.assessment.action
        if action is None:
            self.coordinator.async_update_listeners()
            return

        pump_circuit_id = self._pump_circuit_id(session_after.body)
        if pump_circuit_id is None:
            self._last_delivery_error = "sanitation_pump_circuit_unresolved"
            self.coordinator.async_update_listeners()
            return
        operation, target = _action_identity(action, pump_circuit_id)
        try:
            context = self.authority.bind_sanitation_dispatch(
                session_id=session_after.session_id,
                body=session_after.body.value,
                operation=operation,
                target=target,
                requested_value=action.requested_value,
                pump_circuit_id=pump_circuit_id,
                sanitation_rpm=session_after.target_rpm,
            )
        except ValueError as exc:
            self._last_delivery_error = str(exc)
            self.coordinator.async_update_listeners()
            return
        if self.manual is None or not self.manual.available:
            self._last_delivery_error = "sanitation_manual_delivery_unavailable"
            self.coordinator.async_update_listeners()
            return
        delivery = ManualIntelliCenterSanitationDelivery(self.manual, context)
        correlation_id = (
            f"{session_after.session_id}:{action.kind.value}:"
            f"{snapshot.generated_at.isoformat()}"
        )
        self._task = self.hass.async_create_task(
            delivery.deliver(action, correlation_id=correlation_id),
            f"PoolOS {session_after.body.value} sanitation",
        )
        self._task.add_done_callback(self._task_done)

    def _pump_circuit_id(self, body: SanitationBody) -> str | None:
        thermal = self.thermal_runtime.assessment
        if thermal is None:
            return None
        return (
            thermal.pool_pump_circuit_id
            if body is SanitationBody.POOL
            else thermal.spa_pump_circuit_id
        )

    def _task_done(self, task: asyncio.Task[CommandReceipt]) -> None:
        if task is not self._task:
            return
        self._task = None
        try:
            receipt = task.result()
        except asyncio.CancelledError:
            receipt = None
        except Exception as exc:
            LOGGER.exception("PoolOS sanitation delivery failed")
            self._last_delivery_error = f"runtime_exception:{type(exc).__name__}"
            receipt = None
        if receipt is not None:
            if receipt.status is CommandStatus.ACKNOWLEDGED:
                self._last_delivery_error = None
            else:
                reason = receipt.details.get("authority_reason")
                self._last_delivery_error = (
                    str(reason) if reason else receipt.message
                )
        if not self._unloaded:
            self.hass.async_create_task(
                self.coordinator.async_request_refresh(),
                "Refresh PoolOS after sanitation delivery",
            )
            self.coordinator.async_update_listeners()
        pending = self._pending
        self._pending = None
        if not self._unloaded and pending is not None:
            self._process_frame(*pending)

    async def _persist(self, *, force: bool) -> None:
        session = self.controller.session
        if session is None:
            self._last_persisted_remaining = None
            self._last_persisted_lifecycle = None
            await self.store.async_save({})
            return
        if not force:
            same_lifecycle = (
                self._last_persisted_lifecycle == session.lifecycle.value
            )
            remaining_delta = (
                None
                if self._last_persisted_remaining is None
                else abs(
                    self._last_persisted_remaining
                    - session.remaining_seconds
                )
            )
            if (
                same_lifecycle
                and remaining_delta is not None
                and remaining_delta < _PERSIST_GRANULARITY_SECONDS
            ):
                return
        await self.store.async_save({"session": session.persistent_dict()})
        self._last_persisted_remaining = session.remaining_seconds
        self._last_persisted_lifecycle = session.lifecycle.value

    async def async_unload(self) -> None:
        """Persist remaining work and make late sanitation work inert."""

        if self._unloaded:
            return
        self._unloaded = True
        await self._persist(force=True)
        session = self.controller.session
        if session is not None:
            self.authority.end_sanitation_session(session_id=session.session_id)
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._pending = None

    def diagnostics(self) -> dict[str, object]:
        session = self.controller.session
        assessment = self.assessment
        if session is None:
            return {
                "state": SanitationLifecycle.INACTIVE.value,
                "active": False,
                "body": None,
                "remaining_seconds": 0,
                "configured_rpm": self.default_rpm,
                "body_owner": "none",
                "pump_owner": "none",
                "thermal_owner": "none",
                "last_delivery_error": self._last_delivery_error,
                "restart_durable": True,
                "grid_outage_behavior": "pause_and_resume",
            }
        return {
            "state": session.lifecycle.value,
            "active": session.active,
            "body": session.body.value,
            "session_id": session.session_id,
            "remaining_seconds": round(session.remaining_seconds, 1),
            "configured_duration_seconds": session.configured_duration_seconds,
            "configured_rpm": session.target_rpm,
            "pump_override_external": session.pump_override_external,
            "reason_code": (
                None if assessment is None else assessment.reason_code
            ),
            "body_owner": (
                "poolos_sanitation"
                if assessment is None
                else assessment.body_owner
            ),
            "pump_owner": (
                "poolos_sanitation"
                if assessment is None
                else assessment.pump_owner
            ),
            "thermal_owner": (
                "poolos_sanitation"
                if assessment is None
                else assessment.thermal_owner
            ),
            "heat_required": False,
            "last_delivery_error": self._last_delivery_error,
            "restart_durable": True,
            "grid_outage_behavior": "pause_and_resume",
            "mutually_exclusive": True,
        }


def _value(item: Any) -> Any:
    return None if item is None else getattr(item, "value", None)


def _bool_value(item: Any) -> bool | None:
    value = _value(item)
    return value if isinstance(value, bool) else None


def _str_value(item: Any) -> str | None:
    value = _value(item)
    return value if isinstance(value, str) else None


def _number_value(item: Any) -> float | None:
    value = _value(item)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _usable(item: Any, snapshot: ObservationSnapshot) -> bool:
    if item is None:
        return False
    quality = getattr(getattr(item, "quality", None), "value", None)
    source_id = getattr(item, "source_id", None)
    return quality == "good" and source_id not in set(snapshot.stale_entities)


def _action_identity(
    action: SanitationAction,
    pump_circuit_id: str,
) -> tuple[str, str]:
    body_id = "B1101" if action.body is SanitationBody.POOL else "B1202"
    if action.kind is SanitationActionKind.HEAT_OFF:
        return "body_heat_source", body_id
    if action.kind in {
        SanitationActionKind.BODY_ON,
        SanitationActionKind.BODY_OFF,
    }:
        return "body_active", body_id
    if action.kind is SanitationActionKind.PUMP_SET:
        return "pump_circuit_speed", pump_circuit_id
    raise ValueError("unsupported sanitation action")


__all__ = ["PoolOSSanitationRuntime"]
