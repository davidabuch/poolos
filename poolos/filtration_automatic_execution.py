"""Default-off, event-driven autonomous Pool filtration execution.

Accounting remains command-free in :mod:`poolos.filtration_policy`.  This
module consumes its canonical disposition and advances at most one accepted
Pool operation per authoritative observation epoch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Protocol

from .clock import FixedClock
from .external_change import ExternalChangeBatch, POOL_CIRCULATION_TAKEOVER_CONCEPTS
from .filtration_policy import FiltrationAccountingSnapshot, FiltrationDisposition
from .hal import CommandReceipt
from .integration import PoolOperation, SetBodyActive, SetPumpSpeed, ThermalBody
from .intellicenter_readonly import POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT, is_pmpcirc_native_id
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from .pool_circulation_ownership import (
    FiltrationCirculationLease,
    PoolCirculationOwner,
    PoolCirculationOwnershipRegistry,
)
from .thermal_runtime_ownership import (
    SHARED_HYDRAULIC_SAFETY_BY_CONCEPT,
    SharedHydraulicSafetyClass,
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
)


class FiltrationAutomaticDriverState(StrEnum):
    DISABLED = "disabled"
    BLOCKED = "blocked"
    AWAITING_REOBSERVATION = "awaiting_reobservation"
    OWNED = "owned"
    SUSPENDED = "suspended"
    HANDOFF_PENDING = "handoff_pending"
    FAILED = "failed"
    PREEMPTED = "preempted"
    UNLOADED = "unloaded"


class FiltrationExecutionStep(StrEnum):
    BODY_ON = "body_on"
    PUMP_SETPOINT = "pump_setpoint"
    BODY_OFF = "body_off"


@dataclass(frozen=True, slots=True)
class FiltrationAutomaticExecutionFrame:
    epoch_identity: str
    observed_at: datetime
    observations: tuple[PoolObservation, ...]
    filtration: FiltrationAccountingSnapshot | None
    pool_pump_circuit_id: str | None
    physical_authority_ready: bool
    physical_authority_blocker: str | None
    grid_on: bool
    thermal_candidate_ready: bool
    thermal_owned: bool
    external_changes: ExternalChangeBatch = ExternalChangeBatch(())

    def __post_init__(self) -> None:
        if not self.epoch_identity.strip():
            raise ValueError("filtration epoch identity must not be empty")
        _require_aware(self.observed_at)
        if self.physical_authority_ready == bool(self.physical_authority_blocker):
            raise ValueError("physical readiness must match blocker")
        if self.pool_pump_circuit_id is not None and not is_pmpcirc_native_id(
            self.pool_pump_circuit_id
        ):
            raise ValueError("filtration requires a concrete Pool PMPCIRC identity")
        object.__setattr__(self, "observations", tuple(self.observations))


class FiltrationAutomaticDeliveryPort(Protocol):
    @property
    def available(self) -> bool: ...

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt: ...


class FiltrationAutomaticDeliveryFactory(Protocol):
    def for_operation(
        self,
        *,
        frame: FiltrationAutomaticExecutionFrame,
        session_id: str,
        operation: PoolOperation,
        cleanup: bool,
    ) -> FiltrationAutomaticDeliveryPort: ...


@dataclass(frozen=True, slots=True)
class FiltrationExecutionAttempt:
    step: FiltrationExecutionStep
    operation: PoolOperation
    correlation_id: str
    receipt_id: str
    delivered_at: datetime
    deadline: datetime

    def __post_init__(self) -> None:
        for name in ("correlation_id", "receipt_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        _require_aware(self.delivered_at)
        _require_aware(self.deadline)
        if self.deadline <= self.delivered_at:
            raise ValueError("filtration verification deadline must follow delivery")


@dataclass(frozen=True, slots=True)
class FiltrationAutomaticAssessment:
    state: FiltrationAutomaticDriverState
    evaluated_at: datetime
    requested_enabled: bool
    effective_enabled: bool
    blocker: str | None
    session_id: str | None
    current_step: FiltrationExecutionStep | None
    target_rpm: int | None
    remaining_runtime_seconds: float | None
    owner: PoolCirculationOwner
    ownership_generation: int | None
    owned_concepts: tuple[str, ...]
    accepted_delivery_count: int
    last_accepted_correlation_id: str | None
    command_delivery_performed: bool
    last_transition_at: datetime
    last_failure_reason: str | None


@dataclass(slots=True)
class FiltrationAutomaticExecutionDriver:
    """Advance canonical filtration from fresh native epochs only."""

    ownership: PoolCirculationOwnershipRegistry
    requested_enabled: bool = False
    verification_timeout: timedelta = timedelta(seconds=45)
    pump_rpm_tolerance: int = 25
    assessment: FiltrationAutomaticAssessment | None = None
    session_id: str | None = None
    attempt: FiltrationExecutionAttempt | None = None
    _enabled_after_epoch: str | None = field(default=None, init=False, repr=False)
    _last_epoch: str | None = field(default=None, init=False, repr=False)
    _last_at: datetime | None = field(default=None, init=False, repr=False)
    _accepted_delivery_count: int = field(default=0, init=False, repr=False)
    _last_correlation_id: str | None = field(default=None, init=False, repr=False)
    _last_failure_reason: str | None = field(default=None, init=False, repr=False)
    _requires_reenable: bool = field(default=False, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)

    @property
    def last_epoch_identity(self) -> str | None:
        return self._last_epoch

    def process_disabled_epoch(
        self,
        frame: FiltrationAutomaticExecutionFrame,
    ) -> FiltrationAutomaticAssessment:
        """Publish a disabled frame without executing a cached candidate."""

        self._last_epoch = frame.epoch_identity
        self._last_at = frame.observed_at
        return self._publish(
            FiltrationAutomaticDriverState.DISABLED,
            at=frame.observed_at,
            blocker="automatic_filtration_driver_disabled",
            frame=frame,
            command=False,
        )

    def set_enabled(
        self,
        enabled: bool,
        *,
        changed_at: datetime,
        current_epoch_identity: str | None,
    ) -> None:
        _require_aware(changed_at)
        enabled = bool(enabled)
        if enabled and not self.requested_enabled:
            self._enabled_after_epoch = current_epoch_identity
            self._requires_reenable = False
            self._last_failure_reason = None
        self.requested_enabled = enabled
        self._publish(
            FiltrationAutomaticDriverState.DISABLED if not enabled else FiltrationAutomaticDriverState.BLOCKED,
            at=changed_at,
            blocker=(
                "automatic_filtration_driver_disabled"
                if not enabled
                else "automatic_filtration_fresh_epoch_required_after_enable"
            ),
            frame=None,
            command=False,
        )

    async def process_epoch(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        *,
        delivery_factory: FiltrationAutomaticDeliveryFactory,
    ) -> FiltrationAutomaticAssessment:
        if self._unloaded:
            return self._publish(
                FiltrationAutomaticDriverState.UNLOADED,
                at=frame.observed_at,
                blocker="automatic_filtration_driver_unloaded",
                frame=frame,
                command=False,
            )
        if frame.epoch_identity == self._last_epoch:
            assert self.assessment is not None
            return self.assessment
        if self._last_at is not None and frame.observed_at < self._last_at:
            assert self.assessment is not None
            return self.assessment
        self.ownership.begin_epoch(frame.epoch_identity)
        self._last_epoch = frame.epoch_identity
        self._last_at = frame.observed_at
        lease = self.ownership.filtration_lease
        if (
            lease is not None
            and frame.pool_pump_circuit_id is not None
            and frame.pool_pump_circuit_id != lease.pool_pump_circuit_id
        ):
            self.ownership.release_filtration(session_id=lease.session_id)
            self.session_id = None
            self.attempt = None
            self._requires_reenable = True
            return self._publish(
                FiltrationAutomaticDriverState.PREEMPTED,
                at=frame.observed_at,
                blocker="automatic_filtration_pump_circuit_identity_changed",
                frame=frame,
                command=False,
                failure="automatic_filtration_pump_circuit_identity_changed",
            )
        if self._externally_preempted(frame, lease):
            if lease is not None:
                self.ownership.release_filtration(session_id=lease.session_id)
            self.session_id = None
            self.attempt = None
            self._requires_reenable = True
            return self._publish(
                FiltrationAutomaticDriverState.PREEMPTED,
                at=frame.observed_at,
                blocker="automatic_filtration_external_takeover",
                frame=frame,
                command=False,
                failure="automatic_filtration_external_takeover",
            )
        if self._requires_reenable:
            return self._blocked(frame, "automatic_filtration_reenable_required")
        suspended = (
            lease is not None
            and lease.verified
            and self.ownership.owner is PoolCirculationOwner.FILTRATION_SUSPENDED
        )
        if suspended:
            assert lease is not None
            pool = _live_state(
                {item.observation_id: item for item in frame.observations}.get(
                    "pool.active"
                ),
                frame.observed_at,
            )
            if pool.usable and pool.value is False:
                recovery = self._recover_suspended(frame, lease)
                if recovery is not None:
                    return recovery
        blocker = self._safety_blocker(
            frame,
            allow_pool_off=(
                suspended
                or (
                    self.attempt is not None
                    and self.attempt.step is FiltrationExecutionStep.BODY_OFF
                )
            ),
        )
        if lease is not None and lease.verified and _transient_evidence_loss(blocker):
            self.ownership.suspend_filtration(session_id=lease.session_id)
            return self._publish(
                FiltrationAutomaticDriverState.SUSPENDED,
                at=frame.observed_at,
                blocker=blocker,
                frame=frame,
                command=False,
            )
        if suspended:
            assert lease is not None
            if blocker is not None:
                return self._fail(frame, blocker, preempted=True)
            recovery = self._recover_suspended(frame, lease)
            if recovery is not None:
                return recovery
            self.ownership.resume_filtration(
                session_id=lease.session_id,
                confirmed_at=frame.observed_at,
            )
        if self.attempt is not None:
            return await self._verify_attempt(frame, delivery_factory)
        if lease is not None and frame.thermal_candidate_ready:
            return self._publish(
                FiltrationAutomaticDriverState.HANDOFF_PENDING,
                at=frame.observed_at,
                blocker="automatic_filtration_thermal_successor_pending",
                frame=frame,
                command=False,
            )
        immediate = bool(
            frame.filtration
            and frame.filtration.disposition
            in {FiltrationDisposition.RUN_NOW, FiltrationDisposition.CREDITING}
        )
        if not self.requested_enabled and lease is None:
            return self._publish(
                FiltrationAutomaticDriverState.DISABLED,
                at=frame.observed_at,
                blocker="automatic_filtration_driver_disabled",
                frame=frame,
                command=False,
            )
        if self.requested_enabled and frame.epoch_identity == self._enabled_after_epoch:
            return self._blocked(
                frame,
                "automatic_filtration_fresh_epoch_required_after_enable",
            )
        if lease is None and not immediate:
            return self._blocked(frame, "automatic_filtration_not_immediately_required")
        if frame.thermal_owned or self.ownership.owner is PoolCirculationOwner.THERMAL:
            return self._blocked(frame, "automatic_filtration_thermal_owner_active")
        if blocker is not None:
            if lease is not None:
                return self._fail(frame, blocker, preempted=True)
            return self._blocked(frame, blocker)
        by_id = {item.observation_id: item for item in frame.observations}
        pool = _live_state(by_id.get("pool.active"), frame.observed_at)
        if lease is None:
            if not self.requested_enabled:
                return self._blocked(frame, "automatic_filtration_driver_disabled")
            if pool.value is True:
                return self._blocked(frame, "automatic_filtration_preexisting_body_unowned")
            self.session_id = _session_id(frame)
            return await self._deliver(
                frame,
                delivery_factory,
                FiltrationExecutionStep.BODY_ON,
                SetBodyActive(
                    equipment_id=ThermalBody.POOL.value,
                    active=True,
                    metadata={"reason_code": "automatic_filtration_body_activation"},
                ),
                cleanup=False,
            )
        self.session_id = lease.session_id
        if not immediate or not self.requested_enabled:
            if lease.body_activation is None:
                self.ownership.release_filtration(session_id=lease.session_id)
                return self._blocked(frame, "automatic_filtration_body_provenance_unavailable")
            return await self._deliver(
                frame,
                delivery_factory,
                FiltrationExecutionStep.BODY_OFF,
                SetBodyActive(
                    equipment_id=ThermalBody.POOL.value,
                    active=False,
                    metadata={"reason_code": "automatic_filtration_owned_shutdown"},
                ),
                cleanup=True,
            )
        if lease.verified:
            return self._publish(
                FiltrationAutomaticDriverState.OWNED,
                at=frame.observed_at,
                blocker=None,
                frame=frame,
                command=False,
            )
        return await self._deliver_pump(frame, delivery_factory)

    def _recover_suspended(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        lease: FiltrationCirculationLease,
    ) -> FiltrationAutomaticAssessment | None:
        """Recover only from retained provenance and fresh authoritative truth."""

        by_id = {item.observation_id: item for item in frame.observations}
        pool = _live_state(by_id.get("pool.active"), frame.observed_at)
        if pool.value is False:
            if (
                self.attempt is not None
                and self.attempt.step is FiltrationExecutionStep.BODY_OFF
                and not _later(pool.observed_at, self.attempt.delivered_at)
            ):
                return self._publish(
                    FiltrationAutomaticDriverState.SUSPENDED,
                    at=frame.observed_at,
                    blocker="automatic_filtration_cleanup_verification_pending",
                    frame=frame,
                    command=False,
                )
            self.ownership.release_filtration(session_id=lease.session_id)
            self.session_id = None
            self.attempt = None
            return self._publish(
                (
                    FiltrationAutomaticDriverState.DISABLED
                    if not self.requested_enabled
                    else FiltrationAutomaticDriverState.BLOCKED
                ),
                at=frame.observed_at,
                blocker="automatic_filtration_pool_off_observed_after_suspension",
                frame=frame,
                command=False,
            )
        if pool.value is not True:
            raise AssertionError("usable Pool activity must be an exact boolean")
        pump_provenance = lease.pump_setpoint
        configured = _live_state(
            by_id.get(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT),
            frame.observed_at,
        )
        actual = _live_state(by_id.get("pump.rpm"), frame.observed_at)
        if (
            pump_provenance is None
            or type(pump_provenance.intended_value) is not int
            or configured.value != pump_provenance.intended_value
            or isinstance(actual.value, bool)
            or not isinstance(actual.value, (int, float))
            or abs(float(actual.value) - pump_provenance.intended_value)
            > self.pump_rpm_tolerance
        ):
            return self._fail(
                frame,
                "automatic_filtration_owned_pump_state_conflict",
                preempted=True,
            )
        if self.attempt is not None:
            if self.attempt.step is not FiltrationExecutionStep.BODY_OFF:
                return self._fail(
                    frame,
                    "automatic_filtration_suspended_attempt_invalid",
                    preempted=True,
                )
            return self._publish(
                FiltrationAutomaticDriverState.SUSPENDED,
                at=frame.observed_at,
                blocker=(
                    "automatic_filtration_cleanup_verification_timed_out"
                    if frame.observed_at >= self.attempt.deadline
                    else "automatic_filtration_cleanup_verification_pending"
                ),
                frame=frame,
                command=False,
            )
        return None

    async def _verify_attempt(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        delivery_factory: FiltrationAutomaticDeliveryFactory,
    ) -> FiltrationAutomaticAssessment:
        attempt = self.attempt
        assert attempt is not None
        blocker = self._safety_blocker(frame, allow_pool_off=attempt.step is FiltrationExecutionStep.BODY_OFF)
        if blocker is not None:
            return self._fail(frame, blocker, preempted=True)
        by_id = {item.observation_id: item for item in frame.observations}
        if attempt.step is FiltrationExecutionStep.BODY_ON:
            pool = _live_state(by_id.get("pool.active"), frame.observed_at)
            verified = pool.value is True and _later(pool.observed_at, attempt.delivered_at)
        elif attempt.step is FiltrationExecutionStep.BODY_OFF:
            pool = _live_state(by_id.get("pool.active"), frame.observed_at)
            verified = pool.value is False and _later(pool.observed_at, attempt.delivered_at)
        else:
            configured = _live_state(
                by_id.get(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT),
                frame.observed_at,
            )
            actual = _live_state(by_id.get("pump.rpm"), frame.observed_at)
            operation = attempt.operation
            assert isinstance(operation, SetPumpSpeed)
            verified = bool(
                configured.value == operation.rpm
                and _later(configured.observed_at, attempt.delivered_at)
                and isinstance(actual.value, (int, float))
                and not isinstance(actual.value, bool)
                and abs(float(actual.value) - operation.rpm) <= self.pump_rpm_tolerance
                and _later(actual.observed_at, attempt.delivered_at)
            )
        if verified:
            self.attempt = None
            if attempt.step is FiltrationExecutionStep.BODY_OFF:
                assert self.session_id is not None
                self.ownership.release_filtration(session_id=self.session_id)
                self.session_id = None
                return self._publish(
                    FiltrationAutomaticDriverState.DISABLED if not self.requested_enabled else FiltrationAutomaticDriverState.BLOCKED,
                    at=frame.observed_at,
                    blocker="automatic_filtration_pool_off_verified",
                    frame=frame,
                    command=False,
                )
            if attempt.step is FiltrationExecutionStep.BODY_ON:
                assert self.session_id is not None
                self.ownership.confirm_filtration_body(
                    session_id=self.session_id,
                    confirmed_at=frame.observed_at,
                )
                return await self._deliver_pump(frame, delivery_factory)
            assert self.session_id is not None
            self.ownership.confirm_filtration(
                session_id=self.session_id,
                confirmed_at=frame.observed_at,
            )
            return self._publish(
                FiltrationAutomaticDriverState.OWNED,
                at=frame.observed_at,
                blocker=None,
                frame=frame,
                command=False,
            )
        if frame.observed_at >= attempt.deadline:
            return self._fail(
                frame,
                "automatic_filtration_verification_timed_out",
            )
        return self._publish(
            FiltrationAutomaticDriverState.AWAITING_REOBSERVATION,
            at=frame.observed_at,
            blocker=None,
            frame=frame,
            command=False,
        )

    async def _deliver_pump(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        delivery_factory: FiltrationAutomaticDeliveryFactory,
    ) -> FiltrationAutomaticAssessment:
        assert frame.filtration is not None
        if frame.pool_pump_circuit_id is None:
            return self._blocked(frame, "automatic_filtration_pool_pump_circuit_unresolved")
        return await self._deliver(
            frame,
            delivery_factory,
            FiltrationExecutionStep.PUMP_SETPOINT,
            SetPumpSpeed(
                equipment_id=frame.pool_pump_circuit_id,
                rpm=frame.filtration.ordinary_filtration_rpm,
                metadata={"reason_code": "automatic_filtration_pump_baseline"},
            ),
            cleanup=False,
        )

    async def _deliver(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        delivery_factory: FiltrationAutomaticDeliveryFactory,
        step: FiltrationExecutionStep,
        operation: PoolOperation,
        *,
        cleanup: bool,
    ) -> FiltrationAutomaticAssessment:
        assert self.session_id is not None
        if not self.ownership.filtration_may_deliver(
            epoch_identity=frame.epoch_identity,
            session_id=self.session_id,
        ):
            return self._blocked(frame, "automatic_filtration_circulation_owner_conflict")
        try:
            delivery = delivery_factory.for_operation(
                frame=frame,
                session_id=self.session_id,
                operation=operation,
                cleanup=cleanup,
            )
        except (RuntimeError, ValueError) as exc:
            return self._fail(frame, f"automatic_filtration_delivery_binding_failed:{_bounded(str(exc))}")
        if not delivery.available:
            return self._blocked(frame, "automatic_filtration_delivery_unavailable")
        correlation_id = f"automatic-filtration:{self.session_id}:{operation.operation_id}"
        try:
            receipt = await delivery.deliver(operation, correlation_id=correlation_id)
        except Exception as exc:
            return self._fail(frame, f"automatic_filtration_delivery_exception:{type(exc).__name__}")
        if not receipt.accepted:
            return self._fail(frame, f"automatic_filtration_delivery_{receipt.status.value}")
        if step is not FiltrationExecutionStep.BODY_OFF:
            assert frame.pool_pump_circuit_id is not None
            concept = (
                ThermalRuntimeOwnedConcept.BODY_ACTIVATION
                if step is FiltrationExecutionStep.BODY_ON
                else ThermalRuntimeOwnedConcept.PUMP_SETPOINT
            )
            if step is FiltrationExecutionStep.BODY_ON:
                intended: bool | int = True
            else:
                assert isinstance(operation, SetPumpSpeed)
                intended = operation.rpm
            self.ownership.record_filtration_delivery(
                session_id=self.session_id,
                pool_pump_circuit_id=frame.pool_pump_circuit_id,
                accepted_at=frame.observed_at,
                provenance=ThermalRuntimeConceptProvenance(
                    concept=concept,
                    operation_id=operation.operation_id,
                    receipt_id=receipt.command_id,
                    correlation_id=correlation_id,
                    intended_value=intended,
                ),
            )
        self.attempt = FiltrationExecutionAttempt(
            step=step,
            operation=operation,
            correlation_id=correlation_id,
            receipt_id=receipt.command_id,
            delivered_at=frame.observed_at,
            deadline=frame.observed_at + self.verification_timeout,
        )
        self._accepted_delivery_count += 1
        self._last_correlation_id = correlation_id
        return self._publish(
            FiltrationAutomaticDriverState.AWAITING_REOBSERVATION,
            at=frame.observed_at,
            blocker=None,
            frame=frame,
            command=True,
        )

    def _safety_blocker(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        *,
        allow_pool_off: bool = False,
    ) -> str | None:
        if not frame.physical_authority_ready:
            return frame.physical_authority_blocker or "automatic_filtration_physical_authority_unavailable"
        if not frame.grid_on:
            return "automatic_filtration_grid_not_authoritatively_on"
        if frame.filtration is None or frame.filtration.evaluated_at != frame.observed_at:
            return "automatic_filtration_accounting_not_current"
        if frame.pool_pump_circuit_id is None:
            return "automatic_filtration_pool_pump_circuit_unresolved"
        by_id = {item.observation_id: item for item in frame.observations}
        pool = _live_state(by_id.get("pool.active"), frame.observed_at)
        spa = _live_state(by_id.get("spa.active"), frame.observed_at)
        pump = _live_state(by_id.get("pump.rpm"), frame.observed_at)
        configured = _live_state(
            by_id.get(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT),
            frame.observed_at,
        )
        if not pool.usable or (pool.value is not False and pool.value is not True):
            return "automatic_filtration_pool_activity_unusable"
        if not spa.usable:
            return "automatic_filtration_spa_activity_unusable"
        if spa.value is not False:
            return "automatic_filtration_spa_topology_blocked"
        if (
            not pump.usable
            or isinstance(pump.value, bool)
            or not isinstance(pump.value, (int, float))
        ):
            return "automatic_filtration_pump_observation_unusable"
        if (
            not configured.usable
            or isinstance(configured.value, bool)
            or not isinstance(configured.value, (int, float))
        ):
            return "automatic_filtration_configured_speed_unusable"
        if (
            self.ownership.filtration_lease is None
            and pool.value is False
            and float(pump.value) > self.pump_rpm_tolerance
        ):
            return "automatic_filtration_preexisting_pump_unowned"
        if not allow_pool_off and self.ownership.filtration_lease is not None and pool.value is not True:
            return "automatic_filtration_pool_topology_lost"
        for concept, safety in SHARED_HYDRAULIC_SAFETY_BY_CONCEPT.items():
            if safety is SharedHydraulicSafetyClass.NON_CONFLICTING:
                continue
            state = _live_state(by_id.get(concept), frame.observed_at)
            if not state.usable:
                return f"automatic_filtration_shared_hydraulic_unusable:{concept}"
            if state.value is not False:
                return f"automatic_filtration_shared_hydraulic_conflict:{concept}"
        return None

    def _externally_preempted(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        lease: FiltrationCirculationLease | None,
    ) -> bool:
        if lease is None:
            return False
        for event in frame.external_changes.events:
            if (
                event.concept not in POOL_CIRCULATION_TAKEOVER_CONCEPTS
                or event.observed_at < lease.established_at
                or event.observed_at > frame.observed_at
            ):
                continue
            if event.concept == "pump.rpm":
                pump = lease.pump_setpoint
                if (
                    pump is None
                    or lease.pump_established_at is None
                    or event.observed_at <= lease.pump_established_at
                ):
                    continue
                if (
                    type(pump.intended_value) is int
                    and isinstance(event.new_value, (int, float))
                    and not isinstance(event.new_value, bool)
                    and abs(float(event.new_value) - pump.intended_value)
                    <= self.pump_rpm_tolerance
                ):
                    continue
            return True
        return False

    def _fail(
        self,
        frame: FiltrationAutomaticExecutionFrame,
        reason: str,
        *,
        preempted: bool = False,
    ) -> FiltrationAutomaticAssessment:
        lease = self.ownership.filtration_lease
        if lease is not None:
            self.ownership.release_filtration(session_id=lease.session_id)
        self.session_id = None
        self.attempt = None
        self._requires_reenable = True
        return self._publish(
            FiltrationAutomaticDriverState.PREEMPTED if preempted else FiltrationAutomaticDriverState.FAILED,
            at=frame.observed_at,
            blocker=reason,
            frame=frame,
            command=False,
            failure=reason,
        )

    def _blocked(self, frame: FiltrationAutomaticExecutionFrame, reason: str) -> FiltrationAutomaticAssessment:
        return self._publish(
            FiltrationAutomaticDriverState.BLOCKED,
            at=frame.observed_at,
            blocker=reason,
            frame=frame,
            command=False,
        )

    def unload(self, *, unloaded_at: datetime) -> None:
        _require_aware(unloaded_at)
        self._unloaded = True
        self.requested_enabled = False
        self.session_id = None
        self.attempt = None
        self.ownership.unload()
        self._publish(
            FiltrationAutomaticDriverState.UNLOADED,
            at=unloaded_at,
            blocker="automatic_filtration_driver_unloaded",
            frame=None,
            command=False,
        )

    def fail_closed(self, *, failed_at: datetime, reason: str) -> None:
        """Invalidate continuation after an adapter failure without cleanup."""

        _require_aware(failed_at)
        lease = self.ownership.filtration_lease
        if lease is not None:
            self.ownership.release_filtration(session_id=lease.session_id)
        self.session_id = None
        self.attempt = None
        self._requires_reenable = True
        self._publish(
            FiltrationAutomaticDriverState.FAILED,
            at=failed_at,
            blocker=_bounded(reason),
            frame=None,
            command=False,
            failure=_bounded(reason),
        )

    def diagnostics(self) -> Mapping[str, object]:
        assessment = self.assessment
        if assessment is None:
            return MappingProxyType(
                {
                    "state": FiltrationAutomaticDriverState.DISABLED.value,
                    "requested_enabled": self.requested_enabled,
                    "effective_enabled": False,
                    "blocker": "automatic_filtration_not_evaluated",
                    "command_delivery_performed": False,
                }
            )
        return MappingProxyType(
            {
                "state": assessment.state.value,
                "requested_enabled": assessment.requested_enabled,
                "effective_enabled": assessment.effective_enabled,
                "blocker": assessment.blocker,
                "session_id": assessment.session_id,
                "current_step": None if assessment.current_step is None else assessment.current_step.value,
                "target_rpm": assessment.target_rpm,
                "remaining_filtration_runtime_seconds": assessment.remaining_runtime_seconds,
                "runtime_owner": assessment.owner.value,
                "owned_concepts": list(assessment.owned_concepts),
                "ownership_generation": assessment.ownership_generation,
                "accepted_delivery_count": assessment.accepted_delivery_count,
                "last_accepted_correlation_id": assessment.last_accepted_correlation_id,
                "awaiting_reobservation": assessment.state is FiltrationAutomaticDriverState.AWAITING_REOBSERVATION,
                "awaiting_verification": self.attempt is not None,
                "command_delivery_performed": assessment.command_delivery_performed,
                "last_transition_at": assessment.last_transition_at.isoformat(),
                "last_failure_reason": assessment.last_failure_reason,
                "fresh_authoritative_epoch_required": True,
                "ownership_persisted": False,
            }
        )

    def _publish(
        self,
        state: FiltrationAutomaticDriverState,
        *,
        at: datetime,
        blocker: str | None,
        frame: FiltrationAutomaticExecutionFrame | None,
        command: bool,
        failure: str | None = None,
    ) -> FiltrationAutomaticAssessment:
        lease = self.ownership.filtration_lease
        concepts = tuple(
            concept
            for concept, present in (
                ("body_activation", bool(lease and lease.body_activation)),
                ("pump_setpoint", bool(lease and lease.pump_setpoint)),
            )
            if present
        )
        previous = self.assessment
        if failure is not None:
            self._last_failure_reason = _bounded(failure)
        transitioned = previous is None or (previous.state, previous.blocker) != (state, blocker)
        self.assessment = FiltrationAutomaticAssessment(
            state=state,
            evaluated_at=at,
            requested_enabled=self.requested_enabled,
            effective_enabled=bool(self.requested_enabled and frame and frame.physical_authority_ready),
            blocker=blocker,
            session_id=self.session_id,
            current_step=None if self.attempt is None else self.attempt.step,
            target_rpm=None if frame is None or frame.filtration is None else frame.filtration.ordinary_filtration_rpm,
            remaining_runtime_seconds=(
                None
                if frame is None or frame.filtration is None
                else frame.filtration.total_remaining_runtime.total_seconds()
            ),
            owner=self.ownership.owner,
            ownership_generation=None if lease is None else lease.generation,
            owned_concepts=concepts,
            accepted_delivery_count=self._accepted_delivery_count,
            last_accepted_correlation_id=self._last_correlation_id,
            command_delivery_performed=command,
            last_transition_at=(
                at
                if previous is None or transitioned
                else previous.last_transition_at
            ),
            last_failure_reason=self._last_failure_reason,
        )
        return self.assessment


@dataclass(frozen=True, slots=True)
class _LiveState:
    value: object
    usable: bool
    observed_at: datetime | None


def _live_state(observation: PoolObservation | None, at: datetime) -> _LiveState:
    if observation is None:
        return _LiveState(None, False, None)
    fresh = observation.freshness(
        clock=FixedClock(at),
        policy=FreshnessPolicy(max_age=timedelta(seconds=30)),
    ) is ObservationFreshness.FRESH
    usable = bool(
        fresh
        and observation.source_kind is ObservationSourceKind.LIVE
        and observation.quality is ObservationQuality.GOOD
        and observation.confidence >= 0.5
    )
    return _LiveState(observation.value, usable, observation.observed_at)


def _later(observed_at: datetime | None, delivered_at: datetime) -> bool:
    return observed_at is not None and observed_at > delivered_at


def _transient_evidence_loss(blocker: str | None) -> bool:
    if blocker is None:
        return False
    return blocker in {
        "automatic_filtration_accounting_not_current",
        "automatic_filtration_pool_activity_unusable",
        "automatic_filtration_spa_activity_unusable",
        "automatic_filtration_pump_observation_unusable",
        "automatic_filtration_configured_speed_unusable",
        "automatic_filtration_pool_pump_circuit_unresolved",
    } or blocker.startswith("automatic_filtration_shared_hydraulic_unusable:")


def _session_id(frame: FiltrationAutomaticExecutionFrame) -> str:
    payload = (
        f"{frame.epoch_identity}|{frame.observed_at.isoformat()}|"
        f"{frame.pool_pump_circuit_id}|"
        f"{None if frame.filtration is None else frame.filtration.ordinary_filtration_rpm}"
    )
    return "automatic-filtration-session-" + sha256(payload.encode()).hexdigest()[:24]


def _bounded(value: str, limit: int = 256) -> str:
    return " ".join(value.split())[:limit]


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("automatic filtration timestamp must be timezone-aware")


__all__ = [
    "FiltrationAutomaticAssessment",
    "FiltrationAutomaticDeliveryFactory",
    "FiltrationAutomaticDeliveryPort",
    "FiltrationAutomaticDriverState",
    "FiltrationAutomaticExecutionDriver",
    "FiltrationAutomaticExecutionFrame",
    "FiltrationExecutionAttempt",
    "FiltrationExecutionStep",
]
