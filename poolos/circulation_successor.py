"""Pure command-free Pool thermal circulation-successor arbitration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .external_change import (
    ExternalChangeBatch,
    POOL_CIRCULATION_TAKEOVER_CONCEPTS,
)
from .filtration_policy import FiltrationAccountingSnapshot, FiltrationDisposition
from .grid_outage_confirmation import GridOutageAssessment, GridOutageDisposition
from .integration import PhysicalHeatMode, ThermalBody
from .thermal_runtime_ownership import (
    SHARED_HYDRAULIC_SAFETY_BY_CONCEPT,
    SharedHydraulicCircuitEvidence,
    SharedHydraulicSafetyClass,
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeOwnershipEvidence,
)


class CirculationOrigin(StrEnum):
    POOLOS_THERMAL = "poolos_thermal"
    PREEXISTING_OR_EXTERNAL = "preexisting_or_external"
    UNKNOWN = "unknown"


class CirculationSuccessorKind(StrEnum):
    NONE = "none"
    FILTRATION = "filtration"
    PREEXISTING_OR_EXTERNAL = "preexisting_or_external"
    SHARED_HYDRAULICS = "shared_hydraulics"
    SPA_OR_TOPOLOGY = "spa_or_topology"
    UNKNOWN = "unknown"


class CirculationArbitrationDisposition(StrEnum):
    EXCLUSIVE_THERMAL = "exclusive_thermal"
    RETAIN_FOR_SUCCESSOR = "retain_for_successor"
    RETAIN_PREEXISTING = "retain_preexisting"
    BLOCKED = "blocked"


class FiltrationTargetSemantics(StrEnum):
    NONE = "none"
    ORDINARY_POLICY_BASELINE = "ordinary_policy_baseline"


@dataclass(frozen=True, slots=True)
class FiltrationSuccessorEvidence:
    """Separate canonical filtration debt, immediate need, and target facts."""

    evaluated_at: datetime
    disposition: FiltrationDisposition
    total_remaining_runtime: timedelta
    currently_earning_credit: bool
    immediate_circulation_required: bool
    successor_target_rpm: int | None
    target_semantics: FiltrationTargetSemantics
    authority: str = "none"
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "filtration evaluated_at")
        if self.total_remaining_runtime < timedelta(0):
            raise ValueError("filtration remaining runtime must not be negative")
        if self.successor_target_rpm is not None and self.successor_target_rpm <= 0:
            raise ValueError("filtration successor target must be positive")
        if self.authority != "none" or self.command_delivery_enabled:
            raise ValueError("filtration successor evidence must be command-disabled")
        if self.immediate_circulation_required != (
            self.disposition in {FiltrationDisposition.CREDITING, FiltrationDisposition.RUN_NOW}
        ):
            raise ValueError("immediate need must match canonical filtration disposition")
        if self.currently_earning_credit != (
            self.disposition is FiltrationDisposition.CREDITING
        ):
            raise ValueError("earning-credit state must match canonical disposition")
        if (self.disposition is FiltrationDisposition.SATISFIED) != (
            self.total_remaining_runtime == timedelta(0)
        ):
            raise ValueError("satisfied filtration state must match zero remaining debt")
        if self.successor_target_rpm is not None and not self.immediate_circulation_required:
            raise ValueError("filtration target requires immediate circulation need")
        if (self.successor_target_rpm is None) != (
            self.target_semantics is FiltrationTargetSemantics.NONE
        ):
            raise ValueError("filtration target and target semantics must agree")

    @classmethod
    def from_accounting(
        cls,
        assessment: FiltrationAccountingSnapshot,
        *,
        include_target: bool = True,
    ) -> FiltrationSuccessorEvidence:
        immediate = assessment.disposition in {
            FiltrationDisposition.CREDITING,
            FiltrationDisposition.RUN_NOW,
        }
        target = assessment.ordinary_filtration_rpm if immediate and include_target else None
        return cls(
            evaluated_at=assessment.evaluated_at,
            disposition=assessment.disposition,
            total_remaining_runtime=assessment.total_remaining_runtime,
            currently_earning_credit=assessment.currently_earning_credit,
            immediate_circulation_required=immediate,
            successor_target_rpm=target,
            target_semantics=(
                FiltrationTargetSemantics.ORDINARY_POLICY_BASELINE
                if target is not None
                else FiltrationTargetSemantics.NONE
            ),
        )


@dataclass(frozen=True, slots=True)
class CirculationSuccessorAssessment:
    evaluated_at: datetime
    target_body: ThermalBody
    disposition: CirculationArbitrationDisposition
    successor_kind: CirculationSuccessorKind
    reason_code: str
    circulation_origin: CirculationOrigin
    residual_entitlement_present: bool
    body_activation_provenance_present: bool
    body_provenance_current: bool
    pool_activity_current: bool
    spa_activity_current: bool
    source_cleanup_complete: bool
    filtration_disposition: FiltrationDisposition | None
    filtration_debt_present: bool | None
    filtration_immediate_need: bool | None
    filtration_evidence_current: bool
    filtration_target_rpm: int | None
    filtration_target_semantics: FiltrationTargetSemantics
    grid_disposition: GridOutageDisposition | None
    grid_evidence_current: bool
    shared_hydraulic_blocker: str | None
    shared_hydraulic_evidence_current: bool
    external_takeover: bool
    topology_conflict: bool
    keep_body_active: bool
    body_deactivation_eligible: bool
    pump_handoff_eligible: bool
    physical_handoff_ready: bool
    critical_evidence_current: bool
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "arbitration evaluated_at")
        if not self.reason_code.strip():
            raise ValueError("arbitration reason_code must not be empty")
        if self.command_delivery_enabled:
            raise ValueError("circulation arbitration must remain command-disabled")
        if self.body_deactivation_eligible and (
            self.disposition is not CirculationArbitrationDisposition.EXCLUSIVE_THERMAL
            or self.keep_body_active
        ):
            raise ValueError("body eligibility requires exclusive thermal circulation")
        if self.physical_handoff_ready and not self.pump_handoff_eligible:
            raise ValueError("physical readiness requires pump handoff eligibility")

    def diagnostics(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "circulation_arbitration_disposition": self.disposition.value,
                "circulation_target_body": self.target_body.value,
                "circulation_successor_kind": self.successor_kind.value,
                "circulation_arbitration_reason_code": self.reason_code,
                "circulation_origin": self.circulation_origin.value,
                "circulation_residual_entitlement_present": self.residual_entitlement_present,
                "circulation_body_activation_provenance_present": self.body_activation_provenance_present,
                "circulation_body_provenance_current": self.body_provenance_current,
                "circulation_pool_activity_current": self.pool_activity_current,
                "circulation_spa_activity_current": self.spa_activity_current,
                "circulation_source_cleanup_complete": self.source_cleanup_complete,
                "filtration_disposition": (
                    None
                    if self.filtration_disposition is None
                    else self.filtration_disposition.value
                ),
                "filtration_debt_present": self.filtration_debt_present,
                "filtration_immediate_successor_need": self.filtration_immediate_need,
                "filtration_successor_evidence_current": self.filtration_evidence_current,
                "filtration_successor_target_rpm": self.filtration_target_rpm,
                "filtration_successor_target_semantics": self.filtration_target_semantics.value,
                "circulation_grid_disposition": (
                    None
                    if self.grid_disposition is None
                    else self.grid_disposition.value
                ),
                "circulation_grid_evidence_current": self.grid_evidence_current,
                "circulation_shared_hydraulic_blocker": self.shared_hydraulic_blocker,
                "circulation_shared_hydraulic_evidence_current": self.shared_hydraulic_evidence_current,
                "circulation_external_takeover": self.external_takeover,
                "circulation_topology_conflict": self.topology_conflict,
                "circulation_keep_body_active": self.keep_body_active,
                "body_deactivation_eligible": self.body_deactivation_eligible,
                "pump_handoff_eligible": self.pump_handoff_eligible,
                "physical_handoff_ready": self.physical_handoff_ready,
                "circulation_critical_evidence_current": self.critical_evidence_current,
                "circulation_arbitration_evaluated_at": self.evaluated_at.isoformat(),
                "circulation_command_delivery_enabled": False,
            }
        )


class CirculationSuccessorArbitrator:
    """Answer whether Pool thermal circulation has a current successor."""

    pump_rpm_tolerance = 25

    def evaluate(
        self,
        *,
        entitlement: ThermalResidualTerminationEntitlement | None,
        evidence: ThermalRuntimeOwnershipEvidence,
        filtration: FiltrationSuccessorEvidence | None,
        outage: GridOutageAssessment | None,
    ) -> CirculationSuccessorAssessment:
        facts = _facts(entitlement, evidence, filtration, outage)
        at = evidence.evaluated_at
        if entitlement is not None and entitlement.body is not ThermalBody.POOL:
            return _blocked(at, "circulation_hot_tub_not_commissioned", facts)
        if entitlement is None or entitlement.body_activation is None:
            return _result(
                at,
                CirculationArbitrationDisposition.RETAIN_PREEXISTING,
                CirculationSuccessorKind.PREEXISTING_OR_EXTERNAL,
                "circulation_retained_preexisting_or_external",
                CirculationOrigin.PREEXISTING_OR_EXTERNAL,
                facts,
            )
        if evidence.evaluated_at < entitlement.retained_at:
            return _blocked(at, "circulation_entitlement_temporal_regression", facts)
        if outage is None or outage.evaluated_at != at:
            return _blocked(at, "circulation_grid_evidence_not_current", facts)
        if outage.disposition is not GridOutageDisposition.ON_GRID:
            return _blocked(at, "circulation_grid_state_not_on_grid", facts)
        if not facts.pool_activity_current or not facts.spa_activity_current:
            return _blocked(at, "circulation_body_activity_evidence_not_current", facts)
        if evidence.pool_active is not True or evidence.spa_active is not False:
            return _blocked(
                at,
                "circulation_pool_topology_not_exclusive",
                facts,
                successor=CirculationSuccessorKind.SPA_OR_TOPOLOGY,
            )
        if not facts.shared_hydraulic_evidence_current:
            return _blocked(at, "circulation_shared_hydraulic_evidence_not_current", facts)
        if facts.shared_hydraulic_blocker is not None:
            return _result(
                at,
                CirculationArbitrationDisposition.RETAIN_FOR_SUCCESSOR,
                CirculationSuccessorKind.SHARED_HYDRAULICS,
                f"circulation_retained_shared_hydraulics:{facts.shared_hydraulic_blocker}",
                CirculationOrigin.POOLOS_THERMAL,
                facts,
            )
        if facts.external_takeover:
            return _result(
                at,
                CirculationArbitrationDisposition.RETAIN_PREEXISTING,
                CirculationSuccessorKind.PREEXISTING_OR_EXTERNAL,
                "circulation_retained_external_takeover",
                CirculationOrigin.PREEXISTING_OR_EXTERNAL,
                facts,
            )
        if not facts.body_provenance_current:
            return _blocked(at, "circulation_body_provenance_not_current", facts)
        if not facts.source_cleanup_complete:
            return _blocked(at, "circulation_source_cleanup_not_complete", facts)
        if filtration is None or not facts.filtration_evidence_current:
            return _blocked(at, "circulation_filtration_evidence_not_current", facts)
        if filtration.disposition is FiltrationDisposition.EVIDENCE_UNAVAILABLE:
            return _blocked(at, "circulation_filtration_evidence_unavailable", facts)
        if filtration.immediate_circulation_required:
            pump_eligible = _pump_handoff_eligible(entitlement, evidence, filtration)
            return _result(
                at,
                CirculationArbitrationDisposition.RETAIN_FOR_SUCCESSOR,
                CirculationSuccessorKind.FILTRATION,
                "circulation_retained_for_immediate_filtration",
                CirculationOrigin.POOLOS_THERMAL,
                facts,
                pump_handoff_eligible=pump_eligible,
                physical_handoff_ready=pump_eligible,
            )
        return _result(
            at,
            CirculationArbitrationDisposition.EXCLUSIVE_THERMAL,
            CirculationSuccessorKind.NONE,
            "circulation_exclusive_thermal_future_deactivation_eligible",
            CirculationOrigin.POOLOS_THERMAL,
            facts,
            keep_body_active=False,
            body_deactivation_eligible=True,
        )


@dataclass(frozen=True, slots=True)
class _Facts:
    entitlement_present: bool
    body_provenance_present: bool
    body_provenance_current: bool
    pool_activity_current: bool
    spa_activity_current: bool
    source_cleanup_complete: bool
    filtration_disposition: FiltrationDisposition | None
    filtration_debt_present: bool | None
    filtration_immediate_need: bool | None
    filtration_evidence_current: bool
    filtration_target_rpm: int | None
    filtration_target_semantics: FiltrationTargetSemantics
    grid_disposition: GridOutageDisposition | None
    grid_evidence_current: bool
    shared_hydraulic_blocker: str | None
    shared_hydraulic_evidence_current: bool
    external_takeover: bool
    topology_conflict: bool


def _facts(
    entitlement: ThermalResidualTerminationEntitlement | None,
    evidence: ThermalRuntimeOwnershipEvidence,
    filtration: FiltrationSuccessorEvidence | None,
    outage: GridOutageAssessment | None,
) -> _Facts:
    retained_at = None if entitlement is None else entitlement.retained_at
    pool_current = _current(
        evidence.pool_activity_observed_at,
        evidence.evaluated_at,
        retained_at,
        evidence.pool_activity_fresh,
        evidence.pool_activity_usable,
    )
    spa_current = _current(
        evidence.spa_activity_observed_at,
        evidence.evaluated_at,
        retained_at,
        evidence.spa_activity_fresh,
        evidence.spa_activity_usable,
    )
    required_shared = {
        concept
        for concept, safety_class in SHARED_HYDRAULIC_SAFETY_BY_CONCEPT.items()
        if safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING
    }
    supplied_shared = {
        item.concept
        for item in evidence.shared_hydraulic_circuits
        if item.safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING
    }
    shared_current = (
        evidence.shared_hydraulic_inventory_complete
        and supplied_shared == required_shared
        and all(
            item.safety_class is not SharedHydraulicSafetyClass.UNKNOWN
            and _circuit_current(item, evidence.evaluated_at, retained_at)
            for item in evidence.shared_hydraulic_circuits
            if item.safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING
        )
    )
    shared = next(
        (
            item.concept
            for item in evidence.shared_hydraulic_circuits
            if item.active is True
            and item.safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING
        ),
        None,
    )
    source_current = _current(
        evidence.heat_source_observed_at,
        evidence.evaluated_at,
        retained_at,
        evidence.heat_source_observation_fresh,
        evidence.heat_source_observation_usable,
    )
    filtration_current = filtration is not None and filtration.evaluated_at == evidence.evaluated_at
    return _Facts(
        entitlement_present=entitlement is not None,
        body_provenance_present=bool(entitlement and entitlement.body_activation),
        body_provenance_current=bool(
            entitlement
            and entitlement.body_activation
            and evidence.evaluated_at >= entitlement.retained_at
            and pool_current
            and spa_current
        ),
        pool_activity_current=pool_current,
        spa_activity_current=spa_current,
        source_cleanup_complete=(
            source_current and evidence.effective_heat_source is PhysicalHeatMode.OFF
        ),
        filtration_disposition=None if filtration is None else filtration.disposition,
        filtration_debt_present=(
            None if filtration is None else filtration.total_remaining_runtime > timedelta(0)
        ),
        filtration_immediate_need=(
            None if filtration is None else filtration.immediate_circulation_required
        ),
        filtration_evidence_current=filtration_current,
        filtration_target_rpm=None if filtration is None else filtration.successor_target_rpm,
        filtration_target_semantics=(
            FiltrationTargetSemantics.NONE if filtration is None else filtration.target_semantics
        ),
        grid_disposition=None if outage is None else outage.disposition,
        grid_evidence_current=(
            outage is not None and outage.evaluated_at == evidence.evaluated_at
        ),
        shared_hydraulic_blocker=shared,
        shared_hydraulic_evidence_current=shared_current,
        external_takeover=_external_takeover(
            entitlement, evidence.external_changes, evidence.evaluated_at
        ),
        topology_conflict=(evidence.pool_active is not True or evidence.spa_active is not False),
    )


def _external_takeover(
    entitlement: ThermalResidualTerminationEntitlement | None,
    changes: ExternalChangeBatch,
    evaluated_at: datetime,
) -> bool:
    if entitlement is None:
        return False
    return any(
        event.concept in POOL_CIRCULATION_TAKEOVER_CONCEPTS
        and entitlement.originating_lease_established_at <= event.observed_at <= evaluated_at
        for event in changes.events
    )


def _pump_handoff_eligible(
    entitlement: ThermalResidualTerminationEntitlement,
    evidence: ThermalRuntimeOwnershipEvidence,
    filtration: FiltrationSuccessorEvidence,
) -> bool:
    pump = entitlement.pump_setpoint
    if pump is None or filtration.successor_target_rpm is None:
        return False
    intended = pump.intended_value
    if not isinstance(intended, int) or isinstance(intended, bool):
        return False
    if not all(
        (
            _current(
                evidence.pump_observed_at,
                evidence.evaluated_at,
                entitlement.retained_at,
                evidence.pump_observation_fresh,
                evidence.pump_observation_usable,
            ),
            _current(
                evidence.configured_pump_speed_observed_at,
                evidence.evaluated_at,
                entitlement.retained_at,
                evidence.configured_pump_speed_observation_fresh,
                evidence.configured_pump_speed_observation_usable,
            ),
        )
    ):
        return False
    return bool(
        evidence.pump_rpm is not None
        and evidence.configured_pump_speed_rpm is not None
        and abs(evidence.pump_rpm - intended) <= CirculationSuccessorArbitrator.pump_rpm_tolerance
        and abs(evidence.configured_pump_speed_rpm - intended)
        <= CirculationSuccessorArbitrator.pump_rpm_tolerance
    )


def _circuit_current(
    item: SharedHydraulicCircuitEvidence, at: datetime, retained_at: datetime | None
) -> bool:
    return item.active is not None and _current(
        item.observed_at, at, retained_at, item.fresh, item.usable
    )


def _current(
    observed_at: datetime | None,
    at: datetime,
    retained_at: datetime | None,
    fresh: bool,
    usable: bool,
) -> bool:
    return bool(
        fresh
        and usable
        and observed_at is not None
        and observed_at <= at
        and (retained_at is None or observed_at >= retained_at)
    )


def _blocked(
    at: datetime,
    reason: str,
    facts: _Facts,
    *,
    successor: CirculationSuccessorKind = CirculationSuccessorKind.UNKNOWN,
) -> CirculationSuccessorAssessment:
    return _result(
        at,
        CirculationArbitrationDisposition.BLOCKED,
        successor,
        reason,
        CirculationOrigin.UNKNOWN,
        facts,
    )


def _result(
    at: datetime,
    disposition: CirculationArbitrationDisposition,
    successor: CirculationSuccessorKind,
    reason: str,
    origin: CirculationOrigin,
    facts: _Facts,
    *,
    keep_body_active: bool = True,
    body_deactivation_eligible: bool = False,
    pump_handoff_eligible: bool = False,
    physical_handoff_ready: bool = False,
) -> CirculationSuccessorAssessment:
    return CirculationSuccessorAssessment(
        evaluated_at=at,
        target_body=ThermalBody.POOL,
        disposition=disposition,
        successor_kind=successor,
        reason_code=reason,
        circulation_origin=origin,
        residual_entitlement_present=facts.entitlement_present,
        body_activation_provenance_present=facts.body_provenance_present,
        body_provenance_current=facts.body_provenance_current,
        pool_activity_current=facts.pool_activity_current,
        spa_activity_current=facts.spa_activity_current,
        source_cleanup_complete=facts.source_cleanup_complete,
        filtration_disposition=facts.filtration_disposition,
        filtration_debt_present=facts.filtration_debt_present,
        filtration_immediate_need=facts.filtration_immediate_need,
        filtration_evidence_current=facts.filtration_evidence_current,
        filtration_target_rpm=facts.filtration_target_rpm,
        filtration_target_semantics=facts.filtration_target_semantics,
        grid_disposition=facts.grid_disposition,
        grid_evidence_current=facts.grid_evidence_current,
        shared_hydraulic_blocker=facts.shared_hydraulic_blocker,
        shared_hydraulic_evidence_current=facts.shared_hydraulic_evidence_current,
        external_takeover=facts.external_takeover,
        topology_conflict=facts.topology_conflict,
        keep_body_active=keep_body_active,
        body_deactivation_eligible=body_deactivation_eligible,
        pump_handoff_eligible=pump_handoff_eligible,
        physical_handoff_ready=physical_handoff_ready,
        critical_evidence_current=(
            facts.pool_activity_current
            and facts.spa_activity_current
            and facts.shared_hydraulic_evidence_current
            and facts.filtration_evidence_current
            and facts.grid_evidence_current
            and facts.source_cleanup_complete
            and facts.body_provenance_current
        ),
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = [
    "CirculationArbitrationDisposition",
    "CirculationOrigin",
    "CirculationSuccessorArbitrator",
    "CirculationSuccessorAssessment",
    "CirculationSuccessorKind",
    "FiltrationSuccessorEvidence",
    "FiltrationTargetSemantics",
]
