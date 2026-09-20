"""Command-free runtime ownership and preemption for thermal lifecycles.

Observed equipment state can confirm or invalidate an existing lease, but it
can never create one. A lease originates only from accepted, session-scoped
thermal delivery provenance and exposes no execution or delivery method.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from .pool_circulation_ownership import FiltrationToThermalHandoff

from .external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
)
from .integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed, ThermalBody
from .ownership_evidence import (
    DomainOwnershipState,
    OwnershipAuthority,
    OwnershipDomain,
    OwnershipHealth,
    OwnershipEvidenceKind,
    PositiveOperatorEvidence,
)
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
class ThermalRuntimeBodyAdoption:
    """Fresh prospective BODY origin; never an accepted command receipt."""

    adoption_id: str
    body: ThermalBody
    evaluation_id: str
    thermal_plan_id: str
    execution_plan_id: str
    body_session_id: str
    body_session_generation: int
    opportunity_id: str
    reason_code: str
    adopted_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "adoption_id",
            "evaluation_id",
            "thermal_plan_id",
            "execution_plan_id",
            "body_session_id",
            "opportunity_id",
            "reason_code",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.body_session_generation < 1:
            raise ValueError("body_session_generation must be positive")
        object.__setattr__(self, "body", ThermalBody(self.body))
        _require_aware(self.adopted_at, "adopted_at")


@dataclass(frozen=True, slots=True)
class ThermalRuntimeConceptAdoption:
    """Fresh prospective Pump/Thermal origin; never a command receipt."""

    adoption_id: str
    concept: ThermalRuntimeOwnedConcept
    intended_value: int | PhysicalHeatMode
    observed_at: datetime
    opportunity_id: str
    reason_code: str
    adopted_at: datetime

    def __post_init__(self) -> None:
        for name in ("adoption_id", "opportunity_id", "reason_code"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        concept = ThermalRuntimeOwnedConcept(self.concept)
        if concept not in {
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
            ThermalRuntimeOwnedConcept.HEAT_SOURCE,
        }:
            raise ValueError("concept adoption is limited to Pump/Thermal")
        if concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT:
            if (
                isinstance(self.intended_value, bool)
                or not isinstance(self.intended_value, int)
                or self.intended_value <= 0
            ):
                raise ValueError("pump adoption requires a positive integer RPM")
        else:
            object.__setattr__(
                self,
                "intended_value",
                PhysicalHeatMode(self.intended_value),
            )
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.adopted_at, "adopted_at")
        if self.observed_at > self.adopted_at:
            raise ValueError("concept adoption evidence cannot follow adoption")
        object.__setattr__(self, "concept", concept)


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
    body_adoption: ThermalRuntimeBodyAdoption | None = None
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    heat_source: ThermalRuntimeConceptProvenance | None = None
    pump_setpoint_accepted_at: datetime | None = None
    body_session_id: str | None = None
    body_session_generation: int | None = None

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
        if self.body_activation is not None and self.body_adoption is not None:
            raise ValueError("residual body command provenance and adoption are exclusive")
        if self.body_adoption is not None and self.body_adoption.body is not self.body:
            raise ValueError("residual body adoption must match entitlement body")
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
                (
                    ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
                    self.body_activation or self.body_adoption,
                ),
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
    body_adoption: ThermalRuntimeBodyAdoption | None = None
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    pump_adoption: ThermalRuntimeConceptAdoption | None = None
    heat_source: ThermalRuntimeConceptProvenance | None = None
    heat_source_adoption: ThermalRuntimeConceptAdoption | None = None
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
    domain_states: tuple[DomainOwnershipState, ...] = ()
    body_session_id: str | None = None
    body_session_generation: int | None = None

    def domain_state(self, domain: OwnershipDomain) -> DomainOwnershipState:
        return next(
            (state for state in self.domain_states if state.domain is domain),
            DomainOwnershipState(domain),
        )

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
        if self.body_session_id is None:
            object.__setattr__(self, "body_session_id", self.lease_id)
        if self.body_session_generation is None:
            object.__setattr__(self, "body_session_generation", self.generation)
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
        if self.body_activation is not None and self.body_adoption is not None:
            raise ValueError("thermal body command provenance and adoption are exclusive")
        if self.pump_setpoint is not None and self.pump_adoption is not None:
            raise ValueError("thermal pump command provenance and adoption are exclusive")
        if self.heat_source is not None and self.heat_source_adoption is not None:
            raise ValueError("thermal source command provenance and adoption are exclusive")
        if self.pump_adoption is not None and (
            self.pump_adoption.concept is not ThermalRuntimeOwnedConcept.PUMP_SETPOINT
        ):
            raise ValueError("pump adoption must reference the Pump domain")
        if self.heat_source_adoption is not None and (
            self.heat_source_adoption.concept is not ThermalRuntimeOwnedConcept.HEAT_SOURCE
        ):
            raise ValueError("source adoption must reference the Thermal domain")
        if self.body_adoption is not None:
            if self.body_adoption.body is not self.body:
                raise ValueError("thermal body adoption must match lease body")
            if (
                self.body_adoption.body_session_id != self.body_session_id
                or self.body_adoption.body_session_generation
                != self.body_session_generation
            ):
                raise ValueError("thermal body adoption must match body session")
            if self.body_adoption.adopted_at > self.established_at:
                raise ValueError("thermal body adoption cannot follow lease establishment")
            if self.predecessor_lease_id is None and (
                self.body_adoption.evaluation_id != self.evaluation_id
                or self.body_adoption.thermal_plan_id != self.thermal_plan_id
                or self.body_adoption.execution_plan_id != self.execution_plan_id
                or self.body_adoption.adopted_at != self.established_at
            ):
                raise ValueError("initial thermal body adoption must reference lease origin")
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
        states = {state.domain: state for state in self.domain_states}
        for domain, origin in (
            (OwnershipDomain.BODY, self.body_activation or self.body_adoption),
            (OwnershipDomain.PUMP, self.pump_setpoint or self.pump_adoption),
            (
                OwnershipDomain.THERMAL,
                self.heat_source or self.heat_source_adoption,
            ),
        ):
            if origin is None and domain in states and states[domain].authority is OwnershipAuthority.POOLOS:
                del states[domain]
            if origin is not None and domain not in states:
                states[domain] = DomainOwnershipState(
                    domain, authority=OwnershipAuthority.POOLOS,
                    health=OwnershipHealth.PENDING, command_blocker=None,
                )
        object.__setattr__(self, "domain_states", tuple(states.values()))

    @property
    def owns_body_activation(self) -> bool:
        return (
            self.body_activation is not None
            and self.domain_state(OwnershipDomain.BODY).authority
            is OwnershipAuthority.POOLOS
        )

    @property
    def owns_body_adoption(self) -> bool:
        return (
            self.body_adoption is not None
            and self.domain_state(OwnershipDomain.BODY).authority
            is OwnershipAuthority.POOLOS
        )

    @property
    def owns_body(self) -> bool:
        return self.owns_body_activation or self.owns_body_adoption

    @property
    def owns_pump_setpoint(self) -> bool:
        return (
            (self.pump_setpoint is not None or self.pump_adoption is not None)
            and self.domain_state(OwnershipDomain.PUMP).authority
            is OwnershipAuthority.POOLOS
        )

    @property
    def owns_heat_source(self) -> bool:
        return (
            (self.heat_source is not None or self.heat_source_adoption is not None)
            and self.domain_state(OwnershipDomain.THERMAL).authority
            is OwnershipAuthority.POOLOS
        )


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
class ThermalQuickRestartCheckpoint:
    """Durable proof for one narrowly bounded quick-restart continuation.

    This is not physical-state adoption.  Every owned concept must already
    have accepted and verified PoolOS provenance before the checkpoint can be
    exported.  Fresh post-restart observations may only revalidate that exact
    prior authority for the same semantic thermal purpose.
    """

    captured_at: datetime
    lease_id: str
    generation: int
    body: ThermalBody
    requested_mode: str
    execution_plan_id: str
    purpose_id: str
    established_at: datetime
    body_activation: ThermalRuntimeConceptProvenance
    pump_setpoint: ThermalRuntimeConceptProvenance
    heat_source: ThermalRuntimeConceptProvenance
    verified_concepts: tuple[ThermalRuntimeOwnedConcept, ...]
    body_activation_accepted_at: datetime
    pump_setpoint_accepted_at: datetime
    heat_source_accepted_at: datetime
    domain_states: tuple[DomainOwnershipState, ...]
    body_session_id: str
    body_session_generation: int

    def __post_init__(self) -> None:
        _require_aware(self.captured_at, "captured_at")
        _require_aware(self.established_at, "established_at")
        for name in (
            "lease_id",
            "requested_mode",
            "execution_plan_id",
            "purpose_id",
            "body_session_id",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.generation < 1 or self.body_session_generation < 1:
            raise ValueError("restart checkpoint generations must be positive")
        object.__setattr__(self, "body", ThermalBody(self.body))
        for name in (
            "body_activation_accepted_at",
            "pump_setpoint_accepted_at",
            "heat_source_accepted_at",
        ):
            _require_aware(getattr(self, name), name)
        verified = tuple(
            ThermalRuntimeOwnedConcept(item)
            for item in self.verified_concepts
        )
        object.__setattr__(self, "verified_concepts", verified)
        object.__setattr__(self, "domain_states", tuple(self.domain_states))


    def to_restore_state(self) -> dict[str, object]:
        """Return a JSON-safe representation suitable for HA RestoreEntity."""

        def provenance(
            item: ThermalRuntimeConceptProvenance,
        ) -> dict[str, object]:
            intended = item.intended_value
            if isinstance(intended, PhysicalHeatMode):
                value: object = intended.value
            else:
                value = intended
            return {
                "concept": item.concept.value,
                "operation_id": item.operation_id,
                "receipt_id": item.receipt_id,
                "correlation_id": item.correlation_id,
                "intended_value": value,
            }

        return {
            "schema": 1,
            "captured_at": self.captured_at.isoformat(),
            "lease_id": self.lease_id,
            "generation": self.generation,
            "body": self.body.value,
            "requested_mode": self.requested_mode,
            "execution_plan_id": self.execution_plan_id,
            "purpose_id": self.purpose_id,
            "established_at": self.established_at.isoformat(),
            "body_activation": provenance(self.body_activation),
            "pump_setpoint": provenance(self.pump_setpoint),
            "heat_source": provenance(self.heat_source),
            "body_activation_accepted_at": (
                self.body_activation_accepted_at.isoformat()
            ),
            "pump_setpoint_accepted_at": (
                self.pump_setpoint_accepted_at.isoformat()
            ),
            "heat_source_accepted_at": (
                self.heat_source_accepted_at.isoformat()
            ),
            "body_session_id": self.body_session_id,
            "body_session_generation": self.body_session_generation,
        }

    @classmethod
    def from_restore_state(
        cls,
        value: Mapping[str, object],
    ) -> "ThermalQuickRestartCheckpoint":
        """Strictly decode one persisted RestoreEntity checkpoint."""

        if value.get("schema") != 1:
            raise ValueError("unsupported quick-restart checkpoint schema")

        def required_string(name: str) -> str:
            item = value.get(name)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{name} must be a nonempty string")
            return item

        def required_int(name: str) -> int:
            item = value.get(name)
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError(f"{name} must be a positive integer")
            return item

        def timestamp(name: str) -> datetime:
            parsed = datetime.fromisoformat(required_string(name))
            _require_aware(parsed, name)
            return parsed

        def provenance(
            name: str,
            concept: ThermalRuntimeOwnedConcept,
        ) -> ThermalRuntimeConceptProvenance:
            raw = value.get(name)
            if not isinstance(raw, Mapping):
                raise ValueError(f"{name} provenance must be a mapping")
            if raw.get("concept") != concept.value:
                raise ValueError(f"{name} provenance concept mismatch")

            operation_id_raw = raw.get("operation_id")
            receipt_id_raw = raw.get("receipt_id")
            correlation_id_raw = raw.get("correlation_id")
            if (
                not isinstance(operation_id_raw, str)
                or not operation_id_raw.strip()
                or not isinstance(receipt_id_raw, str)
                or not receipt_id_raw.strip()
                or not isinstance(correlation_id_raw, str)
                or not correlation_id_raw.strip()
            ):
                raise ValueError(f"{name} provenance identifiers invalid")

            operation_id: str = operation_id_raw
            receipt_id: str = receipt_id_raw
            correlation_id: str = correlation_id_raw

            intended = raw.get("intended_value")
            if concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION:
                if intended is not True:
                    raise ValueError("restart BODY provenance must target active")
                decoded: bool | int | PhysicalHeatMode = True
            elif concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT:
                if (
                    isinstance(intended, bool)
                    or not isinstance(intended, int)
                    or intended <= 0
                ):
                    raise ValueError("restart PUMP provenance invalid")
                decoded = intended
            else:
                if not isinstance(intended, str):
                    raise ValueError("restart THERMAL provenance invalid")
                decoded = PhysicalHeatMode(intended)

            return ThermalRuntimeConceptProvenance(
                concept=concept,
                operation_id=operation_id,
                receipt_id=receipt_id,
                correlation_id=correlation_id,
                intended_value=decoded,
            )

        captured_at = timestamp("captured_at")
        body_activation = provenance(
            "body_activation",
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        )
        pump_setpoint = provenance(
            "pump_setpoint",
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
        )
        heat_source = provenance(
            "heat_source",
            ThermalRuntimeOwnedConcept.HEAT_SOURCE,
        )

        # Export is restricted to fully stable PoolOS ownership. Reconstruct
        # only those exact stable domain states; no operator/reconciliation
        # episode is persisted or manufactured.
        states = (
            DomainOwnershipState(
                domain=OwnershipDomain.BODY,
                authority=OwnershipAuthority.POOLOS,
                health=OwnershipHealth.STABLE,
                evidence_kind=OwnershipEvidenceKind.EXPECTED_NATIVE_TRANSITION,
                command_blocker=None,
                target_value=True,
                observed_value=True,
                observed_at=captured_at,
            ),
            DomainOwnershipState(
                domain=OwnershipDomain.PUMP,
                authority=OwnershipAuthority.POOLOS,
                health=OwnershipHealth.STABLE,
                evidence_kind=OwnershipEvidenceKind.EXPECTED_NATIVE_TRANSITION,
                command_blocker=None,
                target_value=pump_setpoint.intended_value,
                observed_value=pump_setpoint.intended_value,
                observed_at=captured_at,
            ),
            DomainOwnershipState(
                domain=OwnershipDomain.THERMAL,
                authority=OwnershipAuthority.POOLOS,
                health=OwnershipHealth.STABLE,
                evidence_kind=OwnershipEvidenceKind.EXPECTED_NATIVE_TRANSITION,
                command_blocker=None,
                target_value=(
                    heat_source.intended_value.value
                    if isinstance(
                        heat_source.intended_value,
                        PhysicalHeatMode,
                    )
                    else heat_source.intended_value
                ),
                observed_value=(
                    heat_source.intended_value.value
                    if isinstance(
                        heat_source.intended_value,
                        PhysicalHeatMode,
                    )
                    else heat_source.intended_value
                ),
                observed_at=captured_at,
            ),
        )

        return cls(
            captured_at=captured_at,
            lease_id=required_string("lease_id"),
            generation=required_int("generation"),
            body=ThermalBody(required_string("body")),
            requested_mode=required_string("requested_mode"),
            execution_plan_id=required_string("execution_plan_id"),
            purpose_id=required_string("purpose_id"),
            established_at=timestamp("established_at"),
            body_activation=body_activation,
            pump_setpoint=pump_setpoint,
            heat_source=heat_source,
            verified_concepts=(
                ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
                ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
                ThermalRuntimeOwnedConcept.HEAT_SOURCE,
            ),
            body_activation_accepted_at=timestamp(
                "body_activation_accepted_at"
            ),
            pump_setpoint_accepted_at=timestamp(
                "pump_setpoint_accepted_at"
            ),
            heat_source_accepted_at=timestamp(
                "heat_source_accepted_at"
            ),
            domain_states=states,
            body_session_id=required_string("body_session_id"),
            body_session_generation=required_int(
                "body_session_generation"
            ),
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


    def export_restart_checkpoint(
        self,
        *,
        captured_at: datetime,
    ) -> ThermalQuickRestartCheckpoint | None:
        """Export only a fully verified Pool Solar ownership session."""

        _require_aware(captured_at, "captured_at")
        lease = self._state.lease
        if (
            self._state.status is not ThermalRuntimeOwnershipStatus.OWNED
            or lease is None
            or lease.body is not ThermalBody.POOL
            or lease.originating_currentness is None
        ):
            return None

        purpose = lease.originating_currentness.purpose
        if (
            purpose.kind is not ThermalExecutionPurposeKind.THERMAL_CONTROL
            or purpose.selected_source is not PhysicalHeatMode.SOLAR
            or purpose.required_pump_rpm is None
        ):
            return None

        if (
            lease.body_activation is None
            or lease.pump_setpoint is None
            or lease.heat_source is None
            or lease.body_activation_accepted_at is None
            or lease.pump_setpoint_accepted_at is None
            or lease.heat_source_accepted_at is None
            or lease.body_session_id is None
            or lease.body_session_generation is None
        ):
            return None

        required = {
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
            ThermalRuntimeOwnedConcept.HEAT_SOURCE,
        }
        if set(lease.verified_concepts) != required:
            return None

        if (
            lease.body_activation.intended_value is not True
            or lease.pump_setpoint.intended_value != purpose.required_pump_rpm
            or lease.heat_source.intended_value is not PhysicalHeatMode.SOLAR
        ):
            return None

        states = {
            state.domain: state
            for state in lease.domain_states
        }
        for domain in (
            OwnershipDomain.BODY,
            OwnershipDomain.PUMP,
            OwnershipDomain.THERMAL,
        ):
            state = states.get(domain)
            if (
                state is None
                or state.authority is not OwnershipAuthority.POOLOS
                or state.health is not OwnershipHealth.STABLE
                or state.positive_operator_evidence is not None
            ):
                return None

        return ThermalQuickRestartCheckpoint(
            captured_at=captured_at,
            lease_id=lease.lease_id,
            generation=lease.generation,
            body=lease.body,
            requested_mode=lease.requested_mode,
            execution_plan_id=lease.execution_plan_id,
            purpose_id=purpose.purpose_id,
            established_at=lease.established_at,
            body_activation=lease.body_activation,
            pump_setpoint=lease.pump_setpoint,
            heat_source=lease.heat_source,
            verified_concepts=lease.verified_concepts,
            body_activation_accepted_at=lease.body_activation_accepted_at,
            pump_setpoint_accepted_at=lease.pump_setpoint_accepted_at,
            heat_source_accepted_at=lease.heat_source_accepted_at,
            domain_states=lease.domain_states,
            body_session_id=lease.body_session_id,
            body_session_generation=lease.body_session_generation,
        )

    def restore_restart_checkpoint(
        self,
        checkpoint: ThermalQuickRestartCheckpoint,
        *,
        evidence: ThermalRuntimeOwnershipEvidence,
        max_age: timedelta,
    ) -> ThermalRuntimeOwnershipDecision:
        """Restore exact prior authority after a short matching restart only."""

        previous = self._state.status
        at = evidence.evaluated_at

        def deny(reason: str) -> ThermalRuntimeOwnershipDecision:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                f"runtime_ownership_restart_denied:{reason}",
                previous,
                at,
            )

        if max_age <= timedelta(0):
            raise ValueError("restart recovery max_age must be positive")

        if self._state.status is not ThermalRuntimeOwnershipStatus.UNOWNED:
            return deny("already_owned")

        if at < checkpoint.captured_at:
            return deny("clock_regression")

        if at - checkpoint.captured_at > max_age:
            return deny("checkpoint_stale")

        currentness = evidence.current_context.execution_currentness
        if currentness is None:
            return deny("currentness_unavailable")

        purpose = currentness.purpose
        if (
            purpose.purpose_id != checkpoint.purpose_id
            or purpose.body is not checkpoint.body
            or purpose.requested_mode.casefold()
            != checkpoint.requested_mode.casefold()
            or purpose.kind is not ThermalExecutionPurposeKind.THERMAL_CONTROL
            or purpose.selected_source is not PhysicalHeatMode.SOLAR
            or purpose.required_pump_rpm
            != checkpoint.pump_setpoint.intended_value
        ):
            return deny("purpose_changed")

        if (
            evidence.requested_mode.casefold()
            != checkpoint.requested_mode.casefold()
        ):
            return deny("requested_mode_changed")

        if evidence.external_changes.events:
            return deny("external_change_present")

        if checkpoint.body is not ThermalBody.POOL:
            return deny("unsupported_body")

        if (
            not evidence.pool_activity_fresh
            or not evidence.pool_activity_usable
            or evidence.pool_activity_observed_at is None
            or evidence.pool_activity_observed_at <= checkpoint.captured_at
            or evidence.pool_active is not True
        ):
            return deny("pool_state_mismatch")

        if (
            not evidence.spa_activity_fresh
            or not evidence.spa_activity_usable
            or evidence.spa_activity_observed_at is None
            or evidence.spa_activity_observed_at <= checkpoint.captured_at
            or evidence.spa_active is not False
        ):
            return deny("spa_state_mismatch")

        expected_rpm = checkpoint.pump_setpoint.intended_value
        if type(expected_rpm) is not int:
            return deny("checkpoint_pump_invalid")

        if (
            not evidence.pump_observation_fresh
            or not evidence.pump_observation_usable
            or evidence.pump_observed_at is None
            or evidence.pump_observed_at <= checkpoint.captured_at
            or evidence.pump_rpm is None
            or abs(evidence.pump_rpm - expected_rpm) > self.pump_rpm_tolerance
        ):
            return deny("pump_state_mismatch")

        if (
            not evidence.heat_source_observation_fresh
            or not evidence.heat_source_observation_usable
            or evidence.heat_source_observed_at is None
            or evidence.heat_source_observed_at <= checkpoint.captured_at
            or evidence.effective_heat_source
            is not checkpoint.heat_source.intended_value
        ):
            return deny("heat_source_mismatch")

        # Preserve the exact accepted command provenance and body-session
        # generation.  Only the transient planner/evaluation identity advances
        # to the fresh post-restart semantic context.
        lease = ThermalRuntimeOwnershipLease(
            lease_id=checkpoint.lease_id,
            generation=checkpoint.generation,
            body=checkpoint.body,
            evaluation_id=currentness.evaluation_id,
            thermal_plan_id=currentness.plan_id,
            execution_plan_id=checkpoint.execution_plan_id,
            requested_mode=checkpoint.requested_mode,
            established_at=checkpoint.established_at,
            last_confirmed_at=at,
            status=ThermalRuntimeOwnershipStatus.OWNED,
            reason_code="runtime_ownership_restored:quick_restart",
            body_activation=checkpoint.body_activation,
            pump_setpoint=checkpoint.pump_setpoint,
            heat_source=checkpoint.heat_source,
            originating_currentness=currentness,
            execution_progress=ThermalExecutionProgress(),
            verified_concepts=checkpoint.verified_concepts,
            body_activation_accepted_at=checkpoint.body_activation_accepted_at,
            pump_setpoint_accepted_at=checkpoint.pump_setpoint_accepted_at,
            heat_source_accepted_at=checkpoint.heat_source_accepted_at,
            domain_states=checkpoint.domain_states,
            body_session_id=checkpoint.body_session_id,
            body_session_generation=checkpoint.body_session_generation,
        )

        self._residual_termination = None
        self._state = ThermalRuntimeOwnershipState(
            status=ThermalRuntimeOwnershipStatus.OWNED,
            lease=lease,
            reason_code=lease.reason_code,
        )

        return self._decision(
            ThermalRuntimeOwnershipDisposition.ESTABLISHED,
            lease.reason_code,
            previous,
            at,
        )

    def adopt_body(
        self,
        *,
        body: ThermalBody,
        adopted_at: datetime,
        requested_mode: str,
        current_context: ThermalLiveExecutionContext,
        execution_plan_id: str,
        execution_progress: ThermalExecutionProgress,
        evidence: ThermalRuntimeOwnershipEvidence,
        opportunity_id: str,
        reason_code: str,
        adopt_pump_rpm: int | None = None,
        adopt_heat_source: PhysicalHeatMode | None = None,
    ) -> ThermalRuntimeOwnershipDecision:
        """Prospectively adopt an already-active BODY from fresh current policy.

        Adoption creates a new BODY origin from this boundary forward. It never
        fabricates a historical SetBodyActive receipt and grants no PUMP or
        THERMAL provenance.
        """

        _require_aware(adopted_at, "adopted_at")
        body = ThermalBody(body)
        previous = self._state.status
        current = self._state.lease

        def deny(reason: str) -> ThermalRuntimeOwnershipDecision:
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_adoption_denied:" + reason,
                previous,
                adopted_at,
            )

        if body is not ThermalBody.POOL:
            return deny("body_not_commissioned")
        if not requested_mode.strip() or not execution_plan_id.strip():
            return deny("identity_incomplete")
        if not opportunity_id.strip() or not reason_code.strip():
            raise ValueError("adoption opportunity and reason must not be empty")
        if current is not None and current.status is ThermalRuntimeOwnershipStatus.OWNED:
            return deny("already_owned")
        if evidence.evaluated_at != adopted_at:
            return deny("evidence_epoch_mismatch")
        if (
            evidence.current_context.evaluation_id != current_context.evaluation_id
            or evidence.current_context.plan_id != current_context.plan_id
            or evidence.current_context.execution_currentness
            != current_context.execution_currentness
        ):
            return deny("currentness_mismatch")
        currentness = current_context.execution_currentness
        if (
            currentness is None
            or currentness.purpose.body is not body
            or currentness.purpose.kind
            not in {
                ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE,
                ThermalExecutionPurposeKind.THERMAL_CONTROL,
            }
        ):
            return deny("independent_current_purpose_unavailable")
        if evidence.requested_mode != requested_mode:
            return deny("requested_mode_changed")
        if not (
            evidence.pool_active is True
            and evidence.pool_activity_fresh
            and evidence.pool_activity_usable
            and evidence.pool_activity_observed_at is not None
            and evidence.pool_activity_observed_at <= adopted_at
        ):
            return deny("pool_activity_unusable")
        if not (
            evidence.spa_active is False
            and evidence.spa_activity_fresh
            and evidence.spa_activity_usable
            and evidence.spa_activity_observed_at is not None
            and evidence.spa_activity_observed_at <= adopted_at
        ):
            return deny("spa_activity_unusable")
        if not evidence.shared_hydraulic_inventory_complete:
            return deny("shared_hydraulic_inventory_incomplete")
        if any(
            item.active is not False
            or not item.fresh
            or not item.usable
            or item.observed_at is None
            or item.observed_at > adopted_at
            or item.safety_class is SharedHydraulicSafetyClass.UNKNOWN
            for item in evidence.shared_hydraulic_circuits
        ):
            return deny("shared_hydraulic_topology_unusable")
        if adopt_pump_rpm is not None:
            if isinstance(adopt_pump_rpm, bool) or adopt_pump_rpm <= 0:
                raise ValueError("adopted pump RPM must be positive")
            if not (
                evidence.pump_observation_fresh
                and evidence.pump_observation_usable
                and evidence.configured_pump_speed_observation_fresh
                and evidence.configured_pump_speed_observation_usable
                and evidence.pump_observed_at is not None
                and evidence.configured_pump_speed_observed_at is not None
                and evidence.pump_observed_at <= adopted_at
                and evidence.configured_pump_speed_observed_at <= adopted_at
                and type(evidence.pump_rpm) is int
                and type(evidence.configured_pump_speed_rpm) is int
                and abs(evidence.pump_rpm - adopt_pump_rpm)
                <= self.pump_rpm_tolerance
                and abs(evidence.configured_pump_speed_rpm - adopt_pump_rpm)
                <= self.pump_rpm_tolerance
            ):
                return deny("pump_adoption_evidence_unusable")
        if adopt_heat_source is not None:
            adopt_heat_source = PhysicalHeatMode(adopt_heat_source)
            if not (
                evidence.heat_source_observation_fresh
                and evidence.heat_source_observation_usable
                and evidence.heat_source_observed_at is not None
                and evidence.heat_source_observed_at <= adopted_at
                and evidence.effective_heat_source is adopt_heat_source
            ):
                return deny("heat_source_adoption_evidence_unusable")

        generation = 1 if current is None else current.generation + 1
        lease_id = _lease_id(
            generation=generation,
            body=body,
            evaluation_id=current_context.evaluation_id,
            plan_id=current_context.plan_id,
            execution_plan_id=execution_plan_id,
            predecessor_lease_id=None,
        )
        adoption = ThermalRuntimeBodyAdoption(
            adoption_id=_body_adoption_id(
                generation=generation,
                body=body,
                evaluation_id=current_context.evaluation_id,
                plan_id=current_context.plan_id,
                execution_plan_id=execution_plan_id,
                adopted_at=adopted_at,
            ),
            body=body,
            evaluation_id=current_context.evaluation_id,
            thermal_plan_id=current_context.plan_id,
            execution_plan_id=execution_plan_id,
            body_session_id=lease_id,
            body_session_generation=generation,
            opportunity_id=opportunity_id,
            reason_code=reason_code,
            adopted_at=adopted_at,
        )
        body_state = DomainOwnershipState(
            OwnershipDomain.BODY,
            authority=OwnershipAuthority.POOLOS,
            health=OwnershipHealth.STABLE,
            evidence_kind=OwnershipEvidenceKind.LEGITIMATE_LIFECYCLE_TRANSITION,
            command_blocker=None,
            target_value=True,
            observed_value=True,
            observed_at=evidence.pool_activity_observed_at,
        )
        pump_adoption = (
            None
            if adopt_pump_rpm is None
            else ThermalRuntimeConceptAdoption(
                adoption_id=_concept_adoption_id(
                    generation=generation,
                    concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
                    opportunity_id=opportunity_id,
                    adopted_at=adopted_at,
                ),
                concept=ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
                intended_value=adopt_pump_rpm,
                observed_at=evidence.pump_observed_at,
                opportunity_id=opportunity_id,
                reason_code=reason_code,
                adopted_at=adopted_at,
            )
        )
        heat_source_adoption = (
            None
            if adopt_heat_source is None
            else ThermalRuntimeConceptAdoption(
                adoption_id=_concept_adoption_id(
                    generation=generation,
                    concept=ThermalRuntimeOwnedConcept.HEAT_SOURCE,
                    opportunity_id=opportunity_id,
                    adopted_at=adopted_at,
                ),
                concept=ThermalRuntimeOwnedConcept.HEAT_SOURCE,
                intended_value=adopt_heat_source,
                observed_at=evidence.heat_source_observed_at,
                opportunity_id=opportunity_id,
                reason_code=reason_code,
                adopted_at=adopted_at,
            )
        )
        domain_states = [body_state]
        if pump_adoption is not None:
            domain_states.append(
                DomainOwnershipState(
                    OwnershipDomain.PUMP,
                    authority=OwnershipAuthority.POOLOS,
                    health=OwnershipHealth.STABLE,
                    evidence_kind=OwnershipEvidenceKind.LEGITIMATE_LIFECYCLE_TRANSITION,
                    command_blocker=None,
                    target_value=adopt_pump_rpm,
                    observed_value=evidence.pump_rpm,
                    observed_at=evidence.pump_observed_at,
                )
            )
        if heat_source_adoption is not None:
            domain_states.append(
                DomainOwnershipState(
                    OwnershipDomain.THERMAL,
                    authority=OwnershipAuthority.POOLOS,
                    health=OwnershipHealth.STABLE,
                    evidence_kind=OwnershipEvidenceKind.LEGITIMATE_LIFECYCLE_TRANSITION,
                    command_blocker=None,
                    target_value=adopt_heat_source.value,
                    observed_value=(
                        None
                        if evidence.effective_heat_source is None
                        else evidence.effective_heat_source.value
                    ),
                    observed_at=evidence.heat_source_observed_at,
                )
            )
        lease = ThermalRuntimeOwnershipLease(
            lease_id=lease_id,
            generation=generation,
            body=body,
            evaluation_id=current_context.evaluation_id,
            thermal_plan_id=current_context.plan_id,
            execution_plan_id=execution_plan_id,
            requested_mode=requested_mode,
            established_at=adopted_at,
            last_confirmed_at=adopted_at,
            status=ThermalRuntimeOwnershipStatus.OWNED,
            reason_code=(
                "runtime_ownership_established:prospective_domain_adoption"
                if pump_adoption is not None or heat_source_adoption is not None
                else "runtime_ownership_established:prospective_body_adoption"
            ),
            body_adoption=adoption,
            pump_adoption=pump_adoption,
            heat_source_adoption=heat_source_adoption,
            originating_currentness=currentness,
            execution_progress=execution_progress,
            verified_concepts=(),
            domain_states=tuple(domain_states),
            body_session_id=lease_id,
            body_session_generation=generation,
        )
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
            adopted_at,
        )

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
            self.record_operator_events(
                evidence.external_changes,
                evaluated_at=evidence.evaluated_at,
            )
            return self._decision(
                ThermalRuntimeOwnershipDisposition.DENIED,
                "runtime_ownership_terminal",
                previous,
                evidence.evaluated_at,
            )
        self.record_operator_events(
            evidence.external_changes,
            evaluated_at=evidence.evaluated_at,
        )
        lease = self._state.lease
        assert lease is not None
        lease = self._confirm_accepted_consequence(lease, evidence)
        lease = self._observe_domains(lease, evidence)
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

    def _observe_domains(
        self,
        lease: ThermalRuntimeOwnershipLease,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipLease:
        """Assess existing domain origins without turning drift into an owner."""
        if evidence.evaluated_at < lease.last_confirmed_at:
            return lease
        progress = lease.execution_progress
        role = (None if progress is None or progress.accepted_current is None
                else progress.accepted_current.role)
        prefix = "pool" if lease.body is ThermalBody.POOL else "spa"
        states = []
        assert lease.body_session_id is not None
        assert lease.body_session_generation is not None
        for state in lease.domain_states:
            actual: bool | int | str | None
            if state.domain is OwnershipDomain.BODY:
                origin = lease.body_activation or lease.body_adoption
                actual = evidence.pool_active if prefix == "pool" else evidence.spa_active
                observed_at = (evidence.pool_activity_observed_at if prefix == "pool"
                               else evidence.spa_activity_observed_at)
                usable = (evidence.pool_activity_fresh and evidence.pool_activity_usable
                          if prefix == "pool" else
                          evidence.spa_activity_fresh and evidence.spa_activity_usable)
                matches = actual is True
                expected = role == "body_activation" and lease.body_activation is not None
                equipment = lease.body.value
            elif state.domain is OwnershipDomain.PUMP:
                origin = lease.pump_setpoint or lease.pump_adoption
                actual = evidence.pump_rpm
                observed_at = evidence.pump_observed_at
                usable = (evidence.pump_observation_fresh and evidence.pump_observation_usable
                          and evidence.configured_pump_speed_observation_fresh
                          and evidence.configured_pump_speed_observation_usable)
                matches = bool(
                    origin is not None and type(origin.intended_value) is int
                    and type(evidence.pump_rpm) is int
                    and type(evidence.configured_pump_speed_rpm) is int
                    and abs(evidence.pump_rpm - origin.intended_value) <= self.pump_rpm_tolerance
                    and abs(evidence.configured_pump_speed_rpm - origin.intended_value) <= self.pump_rpm_tolerance
                )
                expected = role in {"priming", "pool_temperature_probe", "thermal_pump_target"}
                equipment = "pump.rpm"
            else:
                origin = lease.heat_source or lease.heat_source_adoption
                actual = evidence.effective_heat_source
                observed_at = evidence.heat_source_observed_at
                usable = evidence.heat_source_observation_fresh and evidence.heat_source_observation_usable
                matches = origin is not None and evidence.effective_heat_source is origin.intended_value
                expected = role == "heat_source"
                equipment = f"{prefix}.raw_heater_id"
            if origin is None:
                states.append(state)
                continue
            operator = next((
                event.positive_operator_evidence
                for event in reversed(evidence.external_changes.events)
                if event.positive_operator_evidence is not None
                and event.positive_operator_evidence.domain is state.domain
                and lease.established_at <= event.positive_operator_evidence.requested_at
                <= evidence.evaluated_at
            ), None)
            origin_id = (
                origin.adoption_id
                if isinstance(
                    origin,
                    (ThermalRuntimeBodyAdoption, ThermalRuntimeConceptAdoption),
                )
                else origin.receipt_id
            )
            intended_value = (
                True
                if isinstance(origin, ThermalRuntimeBodyAdoption)
                else origin.intended_value
            )
            states.append(state.observe(
                at=evidence.evaluated_at, observed_at=observed_at, usable=usable,
                matches=matches, expected_transition=expected,
                generation=lease.body_session_generation, session_id=lease.body_session_id,
                equipment_id=equipment, policy_identity=lease.requested_mode,
                origin_id=origin_id, intended_value=intended_value,
                operator=operator,
                observed_value=actual,
            ))
        return replace(lease, domain_states=tuple(states))

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
        *,
        evaluated_at: datetime,
    ) -> str | None:
        """Assess current-lease external takeover without mutating ownership."""

        lease = self._state.lease
        if lease is None or lease.status is not ThermalRuntimeOwnershipStatus.OWNED:
            return None
        return _external_preemption_reason(
            lease,
            batch,
            evaluated_at=evaluated_at,
        )

    def domain_command_blocker(
        self, operation: SetBodyActive | SetPumpSpeed | SetHeatMode,
    ) -> str | None:
        """Additional denial only; existing exact execution authorization still applies."""
        lease = self._state.lease
        if lease is None:
            return None
        domain = (OwnershipDomain.BODY if isinstance(operation, SetBodyActive)
                  else OwnershipDomain.PUMP if isinstance(operation, SetPumpSpeed)
                  else OwnershipDomain.THERMAL)
        return self.domain_permission_blocker(domain)

    def domain_permission_blocker(
        self, domain: OwnershipDomain, *, completion_reduction: bool = False,
    ) -> str | None:
        lease = self._state.lease
        if lease is None:
            return None
        denial = lease.domain_state(domain).permission_denial(
            completion_reduction=completion_reduction,
        )
        return None if denial is None else "runtime_ownership_domain_command_denied:" + denial

    def reserve_domain_correction(
        self, operation: SetBodyActive | SetPumpSpeed | SetHeatMode, *, at: datetime,
    ) -> str | None:
        """Debit one bounded attempt before invoking the existing delivery engine."""
        lease = self._state.lease
        if lease is None:
            return None
        domain = (OwnershipDomain.BODY if isinstance(operation, SetBodyActive)
                  else OwnershipDomain.PUMP if isinstance(operation, SetPumpSpeed)
                  else OwnershipDomain.THERMAL)
        state = lease.domain_state(domain)
        episode = state.episode
        if episode is None or episode.verified_at is not None:
            return None
        try:
            updated = replace(state, episode=episode.reserve_correction(operation.operation_id, at=at))
            blocker = None
        except ValueError:
            blocker = "runtime_ownership_domain_command_denied:correction_budget_exhausted"
            updated = replace(state, health=OwnershipHealth.FAULTED,
                              evidence_kind=OwnershipEvidenceKind.COMMAND_OR_CONTROL_FAILURE,
                              command_blocker=blocker)
        lease = replace(lease, domain_states=tuple(
            updated if item.domain is domain else item for item in lease.domain_states
        ))
        self._state = replace(self._state, lease=lease)
        return blocker

    def record_operator_intent(
        self, evidence: PositiveOperatorEvidence, *, evaluated_at: datetime,
    ) -> bool:
        """Yield one current domain synchronously on a trusted explicit request."""
        lease = self._state.lease
        if lease is None:
            return False
        expected_equipment = {
            OwnershipDomain.BODY: lease.body.value,
            OwnershipDomain.PUMP: "pump.rpm",
            OwnershipDomain.THERMAL: (
                "pool.raw_heater_id" if lease.body is ThermalBody.POOL else "spa.raw_heater_id"
            ),
        }[evidence.domain]
        if not evidence.applies(
            generation=lease.body_session_generation or lease.generation,
            session_id=lease.body_session_id or lease.lease_id,
            domain=evidence.domain, equipment_id=expected_equipment,
            established_at=lease.established_at, evaluated_at=evaluated_at,
        ):
            return False
        prior = lease.domain_state(evidence.domain)
        if prior.positive_operator_evidence is not None:
            if prior.positive_operator_evidence == evidence:
                return True
            if evidence.requested_at <= prior.positive_operator_evidence.requested_at:
                return False
        yielded = replace(
            prior, authority=OwnershipAuthority.OPERATOR,
            evidence_kind=OwnershipEvidenceKind.POSITIVE_OPERATOR_INTERVENTION,
            positive_operator_evidence=evidence,
            command_blocker="ownership_operator_domain_override",
        )
        states = {state.domain: state for state in lease.domain_states}
        states[evidence.domain] = yielded
        updated = replace(lease, domain_states=tuple(states.values()))
        self._state = replace(self._state, lease=updated)
        residual = self._residual_termination
        if residual is not None and residual.lease_id == lease.lease_id:
            # A queued reduction must rebind to the new exact token; it cannot
            # retain command authority from before this operator intervention.
            self._residual_termination = _residual_entitlement(
                updated, at=evidence.requested_at,
                reason="runtime_ownership_operator_domain_yield:" + evidence.domain.value,
            )
        return True

    def record_operator_events(
        self,
        events: ExternalChangeBatch,
        *,
        evaluated_at: datetime,
    ) -> None:
        """Apply trusted domain intent to the current exact body generation."""

        for event in events.events:
            if event.positive_operator_evidence is not None:
                self.record_operator_intent(
                    event.positive_operator_evidence,
                    evaluated_at=evaluated_at,
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
            pump_adoption=(None if pump is not None else lease.pump_adoption),
            pump_session_id=(None if pump is not None else lease.pump_session_id),
            pump_session_effective_rpm=(
                None if pump is not None else lease.pump_session_effective_rpm
            ),
            heat_source=source or lease.heat_source,
            heat_source_adoption=(
                None if source is not None else lease.heat_source_adoption
            ),
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

    def finish_circulation_responsibility(
        self, *, lease_id: str, generation: int, completed_at: datetime,
    ) -> bool:
        """Retire authority after verified cleanup or an explicit successor transfer.

        Historical accepted receipts remain available. Only the exact terminal
        generation whose residual has already transferred can be retired.
        The caller supplies the reviewed cleanup/transfer outcome, not equality.
        """
        _require_aware(completed_at, "completion")
        lease = self._state.lease
        if (lease is None or lease.lease_id != lease_id or lease.generation != generation
                or lease.status is ThermalRuntimeOwnershipStatus.OWNED
                or self._residual_termination is not None
                or completed_at < lease.last_confirmed_at):
            return False
        states = tuple(replace(
            state, authority=OwnershipAuthority.NONE,
            evidence_kind=OwnershipEvidenceKind.LEGITIMATE_LIFECYCLE_TRANSITION,
            command_blocker="ownership_lifecycle_responsibility_transferred_or_completed",
        ) for state in lease.domain_states)
        self._state = replace(self._state, lease=replace(lease, domain_states=states))
        return True

    def receive_verified_filtration_body_transfer(
        self, transfer: FiltrationToThermalHandoff, *, thermal_lease_id: str,
    ) -> None:
        """Carry donor verification through the registry's exact typed transfer.

        The registry must validate its still-current donor and token before
        calling this method. Physical equality is deliberately not an input.
        A copied receipt alone cannot invoke this path through establishment.
        """
        lease = self._state.lease
        if (lease is None or lease.lease_id != thermal_lease_id
                or lease.status is not ThermalRuntimeOwnershipStatus.OWNED
                or lease.body is not ThermalBody.POOL
                or lease.body_activation != transfer.body_activation
                or lease.domain_state(OwnershipDomain.BODY).authority is not OwnershipAuthority.POOLOS
                or lease.originating_currentness is None
                or lease.originating_currentness.purpose.purpose_id != transfer.thermal_purpose_id
                or transfer.established_at > lease.last_confirmed_at):
            raise ValueError("thermal body transfer recipient is not current")
        verified = tuple(dict.fromkeys((
            *lease.verified_concepts,
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
            *(
                (ThermalRuntimeOwnedConcept.PUMP_SETPOINT,)
                if transfer.pump_setpoint is not None
                else ()
            ),
        )))
        self._state = replace(self._state, lease=replace(
            lease,
            pump_setpoint=transfer.pump_setpoint,
            pump_setpoint_accepted_at=transfer.pump_setpoint_accepted_at,
            verified_concepts=verified,
            body_session_id=transfer.body_session_id,
            body_session_generation=transfer.body_session_generation,
        ))

    def handoff(
        self,
        request: ThermalRuntimeHandoffRequest,
        evidence: ThermalRuntimeOwnershipEvidence,
    ) -> ThermalRuntimeOwnershipDecision:
        """Explicitly transfer a valid lease to one compatible current successor."""

        previous = self._state.status
        lease = self._state.lease
        if lease is not None and lease.status is ThermalRuntimeOwnershipStatus.OWNED:
            self.record_operator_events(
                evidence.external_changes,
                evaluated_at=evidence.evaluated_at,
            )
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
            pump_adoption=(
                None if request.replace_pump_setpoint else lease.pump_adoption
            ),
            pump_session_id=None,
            pump_session_effective_rpm=None,
            heat_source=(
                None if request.replace_heat_source else lease.heat_source
            ),
            heat_source_adoption=(
                None
                if request.replace_heat_source
                else lease.heat_source_adoption
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
        self.record_operator_events(
            evidence.external_changes,
            evaluated_at=evidence.evaluated_at,
        )
        lease = self._state.lease
        assert lease is not None
        lease = self._confirm_accepted_consequence(lease, evidence)
        lease = self._observe_domains(lease, evidence)
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
        # Pump/source disagreement affects domain health and exact command
        # permission. It cannot establish an operator or terminate BODY origin.
        external = _external_preemption_reason(
            lease,
            evidence.external_changes,
            evaluated_at=evidence.evaluated_at,
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
            requested_currentness = request.successor_context.execution_currentness
            observed_currentness = evidence.current_context.execution_currentness
            if requested_currentness is None or observed_currentness is None:
                return prefix + "successor_plan_not_current"

            compatibility = assess_execution_compatibility(
                requested_currentness,
                observed_currentness,
                progress=(
                    request.successor_progress
                    or ThermalExecutionProgress()
                ),
            )
            if (
                compatibility.reason_code
                != "thermal_execution_convergence_not_attributed"
            ):
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
        pump_origin = lease.pump_setpoint or lease.pump_adoption
        if pump_origin is not None:
            if (
                request.successor_required_pump_rpm
                != pump_origin.intended_value
                and not request.replace_pump_setpoint
            ):
                return prefix + "pump_incompatible"
        source_origin = lease.heat_source or lease.heat_source_adoption
        if source_origin is not None:
            if (
                request.successor_heat_source is not source_origin.intended_value
                and not request.replace_heat_source
            ):
                return prefix + "source_incompatible"
        if request.replace_pump_setpoint or request.replace_heat_source:
            predecessor = lease.originating_currentness
            successor = request.successor_context.execution_currentness
            if (
                predecessor is None
                or successor is None
                or not compatible_thermal_body_successor(predecessor, successor)
                or not request.successor_requires_body_active
            ):
                return prefix + "replacement_not_compatible_body_successor"
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


def compatible_thermal_body_successor(
    predecessor: ThermalExecutionCurrentness,
    successor: ThermalExecutionCurrentness,
) -> bool:
    """Potential typed Pool successor, never permission for an old execution."""
    before, after = predecessor.purpose, successor.purpose
    before_pumps = {op.equipment_id for op in predecessor.residual_plan.operations
                    if op.operation_type == "SetPumpSpeed"}
    after_pumps = {op.equipment_id for op in successor.residual_plan.operations
                   if op.operation_type == "SetPumpSpeed"}
    return (
        before.body is ThermalBody.POOL and after.body is ThermalBody.POOL
        and before.kind in {ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE,
                            ThermalExecutionPurposeKind.THERMAL_CONTROL}
        and after.kind is ThermalExecutionPurposeKind.THERMAL_CONTROL
        and after.selected_source is not PhysicalHeatMode.OFF
        and before.requested_mode == after.requested_mode
        and before.target_temperature_f == after.target_temperature_f
        and (not before_pumps or not after_pumps or before_pumps == after_pumps)
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
    evaluated_at: datetime,
) -> str | None:
    target_prefix = "pool" if lease.body is ThermalBody.POOL else "spa"
    target_body_concept = f"{target_prefix}.active"
    for event in batch.events:
        # An event predating this lease belongs to an earlier ownership epoch.
        # Equality remains fail-closed because ordering within one timestamp
        # cannot prove that the event preceded accepted lease establishment.
        if not lease.established_at <= event.observed_at <= evaluated_at:
            continue
        if (lease.body_activation is not None
                and event.concept == target_body_concept and event.new_value is False):
            return "runtime_ownership_preempted:body_session_interrupted"
        operator = event.positive_operator_evidence
        if operator is None or (
            operator.authority_generation != lease.body_session_generation
            or operator.body_session_id != lease.body_session_id
            or operator.requested_at < lease.established_at
            or operator.requested_at > event.observed_at
        ):
            continue
        if (
            lease.body_activation is not None
            and event.concept == target_body_concept
            and operator.domain is OwnershipDomain.BODY
            and operator.equipment_id == lease.body.value
        ):
            return "runtime_ownership_preempted:body_external_change"
        # PUMP and THERMAL intervention is represented on its own domain. It
        # cannot terminally preempt the aggregate BODY lifecycle.
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


def _body_adoption_id(
    *,
    generation: int,
    body: ThermalBody,
    evaluation_id: str,
    plan_id: str,
    execution_plan_id: str,
    adopted_at: datetime,
) -> str:
    payload = json.dumps(
        {
            "generation": generation,
            "body": body.value,
            "evaluation_id": evaluation_id,
            "plan_id": plan_id,
            "execution_plan_id": execution_plan_id,
            "adopted_at": adopted_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "thermal-body-adoption-" + sha256(payload.encode()).hexdigest()[:24]


def _concept_adoption_id(
    *,
    generation: int,
    concept: ThermalRuntimeOwnedConcept,
    opportunity_id: str,
    adopted_at: datetime,
) -> str:
    payload = json.dumps(
        {
            "generation": generation,
            "concept": concept.value,
            "opportunity_id": opportunity_id,
            "adopted_at": adopted_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "thermal-concept-adoption-" + sha256(payload.encode()).hexdigest()[:24]


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
    body_adoption = (
        lease.body_adoption
        if (
            include_body
            and lease.owns_body_adoption
            and _body_adoption_current_for_lease(lease)
        )
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
    if (
        body_activation is None
        and body_adoption is None
        and pump_setpoint is None
        and heat_source is None
    ):
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
        body_session_id=lease.body_session_id,
        body_session_generation=lease.body_session_generation,
        retained_at=at,
        reason_code=reason,
        body_activation=body_activation,
        body_adoption=body_adoption,
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

    if not (
        _verified_provenance(
            lease,
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
        )
        is not None
        or (
            lease.owns_body_adoption
            and _body_adoption_current_for_lease(lease)
        )
    ):
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


def _body_adoption_current_for_lease(
    lease: ThermalRuntimeOwnershipLease,
) -> bool:
    adoption = lease.body_adoption
    return bool(
        adoption is not None
        and adoption.body is lease.body
        and adoption.body_session_id == lease.body_session_id
        and adoption.body_session_generation == lease.body_session_generation
        and adoption.adopted_at <= lease.established_at
        and lease.domain_state(OwnershipDomain.BODY).authority
        is OwnershipAuthority.POOLOS
    )


def _verified_provenance(
    lease: ThermalRuntimeOwnershipLease,
    concept: ThermalRuntimeOwnedConcept,
) -> ThermalRuntimeConceptProvenance | None:
    provenance = {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: lease.body_activation,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: lease.pump_setpoint,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: lease.heat_source,
    }[concept]
    domain = {
        ThermalRuntimeOwnedConcept.BODY_ACTIVATION: OwnershipDomain.BODY,
        ThermalRuntimeOwnedConcept.PUMP_SETPOINT: OwnershipDomain.PUMP,
        ThermalRuntimeOwnedConcept.HEAT_SOURCE: OwnershipDomain.THERMAL,
    }[concept]
    if lease.domain_state(domain).authority is not OwnershipAuthority.POOLOS:
        return None
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
    "ThermalRuntimeBodyAdoption",
    "ThermalRuntimeConceptAdoption",
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
