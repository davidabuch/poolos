"""Command-free runtime ownership and preemption for thermal lifecycles.

Observed equipment state can confirm or invalidate an existing lease, but it
can never create one. A lease originates only from accepted, session-scoped
thermal delivery provenance and exposes no execution or delivery method.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    pump_event_conflicts_with_provenance,
)
from .integration import PhysicalHeatMode, ThermalBody
from .pump_speed_session import PumpSpeedOverrideState, PumpSpeedSessionPurpose
from .thermal_execution_currentness import (
    ThermalExecutionCompatibilityDisposition,
    ThermalExecutionCurrentness,
    ThermalExecutionPurposeKind,
    ThermalExecutionProgress,
    assess_execution_compatibility,
)
from .thermal_live_execution import (
    ThermalLiveExecutionContext,
    ThermalLiveExecutionOwnership,
)


class ThermalRuntimeOwnershipStatus(StrEnum):
    """Current lifecycle state of one runtime ownership lease."""

    UNOWNED = "unowned"
    OWNED = "owned"
    PREEMPTED = "preempted"
    SUPERSEDED = "superseded"
    RELINQUISHED = "relinquished"


class ThermalRuntimeOwnershipDisposition(StrEnum):
    """Result of one side-effect-free ownership transition request."""

    NO_OWNERSHIP = "no_ownership"
    ESTABLISHED = "established"
    RETAINED = "retained"
    PREEMPTED = "preempted"
    SUPERSEDED = "superseded"
    HANDED_OFF = "handed_off"
    RELINQUISHED = "relinquished"
    DENIED = "denied"


class ThermalRuntimeOwnedConcept(StrEnum):
    """Physical concepts for which accepted delivery can prove provenance."""

    BODY_ACTIVATION = "body_activation"
    PUMP_SETPOINT = "pump_setpoint"
    HEAT_SOURCE = "heat_source"


class SharedHydraulicSafetyClass(StrEnum):
    """Caller-established hydraulic relevance of one observed circuit."""

    CONFLICTING = "conflicting"
    NON_CONFLICTING = "non_conflicting"
    UNKNOWN = "unknown"


SHARED_HYDRAULIC_SAFETY_BY_CONCEPT: Mapping[
    str, SharedHydraulicSafetyClass
] = MappingProxyType(
    {
        "waterfall.active": SharedHydraulicSafetyClass.CONFLICTING,
        "jets.active": SharedHydraulicSafetyClass.CONFLICTING,
        "slide.active": SharedHydraulicSafetyClass.CONFLICTING,
        "pool_light.active": SharedHydraulicSafetyClass.NON_CONFLICTING,
    }
)


def shared_hydraulic_safety_class(concept: str) -> SharedHydraulicSafetyClass:
    """Return the repository-supported thermal relevance of one concept."""

    return SHARED_HYDRAULIC_SAFETY_BY_CONCEPT.get(
        concept,
        SharedHydraulicSafetyClass.UNKNOWN,
    )


@dataclass(frozen=True, slots=True)
class ThermalRuntimeConceptProvenance:
    """Exact accepted operation/receipt provenance for one owned concept."""

    concept: ThermalRuntimeOwnedConcept
    operation_id: str
    receipt_id: str
    correlation_id: str
    intended_value: bool | int | PhysicalHeatMode

    def __post_init__(self) -> None:
        for name in ("operation_id", "receipt_id", "correlation_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class ThermalResidualTerminationEntitlement:
    """Ephemeral proof of PoolOS-created effects eligible only for reduction.

    This is copied from an accepted runtime lease before continuation ends. It
    cannot establish or continue normal ownership and is never persisted.
    """

    entitlement_id: str
    lease_id: str
    generation: int
    body: ThermalBody
    originating_execution_plan_id: str
    originating_lease_established_at: datetime
    retained_at: datetime
    reason_code: str
    body_activation: ThermalRuntimeConceptProvenance | None = None
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    heat_source: ThermalRuntimeConceptProvenance | None = None
    pump_setpoint_accepted_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "entitlement_id",
            "lease_id",
            "originating_execution_plan_id",
            "reason_code",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.generation < 1:
            raise ValueError("termination entitlement generation must be positive")
        _require_aware(self.retained_at, "retained_at")
        _require_aware(
            self.originating_lease_established_at,
            "originating_lease_established_at",
        )
        if self.retained_at < self.originating_lease_established_at:
            raise ValueError("termination retention cannot precede lease establishment")
        object.__setattr__(self, "body", ThermalBody(self.body))
        if self.pump_setpoint_accepted_at is not None:
            _require_aware(
                self.pump_setpoint_accepted_at,
                "pump_setpoint_accepted_at",
            )
            if self.pump_setpoint_accepted_at > self.retained_at:
                raise ValueError("residual pump accepted_at cannot follow retention")

    @property
    def owned_concepts(self) -> tuple[ThermalRuntimeOwnedConcept, ...]:
        return tuple(
            concept
            for concept, provenance in (
                (ThermalRuntimeOwnedConcept.BODY_ACTIVATION, self.body_activation),
                (ThermalRuntimeOwnedConcept.PUMP_SETPOINT, self.pump_setpoint),
                (ThermalRuntimeOwnedConcept.HEAT_SOURCE, self.heat_source),
            )
            if provenance is not None
        )


@dataclass(frozen=True, slots=True)
class SharedHydraulicCircuitEvidence:
    """One already-classified circuit observation supplied by an orchestrator."""

    concept: str
    active: bool | None
    fresh: bool
    usable: bool
    safety_class: SharedHydraulicSafetyClass
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.concept.strip():
            raise ValueError("shared hydraulic concept must not be empty")
        if self.active is not None and not isinstance(self.active, bool):
            raise ValueError("shared hydraulic active state must be boolean or None")
        object.__setattr__(
            self,
            "safety_class",
            SharedHydraulicSafetyClass(self.safety_class),
        )
        if self.observed_at is not None:
            _require_aware(self.observed_at, "shared hydraulic observed_at")


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOwnershipLease:
    """One immutable, session-originated runtime thermal ownership lease."""

    lease_id: str
    generation: int
    body: ThermalBody
    evaluation_id: str
    thermal_plan_id: str
    execution_plan_id: str
    requested_mode: str
    established_at: datetime
    last_confirmed_at: datetime
    status: ThermalRuntimeOwnershipStatus
    reason_code: str
    body_activation: ThermalRuntimeConceptProvenance | None = None
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    heat_source: ThermalRuntimeConceptProvenance | None = None
    predecessor_lease_id: str | None = None
    ended_at: datetime | None = None
    originating_currentness: ThermalExecutionCurrentness | None = None
    execution_progress: ThermalExecutionProgress | None = None
    verified_concepts: tuple[ThermalRuntimeOwnedConcept, ...] = ()
    body_activation_accepted_at: datetime | None = None
    pump_setpoint_accepted_at: datetime | None = None
    heat_source_accepted_at: datetime | None = None
    pump_session_id: str | None = None
    pump_session_effective_rpm: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "lease_id",
            "evaluation_id",
            "thermal_plan_id",
            "execution_plan_id",
            "requested_mode",
            "reason_code",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.generation < 1:
            raise ValueError("ownership generation must be positive")
        _require_aware(self.established_at, "established_at")
        _require_aware(self.last_confirmed_at, "last_confirmed_at")
        if self.last_confirmed_at < self.established_at:
            raise ValueError("last confirmation cannot precede establishment")
        if self.ended_at is not None:
            _require_aware(self.ended_at, "ended_at")
            if self.ended_at < self.established_at:
                raise ValueError("ownership end cannot precede establishment")
        object.__setattr__(self, "body", ThermalBody(self.body))
        object.__setattr__(self, "status", ThermalRuntimeOwnershipStatus(self.status))
        if (self.originating_currentness is None) != (self.execution_progress is None):
            raise ValueError(
                "ownership currentness and execution progress must be supplied together"
            )
        if self.originating_currentness is not None and (
            self.originating_currentness.evaluation_id != self.evaluation_id
            or self.originating_currentness.plan_id != self.thermal_plan_id
        ):
            raise ValueError("ownership currentness must reference lease origin")
        verified = tuple(
            ThermalRuntimeOwnedConcept(concept)
            for concept in self.verified_concepts
        )
        if len(verified) != len(set(verified)):
            raise ValueError("verified ownership concepts must be unique")
        object.__setattr__(self, "verified_concepts", verified)
        for name in (
            "body_activation_accepted_at",
            "pump_setpoint_accepted_at",
            "heat_source_accepted_at",
        ):
            accepted_at = getattr(self, name)
            if accepted_at is not None:
                _require_aware(accepted_at, name)
        for provenance, accepted_at, label in (
            (
                self.body_activation,
                self.body_activation_accepted_at,
                "body activation",
            ),
            (
                self.pump_setpoint,
                self.pump_setpoint_accepted_at,
                "pump setpoint",
            ),
            (
                self.heat_source,
                self.heat_source_accepted_at,
                "heat source",
            ),
        ):
            if (provenance is None) != (accepted_at is None):
                raise ValueError(
                    f"{label} provenance and acceptance time must be supplied together"
                )
        provenance_by_concept = {
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION: self.body_activation,
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT: self.pump_setpoint,
            ThermalRuntimeOwnedConcept.HEAT_SOURCE: self.heat_source,
        }
        if any(provenance_by_concept[concept] is None for concept in verified):
            raise ValueError("verified concept requires accepted provenance")
        if (self.pump_session_id is None) != (
            self.pump_session_effective_rpm is None
        ):
            raise ValueError("pump session relinquishment binding must be paired")
        if self.pump_session_id is not None and self.pump_setpoint is not None:
            raise ValueError("owned and relinquished pump concepts are exclusive")

    @property
    def owns_body_activation(self) -> bool:
        return self.body_activation is not None

    @property
    def owns_pump_setpoint(self) -> bool:
        return self.pump_setpoint is not None

    @property
    def owns_heat_source(self) -> bool:
        return self.heat_source is not None


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOwnershipState:
    """Current manager state; always command-disabled."""

    status: ThermalRuntimeOwnershipStatus = ThermalRuntimeOwnershipStatus.UNOWNED
    lease: ThermalRuntimeOwnershipLease | None = None
    reason_code: str = "runtime_ownership_unowned"
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if self.command_delivery_enabled:
            raise ValueError("runtime ownership must remain command-disabled")
        if not self.reason_code.strip():
            raise ValueError("reason_code must not be empty")
        status = ThermalRuntimeOwnershipStatus(self.status)
        if status is ThermalRuntimeOwnershipStatus.UNOWNED:
            if self.lease is not None:
                raise ValueError("unowned state cannot retain a lease")
        elif self.lease is None or self.lease.status is not status:
            raise ValueError("owned or terminal state requires a matching lease")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOwnershipDecision:
    """Auditable command-free result of one ownership evaluation."""

    disposition: ThermalRuntimeOwnershipDisposition
    reason_code: str
    previous_status: ThermalRuntimeOwnershipStatus
    current_state: ThermalRuntimeOwnershipState
    evaluated_at: datetime
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        if not self.reason_code.strip():
            raise ValueError("reason_code must not be empty")
        if self.command_delivery_enabled:
            raise ValueError("runtime ownership decisions cannot deliver commands")


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOwnershipTransitionDiagnostic:
    """Bounded evidence explaining the latest terminal ownership transition."""

    previous_status: ThermalRuntimeOwnershipStatus
    current_status: ThermalRuntimeOwnershipStatus
    occurred_at: datetime
    reason_code: str
    affected_concept: ThermalRuntimeOwnedConcept | None
    expected_value: bool | int | str | None
    observed_value: bool | int | str | None
    observed_at: datetime | None
    operation_id: str | None
    correlation_id: str | None
    accepted_at: datetime | None
    execution_purpose_id: str | None
    currentness_disposition: str | None
    external_event_id: str | None
    external_event_concept: str | None
    external_event_observed_at: datetime | None

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")
        for name in ("observed_at", "accepted_at", "external_event_observed_at"):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        if not self.reason_code.strip():
            raise ValueError("transition diagnostic reason_code must not be empty")
        object.__setattr__(
            self,
            "previous_status",
            ThermalRuntimeOwnershipStatus(self.previous_status),
        )
        object.__setattr__(
            self,
            "current_status",
            ThermalRuntimeOwnershipStatus(self.current_status),
        )
        if self.affected_concept is not None:
            object.__setattr__(
                self,
                "affected_concept",
                ThermalRuntimeOwnedConcept(self.affected_concept),
            )


@dataclass(frozen=True, slots=True)
class ThermalRuntimeOwnershipEvidence:
    """Current evidence that may confirm or invalidate an existing lease."""

    evaluated_at: datetime
    current_context: ThermalLiveExecutionContext
    requested_mode: str
    pool_active: bool | None
    spa_active: bool | None
    pool_activity_fresh: bool
    spa_activity_fresh: bool
    pool_activity_usable: bool
    spa_activity_usable: bool
    pump_rpm: int | None
    pump_observation_fresh: bool
    pump_observation_usable: bool
    configured_pump_speed_rpm: int | None
    configured_pump_speed_observation_fresh: bool
    configured_pump_speed_observation_usable: bool
    effective_heat_source: PhysicalHeatMode | None
    heat_source_observation_fresh: bool
    heat_source_observation_usable: bool
    external_changes: ExternalChangeBatch = ExternalChangeBatch(())
    shared_hydraulic_circuits: tuple[SharedHydraulicCircuitEvidence, ...] = ()
    shared_hydraulic_inventory_complete: bool = False
    heat_source_observed_at: datetime | None = None
    pool_activity_observed_at: datetime | None = None
    spa_activity_observed_at: datetime | None = None
    pump_observed_at: datetime | None = None
    configured_pump_speed_observed_at: datetime | None = None
    pump_session_id: str | None = None
    pump_session_purpose: PumpSpeedSessionPurpose | None = None
    pump_session_pump_circuit_id: str | None = None
    pump_session_effective_rpm: int | None = None
    pump_session_override_state: PumpSpeedOverrideState = PumpSpeedOverrideState.NONE

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        if not self.requested_mode.strip():
            raise ValueError("requested_mode must not be empty")
        for name in ("pool_active", "spa_active"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be boolean or None")
        for name in ("pump_rpm", "configured_pump_speed_rpm"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.effective_heat_source is not None:
            object.__setattr__(
                self,
                "effective_heat_source",
                PhysicalHeatMode(self.effective_heat_source),
            )
        for name in (
            "heat_source_observed_at",
            "pool_activity_observed_at",
            "spa_activity_observed_at",
            "pump_observed_at",
            "configured_pump_speed_observed_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        circuits = tuple(self.shared_hydraulic_circuits)
        concepts = tuple(item.concept for item in circuits)
        if len(concepts) != len(set(concepts)):
            raise ValueError("shared hydraulic concepts must be unique")
        object.__setattr__(self, "shared_hydraulic_circuits", circuits)


@dataclass(frozen=True, slots=True)
class ThermalRuntimeHandoffRequest:
    """Explicit request to transfer one valid lease to a current successor."""

    explicit: bool
    predecessor_lease_id: str
    predecessor_generation: int
    successor_context: ThermalLiveExecutionContext
    successor_execution_plan_id: str
    successor_body: ThermalBody
    successor_requested_mode: str
    successor_requires_body_active: bool
    successor_required_pump_rpm: int | None
    successor_heat_source: PhysicalHeatMode | None
    successor_progress: ThermalExecutionProgress | None = None
    replace_pump_setpoint: bool = False
    replace_heat_source: bool = False

    def __post_init__(self) -> None:
        if not self.predecessor_lease_id.strip():
            raise ValueError("predecessor_lease_id must not be empty")
        if self.predecessor_generation < 1:
            raise ValueError("predecessor_generation must be positive")
        if not self.successor_execution_plan_id.strip():
            raise ValueError("successor_execution_plan_id must not be empty")
        if not self.successor_requested_mode.strip():
            raise ValueError("successor_requested_mode must not be empty")
        if self.successor_required_pump_rpm is not None:
            if (
                isinstance(self.successor_required_pump_rpm, bool)
                or self.successor_required_pump_rpm <= 0
            ):
                raise ValueError("successor pump RPM must be positive or None")
        object.__setattr__(self, "successor_body", ThermalBody(self.successor_body))
        if self.successor_heat_source is not None:
            object.__setattr__(
                self,
                "successor_heat_source",
                PhysicalHeatMode(self.successor_heat_source),
            )


@dataclass(slots=True)
class ThermalRuntimeOwnershipManager:
    """Maintain one bounded in-memory lease without any command capability."""

    pump_rpm_tolerance: int = 25
    _state: ThermalRuntimeOwnershipState = field(
        default_factory=ThermalRuntimeOwnershipState,
        init=False,
        repr=False,
    )
    _residual_termination: ThermalResidualTerminationEntitlement | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_terminal_transition: ThermalRuntimeOwnershipTransitionDiagnostic | None = (
        field(default=None, init=False, repr=False)
    )

    def __post_init__(self) -> None:
        if self.pump_rpm_tolerance < 0:
            raise ValueError("pump_rpm_tolerance must not be negative")

    @property
    def state(self) -> ThermalRuntimeOwnershipState:
        return self._state

    @property
    def residual_termination(self) -> ThermalResidualTerminationEntitlement | None:
        """Return current in-memory termination proof, never normal authority."""

        return self._residual_termination

    @property
    def last_terminal_transition(
        self,
    ) -> ThermalRuntimeOwnershipTransitionDiagnostic | None:
        """Return bounded diagnostics for the latest terminal transition."""

        return self._last_terminal_transition

    def establish(
        self,
        ownership: ThermalLiveExecutionOwnership,
        *,
        established_at: datetime,
        requested_mode: str,
        current_context: ThermalLiveExecutionContext,
        execution_progress: ThermalExecutionProgress | None = None,
    ) -> ThermalRuntimeOwnershipDecision:
        """Establish a lease only from complete accepted delivery provenance."""

        _require_aware(established_at, "established_at")
        if not requested_mode.strip():
            raise ValueError("requested_mode must not be empty")
        previous = self._state.status
        current = self._state.lease
        if (
            ownership.evaluation_id != current_context.evaluation_id
            or ownership.thermal_plan_id != current_context.plan_id
        ):
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:provenance_not_current",
                previous,
                established_at,
            )
        originating_currentness = current_context.execution_currentness
        if (originating_currentness is None) != (execution_progress is None):
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:"
                "execution_currentness_progress_incomplete",
                previous,
                established_at,
            )
        if current is not None and current.status is ThermalRuntimeOwnershipStatus.OWNED:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:already_owned",
                previous,
                established_at,
            )
        if current is not None and current.execution_plan_id == ownership.execution_plan_id:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:provenance_reused",
                previous,
                established_at,
            )
        try:
            activation = _activation_provenance(ownership)
            pump = _pump_provenance(ownership)
            source = _source_provenance(ownership)
        except ValueError:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:provenance_incomplete",
                previous,
                established_at,
            )
        if activation is None and pump is None and source is None:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_establishment_denied:no_accepted_provenance",
                previous,
                established_at,
            )
        generation = 1 if current is None else current.generation + 1
        lease = ThermalRuntimeOwnershipLease(
            lease_id=_lease_id(
                generation=generation,
                body=ownership.target_body,
                evaluation_id=ownership.evaluation_id,
                plan_id=ownership.thermal_plan_id,
                execution_plan_id=ownership.execution_plan_id,
                predecessor_lease_id=None,
            ),
            generation=generation,
            body=ownership.target_body,
            evaluation_id=ownership.evaluation_id,
            thermal_plan_id=ownership.thermal_plan_id,
            execution_plan_id=ownership.execution_plan_id,
            requested_mode=requested_mode,
            established_at=established_at,
            last_confirmed_at=established_at,
            status=ThermalRuntimeOwnershipStatus.OWNED,
            reason_code="runtime_ownership_established:accepted_delivery",
            body_activation=activation,
            pump_setpoint=pump,
            heat_source=source,
            originating_currentness=originating_currentness,
            execution_progress=execution_progress,
            # Accepted provenance is provisional. Only a later exact native
            # consequence may add a verified concept.
            verified_concepts=(),
            body_activation_accepted_at=(
                _accepted_boundary(
                    established_at,
                    ownership.body_activation_accepted_at,
                )
                if activation is not None
                else None
            ),
            pump_setpoint_accepted_at=(
                _accepted_boundary(established_at, ownership.pump_accepted_at)
                if pump is not None
                else None
            ),
            heat_source_accepted_at=(
                _accepted_boundary(
                    established_at,
                    ownership.heat_source_accepted_at,
                )
                if source is not None
                else None
            ),
        )
        # A new positively-proven session generation makes every older cleanup
        # token stale. Hardware equality never recreates the discarded proof.
        self._residual_termination = None
        self._state = ThermalRuntimeOwnershipState(
            status=lease.status,
            lease=lease,
            reason_code=lease.reason_code,
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.ESTABLISHED,
            lease.reason_code,
            previous,
            established_at,
        )

    def evaluate(
        self,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipDecision:
        """Confirm or terminally preempt the current lease from fresh evidence."""

        previous = self._state.status
        lease = self._state.lease
        if lease is None:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP,
                "runtime_ownership_unowned",
                previous,
                evidence.evaluated_at,
            )
        if lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_terminal",
                previous,
                evidence.evaluated_at,
            )
        lease = self._confirm_accepted_consequence(lease, evidence)
        override_transition = _pump_session_override_transition(lease, evidence)
        if override_transition is PumpSpeedOverrideState.PENDING:
            reason = self._continuation_failure_reason(
                lease,
                evidence,
                check_identity=False,
                check_pump=False,
            )
            if reason is not None:
                return self._terminate(
                    lease,
                    reason=reason,
                    at=evidence.evaluated_at,
                    evidence=evidence,
                )
            retained = replace(
                lease,
                last_confirmed_at=evidence.evaluated_at,
                reason_code="runtime_ownership_retained:pump_override_pending",
            )
            self._state = ThermalRuntimeOwnershipState(
                status=retained.status,
                lease=retained,
                reason_code=retained.reason_code,
            )
            return self._decision(
                ThermalRuntimeOwnershipDisposition.RETAINED,
                retained.reason_code,
                previous,
                evidence.evaluated_at,
            )
        if override_transition is PumpSpeedOverrideState.VERIFIED:
            currentness = evidence.current_context.execution_currentness
            assert currentness is not None
            lease = replace(
                lease,
                evaluation_id=currentness.evaluation_id,
                thermal_plan_id=currentness.plan_id,
                originating_currentness=currentness,
                execution_progress=ThermalExecutionProgress(),
                pump_setpoint=None,
                pump_setpoint_accepted_at=None,
                pump_session_id=evidence.pump_session_id,
                pump_session_effective_rpm=evidence.pump_session_effective_rpm,
                verified_concepts=tuple(
                    concept
                    for concept in lease.verified_concepts
                    if concept is not ThermalRuntimeOwnedConcept.PUMP_SETPOINT
                ),
                last_confirmed_at=evidence.evaluated_at,
                reason_code="runtime_ownership_retained:pump_override_verified",
            )
            self._state = ThermalRuntimeOwnershipState(
                status=lease.status,
                lease=lease,
                reason_code=lease.reason_code,
            )
        reason = self._continuation_failure_reason(lease, evidence)
        if reason is not None:
            return self._terminate(
                lease,
                reason=reason,
                at=evidence.evaluated_at,
                evidence=evidence,
            )
        retained = replace(
            lease,
            last_confirmed_at=evidence.evaluated_at,
            reason_code="runtime_ownership_retained:current_evidence_confirmed",
        )
        self._state = ThermalRuntimeOwnershipState(
            status=retained.status,
            lease=retained,
            reason_code=retained.reason_code,
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.RETAINED,
            retained.reason_code,
            previous,
            evidence.evaluated_at,
        )

    def _confirm_accepted_consequence(
        self,
        lease: ThermalRuntimeOwnershipLease,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipLease:
        """Record exact post-acceptance native proof before currentness changes."""

        progress = lease.execution_progress
        accepted = None if progress is None else progress.accepted_current
        if accepted is None or progress is None or progress.accepted_operation_id is None:
            return lease
        concept: ThermalRuntimeOwnedConcept | None = None
        proven = False
        if accepted.role == "body_activation":
            active = (
                evidence.pool_active
                if lease.body is ThermalBody.POOL
                else evidence.spa_active
            )
            fresh = (
                evidence.pool_activity_fresh
                if lease.body is ThermalBody.POOL
                else evidence.spa_activity_fresh
            )
            usable = (
                evidence.pool_activity_usable
                if lease.body is ThermalBody.POOL
                else evidence.spa_activity_usable
            )
            observed_at = (
                evidence.pool_activity_observed_at
                if lease.body is ThermalBody.POOL
                else evidence.spa_activity_observed_at
            )
            accepted_at = lease.body_activation_accepted_at
            concept = ThermalRuntimeOwnedConcept.BODY_ACTIVATION
            proven = (
                lease.body_activation is not None
                and progress.accepted_operation_id
                == lease.body_activation.operation_id
                and active is True
                and fresh
                and usable
                and observed_at is not None
                and accepted_at is not None
                and observed_at > accepted_at
            )
        elif accepted.role in {
            "priming",
            "pool_temperature_probe",
            "thermal_pump_target",
        }:
            concept = ThermalRuntimeOwnedConcept.PUMP_SETPOINT
            expected = lease.pump_setpoint
            intended = None if expected is None else expected.intended_value
            accepted_at = lease.pump_setpoint_accepted_at
            assert intended is None or isinstance(intended, int)
            proven = (
                intended is not None
                and expected is not None
                and progress.accepted_operation_id == expected.operation_id
                and accepted_at is not None
                and evidence.configured_pump_speed_rpm is not None
                and evidence.pump_rpm is not None
                and evidence.configured_pump_speed_observation_fresh
                and evidence.configured_pump_speed_observation_usable
                and evidence.pump_observation_fresh
                and evidence.pump_observation_usable
                and evidence.configured_pump_speed_observed_at is not None
                and evidence.pump_observed_at is not None
                and evidence.configured_pump_speed_observed_at
                > accepted_at
                and evidence.pump_observed_at > accepted_at
                and evidence.configured_pump_speed_rpm == intended
                and abs(evidence.pump_rpm - intended) <= self.pump_rpm_tolerance
            )
        elif accepted.role == "heat_source":
            concept = ThermalRuntimeOwnedConcept.HEAT_SOURCE
            expected = lease.heat_source
            accepted_at = lease.heat_source_accepted_at
            proven = (
                expected is not None
                and progress.accepted_operation_id == expected.operation_id
                and accepted_at is not None
                and evidence.effective_heat_source is expected.intended_value
                and evidence.heat_source_observation_fresh
                and evidence.heat_source_observation_usable
                and evidence.heat_source_observed_at is not None
                and evidence.heat_source_observed_at > accepted_at
            )
        if not proven or concept is None or concept in lease.verified_concepts:
            return lease
        confirmed_progress = ThermalExecutionProgress(
            verified_prefix=(*progress.verified_prefix, accepted),
        )
        confirmed = replace(
            lease,
            verified_concepts=(*lease.verified_concepts, concept),
            execution_progress=confirmed_progress,
        )
        self._state = ThermalRuntimeOwnershipState(
            status=confirmed.status,
            lease=confirmed,
            reason_code=confirmed.reason_code,
        )
        return confirmed

    def current_external_preemption_reason(
        self,
        batch: ExternalChangeBatch,
    ) -> str | None:
        """Assess current-lease external takeover without mutating ownership."""

        lease = self._state.lease
        if lease is None or lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return None
        return _external_preemption_reason(
            lease,
            batch,
            pump_rpm_tolerance=self.pump_rpm_tolerance,
        )

    def promote_session_provenance(
        self,
        ownership: ThermalLiveExecutionOwnership,
        *,
        promoted_at: datetime,
        requested_mode: str,
        originating_context: ThermalLiveExecutionContext,
        execution_progress: ThermalExecutionProgress,
    ) -> ThermalRuntimeOwnershipDecision:
        """Promote new accepted provenance from the same active live session.

        The first accepted operation establishes the lease.  Later accepted
        operations may update only that exact session's concept provenance.
        Observed hardware state is never an input to this transition.
        """

        _require_aware(promoted_at, "promoted_at")
        lease = self._state.lease
        if lease is None:
            return self.establish(
                ownership,
                established_at=promoted_at,
                requested_mode=requested_mode,
                current_context=originating_context,
                execution_progress=execution_progress,
            )
        if (
            lease.status
            in {
                ThermalRuntimeOwnershipStatus.SUPERSEDED,
                ThermalRuntimeOwnershipStatus.RELINQUISHED,
            }
            and self._residual_termination is None
        ):
            # The terminal lease is historical after its exact residual token
            # has been explicitly consumed. A fresh accepted operation may
            # establish a new generation, but no prior concept provenance is
            # copied into it.
            return self.establish(
                ownership,
                established_at=promoted_at,
                requested_mode=requested_mode,
                current_context=originating_context,
                execution_progress=execution_progress,
            )
        previous = self._state.status
        if lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_promotion_denied:ownership_terminal",
                previous,
                promoted_at,
            )
        if (
            lease.execution_plan_id != ownership.execution_plan_id
            or lease.body is not ownership.target_body
            or lease.evaluation_id != ownership.evaluation_id
            or lease.thermal_plan_id != ownership.thermal_plan_id
        ):
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_promotion_denied:session_provenance_mismatch",
                previous,
                promoted_at,
            )
        if (
            originating_context.evaluation_id != lease.evaluation_id
            or originating_context.plan_id != lease.thermal_plan_id
            or originating_context.execution_currentness
            != lease.originating_currentness
        ):
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_promotion_denied:originating_context_mismatch",
                previous,
                promoted_at,
            )
        try:
            activation = _activation_provenance(ownership)
            pump = _pump_provenance(ownership)
            source = _source_provenance(ownership)
        except ValueError:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_promotion_denied:provenance_incomplete",
                previous,
                promoted_at,
            )
        promoted = replace(
            lease,
            last_confirmed_at=promoted_at,
            reason_code="runtime_ownership_promoted:accepted_session_delivery",
            body_activation=activation or lease.body_activation,
            pump_setpoint=pump or lease.pump_setpoint,
            pump_session_id=(None if pump is not None else lease.pump_session_id),
            pump_session_effective_rpm=(
                None if pump is not None else lease.pump_session_effective_rpm
            ),
            heat_source=source or lease.heat_source,
            execution_progress=execution_progress,
            verified_concepts=_promoted_verified_concepts(
                lease,
                activation=activation,
                pump=pump,
                source=source,
            ),
            body_activation_accepted_at=_promoted_accepted_at(
                activation,
                previous=lease.body_activation,
                previous_accepted_at=lease.body_activation_accepted_at,
                promoted_at=_accepted_boundary(
                    promoted_at,
                    ownership.body_activation_accepted_at,
                ),
            ),
            pump_setpoint_accepted_at=_promoted_accepted_at(
                pump,
                previous=lease.pump_setpoint,
                previous_accepted_at=lease.pump_setpoint_accepted_at,
                promoted_at=_accepted_boundary(
                    promoted_at,
                    ownership.pump_accepted_at,
                ),
            ),
            heat_source_accepted_at=_promoted_accepted_at(
                source,
                previous=lease.heat_source,
                previous_accepted_at=lease.heat_source_accepted_at,
                promoted_at=_accepted_boundary(
                    promoted_at,
                    ownership.heat_source_accepted_at,
                ),
            ),
        )
        self._state = ThermalRuntimeOwnershipState(
            status=promoted.status,
            lease=promoted,
            reason_code=promoted.reason_code,
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.RETAINED,
            promoted.reason_code,
            previous,
            promoted_at,
        )

    def handoff(
        self,
        request: ThermalRuntimeHandoffRequest,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipDecision:
        """Explicitly transfer a valid lease to one compatible current successor."""

        previous = self._state.status
        lease = self._state.lease
        denial = self._handoff_denial_reason(lease, request, evidence)
        if denial is not None:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                denial,
                previous,
                evidence.evaluated_at,
            )
        assert lease is not None
        generation = lease.generation + 1
        successor = replace(
            lease,
            lease_id=_lease_id(
                generation=generation,
                body=request.successor_body,
                evaluation_id=request.successor_context.evaluation_id,
                plan_id=request.successor_context.plan_id,
                execution_plan_id=request.successor_execution_plan_id,
                predecessor_lease_id=lease.lease_id,
            ),
            generation=generation,
            evaluation_id=request.successor_context.evaluation_id,
            thermal_plan_id=request.successor_context.plan_id,
            execution_plan_id=request.successor_execution_plan_id,
            requested_mode=request.successor_requested_mode,
            established_at=evidence.evaluated_at,
            last_confirmed_at=evidence.evaluated_at,
            reason_code="runtime_ownership_handed_off:compatible_successor",
            predecessor_lease_id=lease.lease_id,
            ended_at=None,
            originating_currentness=request.successor_context.execution_currentness,
            execution_progress=request.successor_progress,
            pump_setpoint=(
                None if request.replace_pump_setpoint else lease.pump_setpoint
            ),
            pump_session_id=None,
            pump_session_effective_rpm=None,
            heat_source=(
                None if request.replace_heat_source else lease.heat_source
            ),
            pump_setpoint_accepted_at=(
                None
                if request.replace_pump_setpoint
                else lease.pump_setpoint_accepted_at
            ),
            heat_source_accepted_at=(
                None
                if request.replace_heat_source
                else lease.heat_source_accepted_at
            ),
            verified_concepts=tuple(
                concept
                for concept in lease.verified_concepts
                if not (
                    concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT
                    and request.replace_pump_setpoint
                )
                and not (
                    concept is ThermalRuntimeOwnedConcept.HEAT_SOURCE
                    and request.replace_heat_source
                )
            ),
        )
        self._state = ThermalRuntimeOwnershipState(
            status=successor.status,
            lease=successor,
            reason_code=successor.reason_code,
        )
        self._residual_termination = None
        return self._decision(
            ThermalRuntimeOwnershipDisposition.HANDED_OFF,
            successor.reason_code,
            previous,
            evidence.evaluated_at,
        )

    def evaluate_pending_successor(
        self,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipDecision:
        """Retain a predecessor only while an explicit successor may be handed off.

        This does not transfer ownership or adopt successor state.  It applies
        the normal hydraulic/external checks while deliberately deferring only
        immutable plan identity to the driver's explicit typed handoff.
        """

        previous = self._state.status
        lease = self._state.lease
        if lease is None or lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.NO_OWNERSHIP,
                "runtime_ownership_successor_pending:no_current_owner",
                previous,
                evidence.evaluated_at,
            )
        failure = self._continuation_failure_reason(
            lease,
            evidence,
            check_identity=False,
            check_requested_mode=True,
        )
        if failure is not None:
            return self._terminate(
                lease,
                reason=failure,
                at=evidence.evaluated_at,
                evidence=evidence,
            )
        retained = replace(
            lease,
            last_confirmed_at=evidence.evaluated_at,
            reason_code="runtime_ownership_retained:explicit_successor_pending",
        )
        self._state = ThermalRuntimeOwnershipState(
            status=retained.status,
            lease=retained,
            reason_code=retained.reason_code,
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.RETAINED,
            retained.reason_code,
            previous,
            evidence.evaluated_at,
        )

    def relinquish(
        self,
        *,
        lease_id: str,
        relinquished_at: datetime,
        reason_code: str,
        retain_termination_entitlement: bool = False,
    ) -> ThermalRuntimeOwnershipDecision:
        """Relinquish authority without issuing cleanup or restoration commands."""

        _require_aware(relinquished_at, "relinquished_at")
        previous = self._state.status
        lease = self._state.lease
        if (
            lease is None
            or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease.lease_id != lease_id
        ):
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_relinquishment_denied:not_current_owner",
                previous,
                relinquished_at,
            )
        if not reason_code.strip():
            raise ValueError("relinquishment reason_code must not be empty")
        reason = f"runtime_ownership_relinquished:{reason_code}"
        terminal = replace(
            lease,
            status=ThermalRuntimeOwnershipStatus.RELINQUISHED,
            reason_code=reason,
            ended_at=relinquished_at,
        )
        self._state = ThermalRuntimeOwnershipState(
            status=terminal.status,
            lease=terminal,
            reason_code=reason,
        )
        self._last_terminal_transition = _relinquishment_transition_diagnostic(
            lease,
            reason=reason,
            occurred_at=relinquished_at,
        )
        self._residual_termination = (
            _residual_entitlement(lease, at=relinquished_at, reason=reason)
            if retain_termination_entitlement
            else None
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.RELINQUISHED,
            reason,
            previous,
            relinquished_at,
        )

    def invalidate_residual_termination(self) -> None:
        """Discard residual proof without issuing or authorizing a command."""

        self._residual_termination = None

    def consume_residual_termination(
        self,
        *,
        entitlement_id: str,
    ) -> bool:
        """Relinquish all residual concepts after verified safe reduction."""

        current = self._residual_termination
        if current is None or current.entitlement_id != entitlement_id:
            return False
        self._residual_termination = None
        return True

    def _continuation_failure_reason(
        self,
        lease: ThermalRuntimeOwnershipLease,
        evidence: ThermalRuntimeOwnershipEvidence,
        *,
        check_identity: bool = True,
        check_requested_mode: bool = True,
        check_pump: bool = True,
    ) -> str | None:
        accepted_role = (
            None
            if lease.execution_progress is None
            or lease.execution_progress.accepted_current is None
            else lease.execution_progress.accepted_current.role
        )
        if evidence.evaluated_at < lease.last_confirmed_at:
            return "runtime_ownership_preempted:evidence_temporal_regression"
        if check_identity:
            if lease.originating_currentness is not None:
                currentness = evidence.current_context.execution_currentness
                if currentness is None:
                    return (
                        "runtime_ownership_preempted:"
                        "execution_currentness_unavailable"
                    )
                assert lease.execution_progress is not None
                compatibility = assess_execution_compatibility(
                    lease.originating_currentness,
                    currentness,
                    progress=lease.execution_progress,
                )
                if (
                    compatibility.disposition
                    is ThermalExecutionCompatibilityDisposition.SUPERSEDED
                ):
                    return "runtime_ownership_superseded:execution_purpose"
                if not compatibility.continuation_allowed:
                    return (
                        "runtime_ownership_preempted:execution_currentness_unprovable:"
                        f"{compatibility.reason_code}"
                    )
            else:
                if evidence.current_context.evaluation_id != lease.evaluation_id:
                    return "runtime_ownership_superseded:evaluation_id"
                if evidence.current_context.plan_id != lease.thermal_plan_id:
                    return "runtime_ownership_superseded:plan_id"
        if check_requested_mode and evidence.requested_mode != lease.requested_mode:
            return "runtime_ownership_superseded:requested_mode"
        hydraulic = _hydraulic_failure_reason(
            lease.body,
            evidence,
            target_activation_pending=accepted_role == "body_activation",
        )
        if hydraulic is not None:
            return hydraulic
        shared = _shared_hydraulic_failure_reason(evidence)
        if shared is not None:
            return shared
        pump_consequence_pending = accepted_role in {
            "priming",
            "pool_temperature_probe",
            "thermal_pump_target",
        }
        if check_pump and lease.pump_setpoint is not None and not pump_consequence_pending:
            if evidence.configured_pump_speed_rpm is None:
                return "runtime_ownership_preempted:pump_setpoint_evidence_missing"
            if not evidence.configured_pump_speed_observation_fresh:
                return "runtime_ownership_preempted:pump_setpoint_evidence_stale"
            if not evidence.configured_pump_speed_observation_usable:
                return "runtime_ownership_preempted:pump_setpoint_evidence_unusable"
            if evidence.pump_rpm is None:
                return "runtime_ownership_preempted:pump_evidence_missing"
            if not evidence.pump_observation_fresh:
                return "runtime_ownership_preempted:pump_evidence_stale"
            if not evidence.pump_observation_usable:
                return "runtime_ownership_preempted:pump_evidence_unusable"
            expected_rpm = lease.pump_setpoint.intended_value
            assert isinstance(expected_rpm, int) and not isinstance(expected_rpm, bool)
            if (
                abs(evidence.configured_pump_speed_rpm - expected_rpm)
                > self.pump_rpm_tolerance
            ):
                return "runtime_ownership_preempted:pump_setpoint_external_change"
            if abs(evidence.pump_rpm - expected_rpm) > self.pump_rpm_tolerance:
                return "runtime_ownership_preempted:pump_external_change"
        if lease.heat_source is not None and accepted_role != "heat_source":
            if evidence.effective_heat_source is None:
                return "runtime_ownership_preempted:source_evidence_missing"
            if not evidence.heat_source_observation_fresh:
                return "runtime_ownership_preempted:source_evidence_stale"
            if not evidence.heat_source_observation_usable:
                return "runtime_ownership_preempted:source_evidence_unusable"
            if evidence.effective_heat_source is not lease.heat_source.intended_value:
                return "runtime_ownership_preempted:source_external_change"
        external = _external_preemption_reason(
            lease,
            evidence.external_changes,
            pump_rpm_tolerance=self.pump_rpm_tolerance,
        )
        if external is not None:
            return external
        return None

    def _handoff_denial_reason(
        self,
        lease: ThermalRuntimeOwnershipLease | None,
        request: ThermalRuntimeHandoffRequest,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> str | None:
        prefix = "runtime_ownership_handoff_denied:"
        if not request.explicit:
            return prefix + "not_explicit"
        if lease is None or lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return prefix + "predecessor_not_owned"
        if (
            request.predecessor_lease_id != lease.lease_id
            or request.predecessor_generation != lease.generation
        ):
            return prefix + "predecessor_provenance_mismatch"
        if request.successor_body is not lease.body:
            return prefix + "cross_body"
        if (
            evidence.current_context.evaluation_id
            != request.successor_context.evaluation_id
        ):
            return prefix + "successor_evaluation_not_current"
        if evidence.current_context.plan_id != request.successor_context.plan_id:
            return prefix + "successor_plan_not_current"
        if evidence.requested_mode != request.successor_requested_mode:
            return prefix + "successor_requested_mode_not_current"
        if (
            request.successor_context.execution_currentness is None
        ) != (request.successor_progress is None):
            return prefix + "successor_currentness_progress_incomplete"
        continuation = self._continuation_failure_reason(
            lease,
            evidence,
            check_identity=False,
            check_requested_mode=False,
        )
        if continuation is not None:
            return prefix + "predecessor_" + continuation.rsplit(":", 1)[-1]
        if lease.body_activation is not None and not request.successor_requires_body_active:
            return prefix + "body_activation_incompatible"
        if lease.pump_setpoint is not None:
            if (
                request.successor_required_pump_rpm
                != lease.pump_setpoint.intended_value
                and not request.replace_pump_setpoint
            ):
                return prefix + "pump_incompatible"
        if lease.heat_source is not None:
            if (
                request.successor_heat_source is not lease.heat_source.intended_value
                and not request.replace_heat_source
            ):
                return prefix + "source_incompatible"
        if request.replace_pump_setpoint or request.replace_heat_source:
            predecessor = lease.originating_currentness
            successor = request.successor_context.execution_currentness
            if (
                predecessor is None
                or successor is None
                or predecessor.purpose.kind
                is not ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
                or successor.purpose.kind
                is not ThermalExecutionPurposeKind.THERMAL_CONTROL
                or lease.body is not ThermalBody.POOL
                or request.successor_body is not ThermalBody.POOL
                or predecessor.purpose.requested_mode
                != successor.purpose.requested_mode
                or not request.successor_requires_body_active
            ):
                return prefix + "replacement_not_probe_successor"
        return None

    def _terminate(
        self,
        lease: ThermalRuntimeOwnershipLease,
        *,
        reason: str,
        at: datetime,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipDecision:
        superseded = reason.startswith("runtime_ownership_superseded:")
        status = (
            ThermalRuntimeOwnershipStatus.SUPERSEDED
            if superseded
            else ThermalRuntimeOwnershipStatus.PREEMPTED
        )
        disposition = (
            ThermalRuntimeOwnershipDisposition.SUPERSEDED
            if superseded
            else ThermalRuntimeOwnershipDisposition.PREEMPTED
        )
        terminal = replace(
            lease,
            status=status,
            reason_code=reason,
            ended_at=at,
        )
        previous = self._state.status
        self._state = ThermalRuntimeOwnershipState(
            status=status,
            lease=terminal,
            reason_code=reason,
        )
        self._last_terminal_transition = _terminal_transition_diagnostic(
            lease,
            evidence,
            status=status,
            reason=reason,
            occurred_at=at,
        )
        if _body_origin_invalidated_by_evidence(lease, evidence):
            self._residual_termination = None
        elif superseded:
            self._residual_termination = _residual_entitlement(
                lease,
                at=at,
                reason=reason,
                include_body=_body_origin_continuity_proven(lease, evidence),
            )
        elif not _body_origin_continuity_proven(lease, evidence):
            self._residual_termination = None
        else:
            self._residual_termination = _preempted_body_entitlement(
                lease,
                evidence,
                at=at,
                reason=reason,
            )
        return self._decision(disposition, reason, previous, at)

    def _decision(
        self,
        disposition: ThermalRuntimeOwnershipDisposition,
        reason: str,
        previous: ThermalRuntimeOwnershipStatus,
        at: datetime,
    ) -> ThermalRuntimeOwnershipDecision:
        return ThermalRuntimeOwnershipDecision(
            disposition=disposition,
            reason_code=reason,
            previous_status=previous,
            current_state=self._state,
            evaluated_at=at,
        )


def _activation_provenance(
    ownership: ThermalLiveExecutionOwnership,
) -> ThermalRuntimeConceptProvenance | None:
    values = (
        ownership.body_activation_operation_id,
        ownership.body_activation_receipt_id,
        ownership.body_activation_correlation_id,
    )
    if not any(values):
        return None
    if not all(values):
        raise ValueError("body activation provenance must be complete")
    operation_id, receipt_id, correlation_id = values
    assert operation_id is not None and receipt_id is not None and correlation_id is not None
    return ThermalRuntimeConceptProvenance(
        concept=ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        operation_id=operation_id,
        receipt_id=receipt_id,
        correlation_id=correlation_id,
        intended_value=True,
    )


def _pump_provenance(
    ownership: ThermalLiveExecutionOwnership,
) -> ThermalRuntimeConceptProvenance | None:
    values = (
        ownership.pump_operation_id,
        ownership.pump_receipt_id,
        ownership.pump_correlation_id,
    )
    if not any(values) and ownership.commanded_pump_rpm is None:
        return None
    if not all(values) or ownership.commanded_pump_rpm is None:
        raise ValueError("pump setpoint provenance must be complete")
    operation_id, receipt_id, correlation_id = values
    assert operation_id is not None and receipt_id is not None and correlation_id is not None
    return ThermalRuntimeConceptProvenance(
        concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        operation_id=operation_id,
        receipt_id=receipt_id,
        correlation_id=correlation_id,
        intended_value=ownership.commanded_pump_rpm,
    )


def _source_provenance(
    ownership: ThermalLiveExecutionOwnership,
) -> ThermalRuntimeConceptProvenance | None:
    values = (
        ownership.heat_source_operation_id,
        ownership.heat_source_receipt_id,
        ownership.heat_source_correlation_id,
    )
    if not any(values) and ownership.commanded_heat_source is None:
        return None
    if not all(values) or ownership.commanded_heat_source is None:
        raise ValueError("heat-source provenance must be complete")
    operation_id, receipt_id, correlation_id = values
    assert operation_id is not None and receipt_id is not None and correlation_id is not None
    return ThermalRuntimeConceptProvenance(
        concept=ThermalRuntimeOwnedConcept.HEAT_SOURCE,
        operation_id=operation_id,
        receipt_id=receipt_id,
        correlation_id=correlation_id,
        intended_value=ownership.commanded_heat_source,
    )


def _hydraulic_failure_reason(
    body: ThermalBody,
    evidence: ThermalRuntimeOwnershipEvidence,
    *,
    target_activation_pending: bool = False,
) -> str | None:
    for prefix, value, fresh, usable in (
        (
            "pool",
            evidence.pool_active,
            evidence.pool_activity_fresh,
            evidence.pool_activity_usable,
        ),
        (
            "spa",
            evidence.spa_active,
            evidence.spa_activity_fresh,
            evidence.spa_activity_usable,
        ),
    ):
        if value is None:
            return f"runtime_ownership_preempted:{prefix}_activity_missing"
        if not fresh:
            return f"runtime_ownership_preempted:{prefix}_activity_stale"
        if not usable:
            return f"runtime_ownership_preempted:{prefix}_activity_unusable"
    if evidence.pool_active is True and evidence.spa_active is True:
        return "runtime_ownership_preempted:body_topology_contradictory"
    if body is ThermalBody.POOL:
        if evidence.spa_active is True:
            return "runtime_ownership_preempted:spa_takeover"
        if evidence.pool_active is not True and not target_activation_pending:
            return "runtime_ownership_preempted:pool_inactive"
    else:
        if evidence.pool_active is True:
            return "runtime_ownership_preempted:pool_takeover"
        if evidence.spa_active is not True and not target_activation_pending:
            return "runtime_ownership_preempted:hot_tub_inactive"
    return None


def _shared_hydraulic_failure_reason(
    evidence: ThermalRuntimeOwnershipEvidence,
) -> str | None:
    if not evidence.shared_hydraulic_inventory_complete:
        return "runtime_ownership_preempted:shared_hydraulic_evidence_incomplete"
    for item in evidence.shared_hydraulic_circuits:
        if item.active is None or not item.fresh or not item.usable:
            return (
                "runtime_ownership_preempted:shared_hydraulic_evidence_unusable:"
                f"{item.concept}"
            )
        if not item.active:
            continue
        if item.safety_class is SharedHydraulicSafetyClass.UNKNOWN:
            return (
                "runtime_ownership_preempted:shared_hydraulic_ambiguous:"
                f"{item.concept}"
            )
        if item.safety_class is SharedHydraulicSafetyClass.CONFLICTING:
            return (
                "runtime_ownership_preempted:shared_hydraulic_conflict:"
                f"{item.concept}"
            )
    return None


def _external_preemption_reason(
    lease: ThermalRuntimeOwnershipLease,
    batch: ExternalChangeBatch,
    *,
    pump_rpm_tolerance: int,
) -> str | None:
    target_prefix = "pool" if lease.body is ThermalBody.POOL else "spa"
    target_body_concept = f"{target_prefix}.active"
    for event in batch.events:
        # An event predating this lease belongs to an earlier ownership epoch.
        # Equality remains fail-closed because ordering within one timestamp
        # cannot prove that the event preceded accepted lease establishment.
        if event.observed_at < lease.established_at:
            continue
        if lease.body_activation is not None and event.concept == target_body_concept:
            return "runtime_ownership_preempted:body_external_change"
        if (
            lease.pump_setpoint is not None
            and event.concept == "pump.rpm"
            and event.reconciliation_required
        ):
            if not pump_event_conflicts_with_provenance(
                event,
                intended_rpm=lease.pump_setpoint.intended_value,
                provenance_verified=(
                    ThermalRuntimeOwnedConcept.PUMP_SETPOINT
                    in lease.verified_concepts
                ),
                accepted_at=lease.pump_setpoint_accepted_at,
                tolerance=pump_rpm_tolerance,
            ):
                continue

            return "runtime_ownership_preempted:pump_external_change"
        if (
            lease.heat_source is not None
            and event.concept == f"{target_prefix}.raw_heater_id"
            and event.reconciliation_required
        ):
            return "runtime_ownership_preempted:source_external_change"
    return None


def _pump_session_override_transition(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
) -> PumpSpeedOverrideState | None:
    """Prove one same-purpose RPM override without granting pump ownership."""

    state = evidence.pump_session_override_state
    if state is PumpSpeedOverrideState.NONE and lease.pump_setpoint is not None:
        return None
    if not isinstance(state, PumpSpeedOverrideState):
        return None
    original = lease.originating_currentness
    current = evidence.current_context.execution_currentness
    if (
        original is None
        or current is None
        or evidence.pump_session_id is None
        or evidence.pump_session_pump_circuit_id is None
        or type(evidence.pump_session_effective_rpm) is not int
        or evidence.pump_session_effective_rpm < 1
    ):
        return None
    if (
        lease.pump_session_id is not None
        and evidence.pump_session_id != lease.pump_session_id
    ):
        return None
    before = original.purpose
    after = current.purpose
    expected_purpose = {
        PhysicalHeatMode.OFF: PumpSpeedSessionPurpose.ORDINARY,
        PhysicalHeatMode.SOLAR: PumpSpeedSessionPurpose.SOLAR,
        PhysicalHeatMode.GAS: PumpSpeedSessionPurpose.GAS,
    }.get(after.selected_source)
    if (
        evidence.pump_session_purpose is not expected_purpose
        or before.body is not after.body
        or before.body is not lease.body
        or before.requested_mode != after.requested_mode
        or before.selected_source is not after.selected_source
        or before.target_temperature_f != after.target_temperature_f
        or before.kind is not after.kind
        or before.required_pump_rpm == after.required_pump_rpm
        or after.required_pump_rpm != evidence.pump_session_effective_rpm
    ):
        return None
    pump_ids = {
        operation.equipment_id
        for operation in original.residual_plan.operations
        if operation.operation_type == "SetPumpSpeed"
    }
    if pump_ids and pump_ids != {evidence.pump_session_pump_circuit_id}:
        return None
    if state is PumpSpeedOverrideState.VERIFIED and (
        evidence.configured_pump_speed_rpm != evidence.pump_session_effective_rpm
        or not evidence.configured_pump_speed_observation_fresh
        or not evidence.configured_pump_speed_observation_usable
    ):
        return None
    if state is PumpSpeedOverrideState.NONE:
        if (
            not evidence.configured_pump_speed_observation_fresh
            or not evidence.configured_pump_speed_observation_usable
        ):
            return None
        if evidence.configured_pump_speed_rpm == after.required_pump_rpm:
            return PumpSpeedOverrideState.VERIFIED
        if evidence.configured_pump_speed_rpm == before.required_pump_rpm:
            return PumpSpeedOverrideState.PENDING
        return None
    return state


def _lease_id(
    *,
    generation: int,
    body: ThermalBody,
    evaluation_id: str,
    plan_id: str,
    execution_plan_id: str,
    predecessor_lease_id: str | None,
) -> str:
    payload = json.dumps(
        {
            "generation": generation,
            "body": body.value,
            "evaluation_id": evaluation_id,
            "plan_id": plan_id,
            "execution_plan_id": execution_plan_id,
            "predecessor_lease_id": predecessor_lease_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "thermal-runtime-ownership-" + sha256(payload.encode()).hexdigest()[:24]


def _residual_entitlement(
    lease: ThermalRuntimeOwnershipLease,
    *,
    at: datetime,
    reason: str,
    body_only: bool = False,
    include_body: bool = True,
) -> ThermalResidualTerminationEntitlement | None:
    body_activation = (
        _verified_provenance(
            lease,
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        )
        if include_body
        else None
    )
    pump_setpoint = (
        None
        if body_only
        else _verified_provenance(
            lease,
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        )
    )
    heat_source = (
        None
        if body_only
        else _verified_provenance(
            lease,
            ThermalRuntimeOwnedConcept.HEAT_SOURCE,
        )
    )
    if body_activation is None and pump_setpoint is None and heat_source is None:
        return None
    payload = json.dumps(
        {
            "lease_id": lease.lease_id,
            "generation": lease.generation,
            "execution_plan_id": lease.execution_plan_id,
            "retained_at": at.isoformat(),
            "reason": reason,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return ThermalResidualTerminationEntitlement(
        entitlement_id=(
            "thermal-residual-" + sha256(payload.encode()).hexdigest()[:24]
        ),
        lease_id=lease.lease_id,
        generation=lease.generation,
        body=lease.body,
        originating_execution_plan_id=lease.execution_plan_id,
        originating_lease_established_at=lease.established_at,
        retained_at=at,
        reason_code=reason,
        body_activation=body_activation,
        pump_setpoint=pump_setpoint,
        heat_source=heat_source,
        pump_setpoint_accepted_at=(
            lease.pump_setpoint_accepted_at if pump_setpoint is not None else None
        ),
    )


def _preempted_body_entitlement(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
    *,
    at: datetime,
    reason: str,
) -> ThermalResidualTerminationEntitlement | None:
    if not _body_origin_continuity_proven(lease, evidence):
        return None
    return _residual_entitlement(
        lease,
        at=at,
        reason=reason,
        body_only=True,
    )


def _body_origin_invalidated_by_evidence(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
) -> bool:
    """Return whether current positive evidence ends the owned body epoch."""

    target_active = (
        evidence.pool_active
        if lease.body is ThermalBody.POOL
        else evidence.spa_active
    )
    target_fresh = (
        evidence.pool_activity_fresh
        if lease.body is ThermalBody.POOL
        else evidence.spa_activity_fresh
    )
    target_usable = (
        evidence.pool_activity_usable
        if lease.body is ThermalBody.POOL
        else evidence.spa_activity_usable
    )
    if target_active is False and target_fresh and target_usable:
        return True
    if (
        evidence.pool_active is True
        and evidence.spa_active is True
        and evidence.pool_activity_fresh
        and evidence.spa_activity_fresh
        and evidence.pool_activity_usable
        and evidence.spa_activity_usable
    ):
        return True
    other_active = (
        evidence.spa_active
        if lease.body is ThermalBody.POOL
        else evidence.pool_active
    )
    other_fresh = (
        evidence.spa_activity_fresh
        if lease.body is ThermalBody.POOL
        else evidence.pool_activity_fresh
    )
    other_usable = (
        evidence.spa_activity_usable
        if lease.body is ThermalBody.POOL
        else evidence.pool_activity_usable
    )
    if other_active is True and other_fresh and other_usable:
        return True
    if any(
        item.active is True
        and item.fresh
        and item.usable
        and item.safety_class is SharedHydraulicSafetyClass.CONFLICTING
        for item in evidence.shared_hydraulic_circuits
    ):
        return True
    target_concept = (
        "pool.active" if lease.body is ThermalBody.POOL else "spa.active"
    )
    return any(
        event.observed_at >= lease.established_at
        and event.concept == target_concept
        for event in evidence.external_changes.events
    )


def _body_origin_continuity_proven(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
) -> bool:
    """Require positive current topology before retaining body cleanup proof."""

    if _verified_provenance(
        lease,
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
    ) is None:
        return False
    target_active = (
        evidence.pool_active
        if lease.body is ThermalBody.POOL
        else evidence.spa_active
    )
    target_fresh = (
        evidence.pool_activity_fresh
        if lease.body is ThermalBody.POOL
        else evidence.spa_activity_fresh
    )
    target_usable = (
        evidence.pool_activity_usable
        if lease.body is ThermalBody.POOL
        else evidence.spa_activity_usable
    )
    other_active = (
        evidence.spa_active
        if lease.body is ThermalBody.POOL
        else evidence.pool_active
    )
    other_fresh = (
        evidence.spa_activity_fresh
        if lease.body is ThermalBody.POOL
        else evidence.pool_activity_fresh
    )
    other_usable = (
        evidence.spa_activity_usable
        if lease.body is ThermalBody.POOL
        else evidence.pool_activity_usable
    )
    if not (
        target_active is True
        and target_fresh
        and target_usable
        and other_active is False
        and other_fresh
        and other_usable
        and evidence.shared_hydraulic_inventory_complete
    ):
        return False
    if any(
        item.active is not False
        or not item.fresh
        or not item.usable
        or item.safety_class is SharedHydraulicSafetyClass.UNKNOWN
        for item in evidence.shared_hydraulic_circuits
    ):
        return False
    target_concept = (
        "pool.active" if lease.body is ThermalBody.POOL else "spa.active"
    )
    return not any(
        event.observed_at >= lease.established_at
        and event.concept == target_concept
        for event in evidence.external_changes.events
    )


def _terminal_transition_diagnostic(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
    *,
    status: ThermalRuntimeOwnershipStatus,
    reason: str,
    occurred_at: datetime,
) -> ThermalRuntimeOwnershipTransitionDiagnostic:
    concept = _affected_concept(reason)
    provenance = (
        None if concept is None else _provenance_for_concept(lease, concept)
    )
    expected = None if provenance is None else provenance.intended_value
    expected_value = (
        expected.value if isinstance(expected, PhysicalHeatMode) else expected
    )
    observed_value, observed_at = _observed_transition_value(
        lease,
        evidence,
        reason=reason,
        concept=concept,
    )
    accepted_at = (
        None if concept is None else _accepted_at_for_concept(lease, concept)
    )
    currentness_disposition: str | None = None
    purpose_id: str | None = None
    if lease.originating_currentness is not None:
        purpose_id = lease.originating_currentness.purpose.purpose_id
        if (
            evidence.current_context.execution_currentness is not None
            and lease.execution_progress is not None
        ):
            currentness_disposition = assess_execution_compatibility(
                lease.originating_currentness,
                evidence.current_context.execution_currentness,
                progress=lease.execution_progress,
            ).disposition.value
    external = _diagnostic_external_event(lease, evidence, concept)
    return ThermalRuntimeOwnershipTransitionDiagnostic(
        previous_status=ThermalRuntimeOwnershipStatus.OWNED,
        current_status=status,
        occurred_at=occurred_at,
        reason_code=reason,
        affected_concept=concept,
        expected_value=expected_value,
        observed_value=observed_value,
        observed_at=observed_at,
        operation_id=None if provenance is None else provenance.operation_id,
        correlation_id=None if provenance is None else provenance.correlation_id,
        accepted_at=accepted_at,
        execution_purpose_id=purpose_id,
        currentness_disposition=currentness_disposition,
        external_event_id=None if external is None else external.event_id,
        external_event_concept=None if external is None else external.concept,
        external_event_observed_at=(
            None if external is None else external.observed_at
        ),
    )


def _relinquishment_transition_diagnostic(
    lease: ThermalRuntimeOwnershipLease,
    *,
    reason: str,
    occurred_at: datetime,
) -> ThermalRuntimeOwnershipTransitionDiagnostic:
    accepted = (
        None
        if lease.execution_progress is None
        else lease.execution_progress.accepted_current
    )
    role_to_concept = {
        "body_activation": ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        "priming": ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        "pool_temperature_probe": ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        "thermal_pump_target": ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        "heat_source": ThermalRuntimeOwnedConcept.HEAT_SOURCE,
    }
    concept = None if accepted is None else role_to_concept.get(accepted.role)
    provenance = (
        None if concept is None else _provenance_for_concept(lease, concept)
    )
    expected = None if provenance is None else provenance.intended_value
    return ThermalRuntimeOwnershipTransitionDiagnostic(
        previous_status=ThermalRuntimeOwnershipStatus.OWNED,
        current_status=ThermalRuntimeOwnershipStatus.RELINQUISHED,
        occurred_at=occurred_at,
        reason_code=reason,
        affected_concept=concept,
        expected_value=(
            expected.value if isinstance(expected, PhysicalHeatMode) else expected
        ),
        observed_value=None,
        observed_at=None,
        operation_id=None if provenance is None else provenance.operation_id,
        correlation_id=None if provenance is None else provenance.correlation_id,
        accepted_at=(
            None if concept is None else _accepted_at_for_concept(lease, concept)
        ),
        execution_purpose_id=(
            None
            if lease.originating_currentness is None
            else lease.originating_currentness.purpose.purpose_id
        ),
        currentness_disposition=None,
        external_event_id=None,
        external_event_concept=None,
        external_event_observed_at=None,
    )


def _affected_concept(reason: str) -> ThermalRuntimeOwnedConcept | None:
    detail = reason
    for prefix in (
        "runtime_ownership_preempted:",
        "runtime_ownership_superseded:",
        "runtime_ownership_relinquished:",
    ):
        if detail.startswith(prefix):
            detail = detail.removeprefix(prefix)
            break
    if detail.startswith("shared_hydraulic_"):
        return ThermalRuntimeOwnedConcept.BODY_ACTIVATION
    if detail.startswith("pump_"):
        return ThermalRuntimeOwnedConcept.PUMP_SETPOINT
    if detail.startswith("source_"):
        return ThermalRuntimeOwnedConcept.HEAT_SOURCE
    if detail.startswith(
        (
            "pool_activity_",
            "spa_activity_",
            "pool_inactive",
            "hot_tub_inactive",
            "pool_takeover",
            "spa_takeover",
            "body_",
        )
    ):
        return ThermalRuntimeOwnedConcept.BODY_ACTIVATION
    return None


def _provenance_for_concept(
    lease: ThermalRuntimeOwnershipLease,
    concept: ThermalRuntimeOwnedConcept,
) -> ThermalRuntimeConceptProvenance | None:
    return {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: lease.body_activation,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: lease.pump_setpoint,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: lease.heat_source,
    }[concept]


def _accepted_at_for_concept(
    lease: ThermalRuntimeOwnershipLease,
    concept: ThermalRuntimeOwnedConcept,
) -> datetime | None:
    return {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: lease.body_activation_accepted_at,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: lease.pump_setpoint_accepted_at,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: lease.heat_source_accepted_at,
    }[concept]


def _observed_transition_value(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
    *,
    reason: str,
    concept: ThermalRuntimeOwnedConcept | None,
) -> tuple[bool | int | str | None, datetime | None]:
    if concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT:
        if "setpoint" in reason:
            return (
                evidence.configured_pump_speed_rpm,
                evidence.configured_pump_speed_observed_at,
            )
        return evidence.pump_rpm, evidence.pump_observed_at
    if concept is ThermalRuntimeOwnedConcept.HEAT_SOURCE:
        value = evidence.effective_heat_source
        return (
            None if value is None else value.value,
            evidence.heat_source_observed_at,
        )
    if concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION:
        if "shared_hydraulic" in reason:
            conflicting = next(
                (
                    item
                    for item in evidence.shared_hydraulic_circuits
                    if item.active is not False
                ),
                None,
            )
            return (
                None if conflicting is None else conflicting.active,
                None if conflicting is None else conflicting.observed_at,
            )
        if lease.body is ThermalBody.POOL:
            return evidence.pool_active, evidence.pool_activity_observed_at
        return evidence.spa_active, evidence.spa_activity_observed_at
    return None, None


def _diagnostic_external_event(
    lease: ThermalRuntimeOwnershipLease,
    evidence: ThermalRuntimeOwnershipEvidence,
    concept: ThermalRuntimeOwnedConcept | None,
) -> ExternalChangeEvent | None:
    def relevant(event: ExternalChangeEvent) -> bool:
        if concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION:
            return event.concept == (
                "pool.active" if lease.body is ThermalBody.POOL else "spa.active"
            )
        if concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT:
            return event.concept == "pump.rpm" or event.concept.endswith(
                ".configured_speed_rpm"
            )
        if concept is ThermalRuntimeOwnedConcept.HEAT_SOURCE:
            return event.concept == (
                "pool.raw_heater_id"
                if lease.body is ThermalBody.POOL
                else "spa.raw_heater_id"
            )
        return False

    candidates = tuple(
        event
        for event in evidence.external_changes.events
        if event.observed_at >= lease.established_at
        and (
            concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION
            or event.reconciliation_required
        )
        and relevant(event)
    )
    return max(candidates, key=lambda event: event.observed_at, default=None)


def _verified_provenance(
    lease: ThermalRuntimeOwnershipLease,
    concept: ThermalRuntimeOwnedConcept,
) -> ThermalRuntimeConceptProvenance | None:
    provenance = {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: lease.body_activation,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: lease.pump_setpoint,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: lease.heat_source,
    }[concept]
    if provenance is None or concept not in lease.verified_concepts:
        return None
    return provenance


def _promoted_verified_concepts(
    lease: ThermalRuntimeOwnershipLease,
    *,
    activation: ThermalRuntimeConceptProvenance | None,
    pump: ThermalRuntimeConceptProvenance | None,
    source: ThermalRuntimeConceptProvenance | None,
) -> tuple[ThermalRuntimeOwnedConcept, ...]:
    current = {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: activation or lease.body_activation,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: pump or lease.pump_setpoint,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: source or lease.heat_source,
    }
    prior = {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: lease.body_activation,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: lease.pump_setpoint,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: lease.heat_source,
    }
    derived: set[ThermalRuntimeOwnedConcept] = set()
    for concept in lease.verified_concepts:
        if prior[concept] == current[concept]:
            derived.add(concept)
    return tuple(concept for concept in ThermalRuntimeOwnedConcept if concept in derived)


def _promoted_accepted_at(
    provenance: ThermalRuntimeConceptProvenance | None,
    *,
    previous: ThermalRuntimeConceptProvenance | None,
    previous_accepted_at: datetime | None,
    promoted_at: datetime,
) -> datetime | None:
    if provenance is None:
        return previous_accepted_at
    if provenance == previous:
        return previous_accepted_at
    return promoted_at


def _accepted_boundary(
    promoted_at: datetime,
    receipt_accepted_at: datetime | None,
) -> datetime:
    if receipt_accepted_at is None:
        return promoted_at
    _require_aware(receipt_accepted_at, "receipt_accepted_at")
    return receipt_accepted_at


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "SHARED_HYDRAULIC_SAFETY_BY_CONCEPT",
    "SharedHydraulicCircuitEvidence",
    "SharedHydraulicSafetyClass",
    "ThermalResidualTerminationEntitlement",
    "ThermalRuntimeConceptProvenance",
    "ThermalRuntimeHandoffRequest",
    "ThermalRuntimeOwnedConcept",
    "ThermalRuntimeOwnershipDecision",
    "ThermalRuntimeOwnershipDisposition",
    "ThermalRuntimeOwnershipEvidence",
    "ThermalRuntimeOwnershipLease",
    "ThermalRuntimeOwnershipManager",
    "ThermalRuntimeOwnershipState",
    "ThermalRuntimeOwnershipStatus",
    "ThermalRuntimeOwnershipTransitionDiagnostic",
    "shared_hydraulic_safety_class",
]
