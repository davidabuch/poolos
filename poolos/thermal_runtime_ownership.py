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

from .external_change import ExternalChangeBatch
from .integration import PhysicalHeatMode, ThermalBody
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
class SharedHydraulicCircuitEvidence:
    """One already-classified circuit observation supplied by an orchestrator."""

    concept: str
    active: bool | None
    fresh: bool
    usable: bool
    safety_class: SharedHydraulicSafetyClass

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

    def __post_init__(self) -> None:
        if self.pump_rpm_tolerance < 0:
            raise ValueError("pump_rpm_tolerance must not be negative")

    @property
    def state(self) -> ThermalRuntimeOwnershipState:
        return self._state

    def establish(
        self,
        ownership: ThermalLiveExecutionOwnership,
        *,
        established_at: datetime,
        requested_mode: str,
        current_context: ThermalLiveExecutionContext,
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
        )
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
        reason = self._continuation_failure_reason(lease, evidence)
        if reason is not None:
            return self._terminate(lease, reason=reason, at=evidence.evaluated_at)
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
        )
        self._state = ThermalRuntimeOwnershipState(
            status=successor.status,
            lease=successor,
            reason_code=successor.reason_code,
        )
        return self._decision(
            ThermalRuntimeOwnershipDisposition.HANDED_OFF,
            successor.reason_code,
            previous,
            evidence.evaluated_at,
        )

    def relinquish(
        self,
        *,
        lease_id: str,
        relinquished_at: datetime,
        reason_code: str,
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
        return self._decision(
            ThermalRuntimeOwnershipDisposition.RELINQUISHED,
            reason,
            previous,
            relinquished_at,
        )

    def _continuation_failure_reason(
        self,
        lease: ThermalRuntimeOwnershipLease,
        evidence: ThermalRuntimeOwnershipEvidence,
        *,
        check_identity: bool = True,
        check_requested_mode: bool = True,
    ) -> str | None:
        if evidence.evaluated_at < lease.last_confirmed_at:
            return "runtime_ownership_preempted:evidence_temporal_regression"
        if check_identity:
            if evidence.current_context.evaluation_id != lease.evaluation_id:
                return "runtime_ownership_superseded:evaluation_id"
            if evidence.current_context.plan_id != lease.thermal_plan_id:
                return "runtime_ownership_superseded:plan_id"
        if check_requested_mode and evidence.requested_mode != lease.requested_mode:
            return "runtime_ownership_superseded:requested_mode"
        hydraulic = _hydraulic_failure_reason(lease.body, evidence)
        if hydraulic is not None:
            return hydraulic
        shared = _shared_hydraulic_failure_reason(evidence)
        if shared is not None:
            return shared
        if lease.pump_setpoint is not None:
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
        if lease.heat_source is not None:
            if evidence.effective_heat_source is None:
                return "runtime_ownership_preempted:source_evidence_missing"
            if not evidence.heat_source_observation_fresh:
                return "runtime_ownership_preempted:source_evidence_stale"
            if not evidence.heat_source_observation_usable:
                return "runtime_ownership_preempted:source_evidence_unusable"
            if evidence.effective_heat_source is not lease.heat_source.intended_value:
                return "runtime_ownership_preempted:source_external_change"
        external = _external_preemption_reason(lease, evidence.external_changes)
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
            if request.successor_required_pump_rpm != lease.pump_setpoint.intended_value:
                return prefix + "pump_incompatible"
        if lease.heat_source is not None:
            if request.successor_heat_source is not lease.heat_source.intended_value:
                return prefix + "source_incompatible"
        return None

    def _terminate(
        self,
        lease: ThermalRuntimeOwnershipLease,
        *,
        reason: str,
        at: datetime,
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
        if evidence.pool_active is not True:
            return "runtime_ownership_preempted:pool_inactive"
    else:
        if evidence.pool_active is True:
            return "runtime_ownership_preempted:pool_takeover"
        if evidence.spa_active is not True:
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
) -> str | None:
    target_prefix = "pool" if lease.body is ThermalBody.POOL else "spa"
    target_body_concept = f"{target_prefix}.active"
    for event in batch.events:
        if lease.body_activation is not None and event.concept == target_body_concept:
            return "runtime_ownership_preempted:body_external_change"
        if (
            lease.pump_setpoint is not None
            and event.concept == "pump.rpm"
            and event.reconciliation_required
        ):
            return "runtime_ownership_preempted:pump_external_change"
        if (
            lease.heat_source is not None
            and event.concept == f"{target_prefix}.raw_heater_id"
            and event.reconciliation_required
        ):
            return "runtime_ownership_preempted:source_external_change"
    return None


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


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "SHARED_HYDRAULIC_SAFETY_BY_CONCEPT",
    "SharedHydraulicCircuitEvidence",
    "SharedHydraulicSafetyClass",
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
    "shared_hydraulic_safety_class",
]
