"""Ephemeral single-owner arbitration for autonomous Pool circulation.

The registry owns no delivery port.  It records only accepted PoolOS command
provenance and explicit handoffs between the filtration and thermal runtimes.
Observed hardware equality can confirm or preempt an owner, but can never create
one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from .intellicenter_readonly import is_pmpcirc_native_id
from .ownership_evidence import (
    DomainOwnershipState, OwnershipAuthority, OwnershipDomain,
    OwnershipEvidenceKind, PositiveOperatorEvidence,
)
from .thermal_runtime_ownership import (
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
    ThermalRuntimeOwnershipManager,
)


class PoolCirculationOwner(StrEnum):
    NONE = "none"
    FILTRATION_ACQUIRING = "filtration_acquiring"
    FILTRATION = "filtration"
    FILTRATION_SUSPENDED = "filtration_suspended"
    THERMAL = "thermal"
    FILTRATION_TO_THERMAL = "filtration_to_thermal"


@dataclass(frozen=True, slots=True)
class FiltrationBodyAdoption:
    """Prospective Body provenance created at a legitimate recovery boundary."""

    adoption_id: str
    epoch_identity: str
    reason_code: str
    adopted_at: datetime

    def __post_init__(self) -> None:
        for name in ("adoption_id", "epoch_identity", "reason_code"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        _require_aware(self.adopted_at)


@dataclass(frozen=True, slots=True)
class FiltrationCirculationLease:
    """Accepted, session-scoped filtration command provenance."""

    lease_id: str
    generation: int
    session_id: str
    pool_pump_circuit_id: str
    established_at: datetime
    last_confirmed_at: datetime
    body_activation: ThermalRuntimeConceptProvenance | None = None
    body_adoption: FiltrationBodyAdoption | None = None
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    pump_established_at: datetime | None = None
    pump_session_id: str | None = None
    pump_session_effective_rpm: int | None = None
    body_verified: bool = False
    verified: bool = False
    domain_states: tuple[DomainOwnershipState, ...] = ()
    body_session_id: str | None = None
    body_session_generation: int | None = None

    def domain_state(self, domain: OwnershipDomain) -> DomainOwnershipState:
        return next((item for item in self.domain_states if item.domain is domain),
                    DomainOwnershipState(domain))

    def __post_init__(self) -> None:
        if self.body_session_id is None and self.body_session_generation is None:
            object.__setattr__(self, "body_session_id", self.session_id)
            object.__setattr__(self, "body_session_generation", self.generation)
        if (not self.body_session_id or self.body_session_generation is None
                or self.body_session_generation < 1):
            raise ValueError("filtration body session requires identity and generation")
        if not self.lease_id.strip() or not self.session_id.strip():
            raise ValueError("filtration lease identity must not be empty")
        if not is_pmpcirc_native_id(self.pool_pump_circuit_id):
            raise ValueError("filtration lease requires a concrete Pool PMPCIRC")
        if self.generation < 1:
            raise ValueError("filtration lease generation must be positive")
        _require_aware(self.established_at)
        _require_aware(self.last_confirmed_at)
        if self.last_confirmed_at < self.established_at:
            raise ValueError("filtration confirmation cannot predate establishment")
        if self.body_activation is not None and self.body_adoption is not None:
            raise ValueError(
                "filtration body command provenance and adoption are exclusive"
            )
        if (
            self.body_verified
            and self.body_activation is None
            and self.body_adoption is None
        ):
            raise ValueError(
                "verified filtration body requires command or adoption provenance"
            )
        if self.pump_established_at is not None:
            _require_aware(self.pump_established_at)
            if self.pump_setpoint is None:
                raise ValueError("filtration pump timestamp requires pump provenance")
        if (self.pump_session_id is None) != (
            self.pump_session_effective_rpm is None
        ):
            raise ValueError("filtration pump session binding must be paired")
        if self.pump_session_effective_rpm is not None and (
            type(self.pump_session_effective_rpm) is not int
            or self.pump_session_effective_rpm < 1
        ):
            raise ValueError("filtration session RPM must be a positive integer")
        if self.pump_setpoint is not None and self.pump_session_effective_rpm is not None:
            raise ValueError("filtration pump provenance and session binding are exclusive")
        if self.verified and (
            not self.body_verified
            or (
                self.body_activation is None
                and self.body_adoption is None
            )
            or (
                self.pump_setpoint is None
                and self.pump_session_effective_rpm is None
            )
        ):
            raise ValueError("verified filtration ownership requires body and pump proof")
        states = {item.domain: item for item in self.domain_states}
        for domain, origin in (
            (OwnershipDomain.BODY, self.body_activation or self.body_adoption),
            (OwnershipDomain.PUMP, self.pump_setpoint),
        ):
            if origin is not None and domain not in states:
                states[domain] = DomainOwnershipState(domain, OwnershipAuthority.POOLOS,
                                                       command_blocker=None)
        object.__setattr__(self, "domain_states", tuple(states.values()))


@dataclass(frozen=True, slots=True)
class FiltrationToThermalHandoff:
    """One explicit transition token; it is not itself physical authority."""

    token_id: str
    filtration_lease_id: str
    filtration_generation: int
    thermal_purpose_id: str
    established_at: datetime
    body_activation: ThermalRuntimeConceptProvenance
    pump_setpoint: ThermalRuntimeConceptProvenance | None = None
    pump_setpoint_accepted_at: datetime | None = None
    body_session_id: str | None = None
    body_session_generation: int | None = None

    def __post_init__(self) -> None:
        if self.body_session_id is None and self.body_session_generation is None:
            object.__setattr__(self, "body_session_id", self.filtration_lease_id)
            object.__setattr__(self, "body_session_generation", self.filtration_generation)
        if (not self.body_session_id or self.body_session_generation is None
                or self.body_session_generation < 1):
            raise ValueError("handoff requires the donor body session")
        for name in ("token_id", "filtration_lease_id", "thermal_purpose_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.filtration_generation < 1:
            raise ValueError("handoff generation must be positive")
        _require_aware(self.established_at)
        if self.pump_setpoint is not None:
            if self.pump_setpoint_accepted_at is None:
                raise ValueError("pump handoff requires its accepted timestamp")
            _require_aware(self.pump_setpoint_accepted_at)


@dataclass(slots=True)
class PoolCirculationOwnershipRegistry:
    """Keep at most one PoolOS circulation command owner in memory."""

    owner: PoolCirculationOwner = PoolCirculationOwner.NONE
    filtration_lease: FiltrationCirculationLease | None = None
    thermal_lease_id: str | None = None
    handoff: FiltrationToThermalHandoff | None = None
    _generation: int = field(default=0, init=False, repr=False)
    _epoch_identity: str | None = field(default=None, init=False, repr=False)
    _thermal_reserved_epoch: str | None = field(default=None, init=False, repr=False)

    def update_filtration_domain(self, state: DomainOwnershipState, *, session_id: str) -> None:
        lease = self.filtration_lease
        if lease is None or lease.session_id != session_id:
            raise ValueError("filtration domain session is not current")
        states = {item.domain: item for item in lease.domain_states}
        states[state.domain] = state
        self.filtration_lease = replace(lease, domain_states=tuple(states.values()))

    def record_operator_intent(
        self, evidence: PositiveOperatorEvidence, *, evaluated_at: datetime,
    ) -> bool:
        lease = self.filtration_lease
        if lease is None:
            return False
        expected_equipment = (lease.pool_pump_circuit_id
                              if evidence.domain is OwnershipDomain.PUMP else "B1101")
        if not evidence.applies(
            generation=lease.body_session_generation or lease.generation,
            session_id=lease.body_session_id or lease.session_id,
            domain=evidence.domain, equipment_id=expected_equipment,
            established_at=lease.established_at, evaluated_at=evaluated_at,
        ):
            return False
        prior = lease.domain_state(evidence.domain).positive_operator_evidence
        if prior is not None:
            if prior == evidence:
                return True
            if evidence.requested_at <= prior.requested_at:
                return False
        self.update_filtration_domain(replace(
            lease.domain_state(evidence.domain), authority=OwnershipAuthority.OPERATOR,
            positive_operator_evidence=evidence,
            evidence_kind=OwnershipEvidenceKind.POSITIVE_OPERATOR_INTERVENTION,
            command_blocker="ownership_operator_domain_override",
        ), session_id=lease.session_id)
        return True

    def domain_permission_blocker(self, domain: OwnershipDomain) -> str | None:
        lease = self.filtration_lease
        if lease is None:
            return None
        body = lease.domain_state(OwnershipDomain.BODY)
        if body.authority in {OwnershipAuthority.OPERATOR, OwnershipAuthority.SAFETY}:
            return "automatic_filtration_body_authority_yielded"
        denial = lease.domain_state(domain).permission_denial()
        if denial is None:
            return None
        if denial in {"operator", "safety"}:
            return "automatic_filtration_domain_override:" + domain.value
        if denial == "control_fault":
            return "automatic_filtration_domain_control_fault:" + domain.value
        return "automatic_filtration_domain_command_denied:" + denial

    def begin_epoch(self, epoch_identity: str) -> None:
        if not epoch_identity.strip():
            raise ValueError("circulation epoch identity must not be empty")
        if epoch_identity == self._epoch_identity:
            return
        self._epoch_identity = epoch_identity
        self._thermal_reserved_epoch = None

    def reserve_thermal(self, epoch_identity: str) -> bool:
        """Reserve this epoch for thermal, or open an explicit handoff."""

        if epoch_identity != self._epoch_identity:
            return False
        if self.owner is PoolCirculationOwner.THERMAL:
            self._thermal_reserved_epoch = epoch_identity
            return True
        if self.owner is PoolCirculationOwner.NONE:
            self._thermal_reserved_epoch = epoch_identity
            return True
        if self.owner is PoolCirculationOwner.FILTRATION:
            lease = self.filtration_lease
            if (
                lease is not None
                and lease.body_activation is None
                and lease.body_adoption is not None
            ):
                return False
            self._thermal_reserved_epoch = epoch_identity
            return True
        return False

    def thermal_reserved_for(self, epoch_identity: str) -> bool:
        """Return whether thermal won arbitration for this exact epoch."""

        return bool(
            epoch_identity == self._epoch_identity
            and self._thermal_reserved_epoch == epoch_identity
        )

    def filtration_may_deliver(self, *, epoch_identity: str, session_id: str) -> bool:
        if epoch_identity != self._epoch_identity:
            return False
        if self._thermal_reserved_epoch == epoch_identity:
            return False
        lease = self.filtration_lease
        return self.owner in {
            PoolCirculationOwner.NONE,
            PoolCirculationOwner.FILTRATION_ACQUIRING,
            PoolCirculationOwner.FILTRATION,
        } and (lease is None or lease.session_id == session_id)

    def adopt_filtration_body(
        self,
        *,
        session_id: str,
        pool_pump_circuit_id: str,
        adopted_at: datetime,
        epoch_identity: str,
        reason_code: str,
    ) -> FiltrationCirculationLease:
        """Create fresh prospective Body provenance without historical fabrication."""

        _require_aware(adopted_at)
        if not session_id.strip():
            raise ValueError("filtration adoption session identity must not be empty")
        if not epoch_identity.strip() or not reason_code.strip():
            raise ValueError("filtration adoption context must not be empty")
        if not is_pmpcirc_native_id(pool_pump_circuit_id):
            raise ValueError("filtration adoption requires a concrete Pool PMPCIRC")
        if (
            self.owner is not PoolCirculationOwner.NONE
            or self.filtration_lease is not None
        ):
            raise ValueError("filtration adoption requires unowned circulation")

        self._generation += 1
        adoption = FiltrationBodyAdoption(
            adoption_id=_adoption_id(
                self._generation,
                session_id,
                epoch_identity,
                adopted_at,
            ),
            epoch_identity=epoch_identity,
            reason_code=reason_code,
            adopted_at=adopted_at,
        )
        lease = FiltrationCirculationLease(
            lease_id=_lease_id(self._generation, session_id, adopted_at),
            generation=self._generation,
            session_id=session_id,
            pool_pump_circuit_id=pool_pump_circuit_id,
            established_at=adopted_at,
            last_confirmed_at=adopted_at,
            body_adoption=adoption,
            body_verified=True,
        )
        self.filtration_lease = lease
        self.owner = PoolCirculationOwner.FILTRATION_ACQUIRING
        return lease

    def record_filtration_delivery(
        self,
        *,
        session_id: str,
        pool_pump_circuit_id: str,
        accepted_at: datetime,
        provenance: ThermalRuntimeConceptProvenance,
    ) -> FiltrationCirculationLease:
        """Record one accepted filtration operation; never inspect hardware."""

        _require_aware(accepted_at)
        if not is_pmpcirc_native_id(pool_pump_circuit_id):
            raise ValueError("filtration delivery requires a concrete Pool PMPCIRC")
        lease = self.filtration_lease
        if self.owner not in {
            PoolCirculationOwner.NONE,
            PoolCirculationOwner.FILTRATION_ACQUIRING,
            PoolCirculationOwner.FILTRATION,
        }:
            raise ValueError("filtration cannot acquire circulation owned by thermal")
        if lease is None:
            self._generation += 1
            lease = FiltrationCirculationLease(
                lease_id=_lease_id(self._generation, session_id, accepted_at),
                generation=self._generation,
                session_id=session_id,
                pool_pump_circuit_id=pool_pump_circuit_id,
                established_at=accepted_at,
                last_confirmed_at=accepted_at,
            )
        elif lease.session_id != session_id:
            raise ValueError("filtration session cannot replace an active lease")
        elif lease.pool_pump_circuit_id != pool_pump_circuit_id:
            raise ValueError("filtration session cannot change Pool PMPCIRC identity")
        if provenance.concept is ThermalRuntimeOwnedConcept.BODY_ACTIVATION:
            if provenance.intended_value is not True:
                raise ValueError("filtration body provenance must activate Pool")
            lease = replace(
                lease,
                body_activation=provenance,
                body_adoption=None,
                last_confirmed_at=accepted_at,
            )
        elif provenance.concept is ThermalRuntimeOwnedConcept.PUMP_SETPOINT:
            if (
                type(provenance.intended_value) is not int
                or provenance.intended_value < 1
            ):
                raise ValueError("filtration pump provenance must be a positive RPM")
            lease = replace(
                lease,
                pump_setpoint=provenance,
                pump_established_at=accepted_at,
                pump_session_id=None,
                pump_session_effective_rpm=None,
                last_confirmed_at=accepted_at,
            )
        else:
            raise ValueError("filtration may own only Pool body and pump concepts")
        self.filtration_lease = lease
        self.owner = PoolCirculationOwner.FILTRATION_ACQUIRING
        return lease

    def confirm_filtration_body(
        self,
        *,
        session_id: str,
        confirmed_at: datetime,
    ) -> None:
        """Confirm a delivered body activation without claiming full ownership."""

        _require_aware(confirmed_at)
        lease = self.filtration_lease
        if lease is None or lease.session_id != session_id:
            raise ValueError("filtration body confirmation requires the current lease")
        if lease.body_activation is None:
            raise ValueError("filtration body confirmation requires body provenance")
        self.filtration_lease = replace(
            lease,
            body_verified=True,
            last_confirmed_at=confirmed_at,
        )
        if self.filtration_lease.verified:
            self.owner = PoolCirculationOwner.FILTRATION

    def confirm_filtration(self, *, session_id: str, confirmed_at: datetime) -> None:
        _require_aware(confirmed_at)
        lease = self.filtration_lease
        if lease is None or lease.session_id != session_id:
            raise ValueError("filtration confirmation requires the current lease")
        if (
            lease.body_activation is None
            and lease.body_adoption is None
        ) or lease.pump_setpoint is None:
            raise ValueError("filtration confirmation requires body and pump provenance")
        if not lease.body_verified:
            raise ValueError("filtration confirmation requires verified body activation")
        self.filtration_lease = replace(
            lease,
            verified=True,
            last_confirmed_at=confirmed_at,
        )
        self.owner = PoolCirculationOwner.FILTRATION

    def retain_body_for_pump_session_requirement(
        self,
        *,
        session_id: str,
        pump_circuit_id: str,
        pump_session_id: str,
        effective_rpm: int,
        confirmed_at: datetime,
    ) -> None:
        """Relinquish only pump provenance to one exact session requirement."""

        _require_aware(confirmed_at)
        lease = self.filtration_lease
        if (
            lease is None
            or lease.session_id != session_id
            or lease.pool_pump_circuit_id != pump_circuit_id
            or not lease.verified
            or self.owner not in {
                PoolCirculationOwner.FILTRATION,
                PoolCirculationOwner.FILTRATION_SUSPENDED,
            }
            or type(effective_rpm) is not int
            or effective_rpm < 1
            or not pump_session_id.strip()
        ):
            raise ValueError("pump override requires current verified filtration")
        self.filtration_lease = replace(
            lease,
            pump_setpoint=None,
            pump_established_at=None,
            pump_session_id=pump_session_id,
            pump_session_effective_rpm=effective_rpm,
            last_confirmed_at=confirmed_at,
        )

    def suspend_filtration(self, *, session_id: str) -> None:
        """Retain verified provenance while current evidence is unusable."""

        lease = self.filtration_lease
        if lease is None or lease.session_id != session_id or not lease.verified:
            raise ValueError("filtration suspension requires the verified lease")
        if self.owner not in {
            PoolCirculationOwner.FILTRATION,
            PoolCirculationOwner.FILTRATION_SUSPENDED,
        }:
            raise ValueError("only the current filtration owner may be suspended")
        self.owner = PoolCirculationOwner.FILTRATION_SUSPENDED

    def resume_filtration(
        self,
        *,
        session_id: str,
        confirmed_at: datetime,
    ) -> None:
        """Resume retained provenance after current hardware is reverified."""

        _require_aware(confirmed_at)
        lease = self.filtration_lease
        if (
            self.owner is not PoolCirculationOwner.FILTRATION_SUSPENDED
            or lease is None
            or lease.session_id != session_id
            or not lease.verified
        ):
            raise ValueError("filtration resumption requires the suspended lease")
        self.filtration_lease = replace(
            lease,
            last_confirmed_at=confirmed_at,
        )
        self.owner = PoolCirculationOwner.FILTRATION

    def begin_filtration_to_thermal(
        self,
        *,
        thermal_purpose_id: str,
        established_at: datetime,
    ) -> FiltrationToThermalHandoff | None:
        """Bind verified filtration body provenance to one thermal successor."""

        lease = self.filtration_lease
        if (
            self.owner is not PoolCirculationOwner.FILTRATION
            or lease is None
            or not lease.verified
            or lease.body_activation is None
            or lease.domain_state(OwnershipDomain.BODY).authority is not OwnershipAuthority.POOLOS
            or self._thermal_reserved_epoch != self._epoch_identity
        ):
            return None
        if established_at < lease.last_confirmed_at:
            return None
        token = FiltrationToThermalHandoff(
            token_id=_handoff_id(lease, thermal_purpose_id, established_at),
            filtration_lease_id=lease.lease_id,
            filtration_generation=lease.generation,
            thermal_purpose_id=thermal_purpose_id,
            established_at=established_at,
            body_activation=lease.body_activation,
            pump_setpoint=(
                lease.pump_setpoint
                if lease.domain_state(OwnershipDomain.PUMP).authority
                is OwnershipAuthority.POOLOS
                else None
            ),
            pump_setpoint_accepted_at=(
                lease.pump_established_at
                if lease.domain_state(OwnershipDomain.PUMP).authority
                is OwnershipAuthority.POOLOS
                else None
            ),
            body_session_id=lease.body_session_id,
            body_session_generation=lease.body_session_generation,
        )
        self.handoff = token
        self.owner = PoolCirculationOwner.FILTRATION_TO_THERMAL
        return token

    def complete_filtration_to_thermal(
        self,
        *,
        token_id: str,
        thermal_lease_id: str,
        recipient: ThermalRuntimeOwnershipManager | None = None,
    ) -> None:
        token = self.handoff
        if token is None or token.token_id != token_id:
            raise ValueError("thermal handoff token is not current")
        lease = self.filtration_lease
        if (lease is None or lease.lease_id != token.filtration_lease_id
                or lease.generation != token.filtration_generation
                or lease.body_session_id != token.body_session_id
                or lease.body_session_generation != token.body_session_generation
                or lease.pump_setpoint != token.pump_setpoint
                or lease.domain_state(OwnershipDomain.BODY).authority is not OwnershipAuthority.POOLOS):
            raise ValueError("thermal handoff body authority is no longer current")
        if not thermal_lease_id.strip():
            raise ValueError("thermal lease identity must not be empty")
        if recipient is not None:
            recipient.receive_verified_filtration_body_transfer(
                token, thermal_lease_id=thermal_lease_id,
            )
        self.filtration_lease = None
        self.handoff = None
        self.thermal_lease_id = thermal_lease_id
        self.owner = PoolCirculationOwner.THERMAL

    def cancel_filtration_to_thermal(self, *, token_id: str) -> None:
        if self.handoff is None or self.handoff.token_id != token_id:
            return
        self.handoff = None
        self.owner = (
            PoolCirculationOwner.FILTRATION
            if self.filtration_lease is not None
            else PoolCirculationOwner.NONE
        )

    def invalidate_filtration_to_thermal(self, *, token_id: str) -> None:
        """Discard both sides when accepted successor delivery cannot be owned."""

        if self.handoff is None or self.handoff.token_id != token_id:
            return
        self.filtration_lease = None
        self.handoff = None
        self.thermal_lease_id = None
        self.owner = PoolCirculationOwner.NONE

    def accept_thermal_to_filtration(
        self,
        *,
        session_id: str,
        pool_pump_circuit_id: str,
        accepted_at: datetime,
        body_activation: ThermalRuntimeConceptProvenance,
        pump_setpoint: ThermalRuntimeConceptProvenance,
        body_session_id: str | None = None,
        body_session_generation: int | None = None,
    ) -> FiltrationCirculationLease:
        """Accept explicit verified thermal cleanup provenance as filtration."""

        _require_aware(accepted_at)
        if not is_pmpcirc_native_id(pool_pump_circuit_id):
            raise ValueError("filtration handoff requires a concrete Pool PMPCIRC")
        if self.owner is not PoolCirculationOwner.THERMAL:
            raise ValueError("thermal-to-filtration requires the current thermal owner")
        if (
            body_activation.concept is not ThermalRuntimeOwnedConcept.BODY_ACTIVATION
            or body_activation.intended_value is not True
        ):
            raise ValueError("thermal handoff requires Pool body activation provenance")
        if (
            pump_setpoint.concept is not ThermalRuntimeOwnedConcept.PUMP_SETPOINT
            or type(pump_setpoint.intended_value) is not int
            or pump_setpoint.intended_value < 1
        ):
            raise ValueError("thermal handoff requires positive pump provenance")
        self._generation += 1
        lease = FiltrationCirculationLease(
            lease_id=_lease_id(self._generation, session_id, accepted_at),
            generation=self._generation,
            session_id=session_id,
            pool_pump_circuit_id=pool_pump_circuit_id,
            established_at=accepted_at,
            last_confirmed_at=accepted_at,
            body_activation=body_activation,
            body_session_id=body_session_id,
            body_session_generation=body_session_generation,
            pump_setpoint=pump_setpoint,
            pump_established_at=accepted_at,
            body_verified=True,
            verified=True,
        )
        self.filtration_lease = lease
        self.thermal_lease_id = None
        self.handoff = None
        self.owner = PoolCirculationOwner.FILTRATION
        return lease

    def mark_thermal_owned(self, thermal_lease_id: str) -> None:
        if not thermal_lease_id.strip():
            raise ValueError("thermal lease identity must not be empty")
        if self.owner not in {
            PoolCirculationOwner.NONE,
            PoolCirculationOwner.THERMAL,
        }:
            raise ValueError("thermal cannot replace another circulation owner")
        self.thermal_lease_id = thermal_lease_id
        self.owner = PoolCirculationOwner.THERMAL

    def release_filtration(self, *, session_id: str) -> None:
        lease = self.filtration_lease
        if lease is None or lease.session_id != session_id:
            return
        self.filtration_lease = None
        self.handoff = None
        self.owner = PoolCirculationOwner.NONE

    def release_thermal(self, *, thermal_lease_id: str | None = None) -> None:
        if thermal_lease_id is not None and self.thermal_lease_id != thermal_lease_id:
            return
        self.thermal_lease_id = None
        if self.filtration_lease is None:
            self.owner = PoolCirculationOwner.NONE

    def unload(self) -> None:
        """Restart/reload reconstructs no ownership and issues no command."""

        self.owner = PoolCirculationOwner.NONE
        self.filtration_lease = None
        self.thermal_lease_id = None
        self.handoff = None
        self._thermal_reserved_epoch = None
        self._epoch_identity = None


def _lease_id(generation: int, session_id: str, at: datetime) -> str:
    payload = f"{generation}|{session_id}|{at.isoformat()}"
    return "filtration-circulation-" + sha256(payload.encode()).hexdigest()[:24]


def _adoption_id(
    generation: int,
    session_id: str,
    epoch_identity: str,
    at: datetime,
) -> str:
    payload = f"{generation}|{session_id}|{epoch_identity}|{at.isoformat()}"
    return "filtration-body-adoption-" + sha256(payload.encode()).hexdigest()[:24]


def _handoff_id(
    lease: FiltrationCirculationLease,
    purpose_id: str,
    at: datetime,
) -> str:
    payload = f"{lease.lease_id}|{lease.generation}|{purpose_id}|{at.isoformat()}"
    return "filtration-to-thermal-" + sha256(payload.encode()).hexdigest()[:24]


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("circulation ownership timestamp must be timezone-aware")


__all__ = [
    "FiltrationBodyAdoption",
    "FiltrationCirculationLease",
    "FiltrationToThermalHandoff",
    "PoolCirculationOwner",
    "PoolCirculationOwnershipRegistry",
]
