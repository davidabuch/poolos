"""Typed in-memory provenance and candidates for Pool circulation cleanup.

This module owns no delivery port and grants no authority.  It separates
retained accepted-command provenance from one authoritative-epoch cleanup
candidate and from a later accepted command awaiting native verification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json

from .circulation_successor import CirculationSuccessorAssessment
from .integration import PoolOperation, SetBodyActive, SetPumpSpeed, ThermalBody
from .thermal_runtime_ownership import (
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeConceptProvenance,
)


class ThermalCirculationCleanupAction(StrEnum):
    BODY_DEACTIVATION = "body_deactivation"
    FILTRATION_PUMP_NORMALIZATION = "filtration_pump_normalization"


@dataclass(frozen=True, slots=True)
class ThermalCirculationCleanupProvenance:
    """Ephemeral concept-specific proof retained after source cleanup."""

    provenance_id: str
    source_entitlement_id: str
    lease_id: str
    generation: int
    body: ThermalBody
    originating_execution_plan_id: str
    originating_lease_established_at: datetime
    established_at: datetime
    body_activation: ThermalRuntimeConceptProvenance | None
    pump_setpoint: ThermalRuntimeConceptProvenance | None

    def __post_init__(self) -> None:
        for name in (
            "provenance_id",
            "source_entitlement_id",
            "lease_id",
            "originating_execution_plan_id",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.generation < 1:
            raise ValueError("cleanup provenance generation must be positive")
        _require_aware(self.originating_lease_established_at, "originating lease")
        _require_aware(self.established_at, "cleanup provenance establishment")
        if self.established_at < self.originating_lease_established_at:
            raise ValueError("cleanup provenance cannot predate originating lease")
        object.__setattr__(self, "body", ThermalBody(self.body))
        if self.body is not ThermalBody.POOL:
            raise ValueError("circulation cleanup is commissioned only for Pool")
        if self.body_activation is None and self.pump_setpoint is None:
            raise ValueError("cleanup provenance requires an owned body or pump concept")

    @classmethod
    def from_residual(
        cls,
        entitlement: ThermalResidualTerminationEntitlement,
        *,
        established_at: datetime,
    ) -> ThermalCirculationCleanupProvenance | None:
        """Copy only circulation provenance; never infer it from hardware."""

        if (
            entitlement.body is not ThermalBody.POOL
            or (
                entitlement.body_activation is None
                and entitlement.pump_setpoint is None
            )
        ):
            return None
        payload = json.dumps(
            {
                "entitlement_id": entitlement.entitlement_id,
                "lease_id": entitlement.lease_id,
                "generation": entitlement.generation,
                "established_at": established_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            provenance_id="thermal-circulation-cleanup-"
            + sha256(payload.encode()).hexdigest()[:24],
            source_entitlement_id=entitlement.entitlement_id,
            lease_id=entitlement.lease_id,
            generation=entitlement.generation,
            body=entitlement.body,
            originating_execution_plan_id=entitlement.originating_execution_plan_id,
            originating_lease_established_at=(
                entitlement.originating_lease_established_at
            ),
            established_at=established_at,
            body_activation=entitlement.body_activation,
            pump_setpoint=entitlement.pump_setpoint,
        )

    def arbitration_entitlement(self) -> ThermalResidualTerminationEntitlement:
        """Project retained proof into the canonical read-only arbitrator input."""

        return ThermalResidualTerminationEntitlement(
            entitlement_id=self.provenance_id,
            lease_id=self.lease_id,
            generation=self.generation,
            body=self.body,
            originating_execution_plan_id=self.originating_execution_plan_id,
            originating_lease_established_at=self.originating_lease_established_at,
            retained_at=self.established_at,
            reason_code="thermal_circulation_cleanup_provenance",
            body_activation=self.body_activation,
            pump_setpoint=self.pump_setpoint,
            heat_source=None,
        )

    def without_pump(self) -> ThermalCirculationCleanupProvenance | None:
        """Consume only pump cleanup capability after verified normalization."""

        if self.body_activation is None:
            return None
        return replace(self, pump_setpoint=None)


@dataclass(frozen=True, slots=True)
class ThermalCirculationCleanupCandidate:
    """One command-free cleanup decision bound to one authoritative epoch."""

    candidate_id: str
    epoch_identity: str
    evaluated_at: datetime
    provenance_id: str
    provenance_generation: int
    action: ThermalCirculationCleanupAction
    operation: PoolOperation
    arbitration_reason_code: str

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "epoch_identity",
            "provenance_id",
            "arbitration_reason_code",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        _require_aware(self.evaluated_at, "cleanup candidate evaluation")
        if self.provenance_generation < 1:
            raise ValueError("cleanup candidate generation must be positive")
        object.__setattr__(
            self,
            "action",
            ThermalCirculationCleanupAction(self.action),
        )
        if self.action is ThermalCirculationCleanupAction.BODY_DEACTIVATION:
            if not (
                isinstance(self.operation, SetBodyActive)
                and self.operation.equipment_id == ThermalBody.POOL.value
                and self.operation.active is False
            ):
                raise ValueError("body cleanup candidate must be exact Pool Off")
        elif not (
            isinstance(self.operation, SetPumpSpeed)
            and self.operation.equipment_id == "p0102"
        ):
            raise ValueError("pump cleanup candidate must target p0102")

    @classmethod
    def from_arbitration(
        cls,
        *,
        provenance: ThermalCirculationCleanupProvenance,
        assessment: CirculationSuccessorAssessment,
        epoch_identity: str,
    ) -> ThermalCirculationCleanupCandidate | None:
        """Create only an operation justified by the canonical assessment."""

        if assessment.evaluated_at < provenance.established_at:
            return None
        if assessment.body_deactivation_eligible:
            action = ThermalCirculationCleanupAction.BODY_DEACTIVATION
            operation: PoolOperation = SetBodyActive(
                equipment_id=ThermalBody.POOL.value,
                active=False,
                metadata={
                    "thermal_circulation_cleanup": True,
                    "cleanup_provenance_id": provenance.provenance_id,
                    "cleanup_action": action.value,
                },
            )
        elif assessment.pump_handoff_eligible:
            target = assessment.filtration_target_rpm
            if target is None:
                return None
            action = ThermalCirculationCleanupAction.FILTRATION_PUMP_NORMALIZATION
            operation = SetPumpSpeed(
                equipment_id="p0102",
                rpm=target,
                metadata={
                    "thermal_circulation_cleanup": True,
                    "cleanup_provenance_id": provenance.provenance_id,
                    "cleanup_action": action.value,
                    "successor": "filtration",
                },
            )
        else:
            return None
        payload = json.dumps(
            {
                "epoch_identity": epoch_identity,
                "provenance_id": provenance.provenance_id,
                "generation": provenance.generation,
                "action": action.value,
                "operation_id": operation.operation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            candidate_id="thermal-cleanup-candidate-"
            + sha256(payload.encode()).hexdigest()[:24],
            epoch_identity=epoch_identity,
            evaluated_at=assessment.evaluated_at,
            provenance_id=provenance.provenance_id,
            provenance_generation=provenance.generation,
            action=action,
            operation=operation,
            arbitration_reason_code=assessment.reason_code,
        )


@dataclass(frozen=True, slots=True)
class ThermalCirculationCleanupAttempt:
    """One accepted cleanup request awaiting later authoritative truth."""

    candidate: ThermalCirculationCleanupCandidate
    correlation_id: str
    delivered_at: datetime
    deadline: datetime

    def __post_init__(self) -> None:
        if not self.correlation_id.strip():
            raise ValueError("cleanup correlation_id must not be empty")
        _require_aware(self.delivered_at, "cleanup delivery")
        _require_aware(self.deadline, "cleanup deadline")
        if self.deadline <= self.delivered_at:
            raise ValueError("cleanup deadline must follow delivery")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} timestamp must be timezone-aware")


__all__ = [
    "ThermalCirculationCleanupAction",
    "ThermalCirculationCleanupAttempt",
    "ThermalCirculationCleanupCandidate",
    "ThermalCirculationCleanupProvenance",
]
