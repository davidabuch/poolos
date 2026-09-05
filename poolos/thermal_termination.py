"""Command-free, ownership-scoped thermal termination decisions.

Termination is deliberately smaller than normal thermal execution.  It may
only de-select a still-attributable Pool heat source.  Pump and body effects
are relinquished without writes because PoolOS has no authoritative successor
execution owner capable of proving that circulation may stop or which RPM it
should assume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypedDict

from .integration import PhysicalHeatMode, SetHeatMode, ThermalBody
from .thermal_runtime_ownership import (
    SharedHydraulicSafetyClass,
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeOwnershipEvidence,
)


class ThermalTerminationDisposition(StrEnum):
    """Current result of evaluating one residual entitlement."""

    NO_ENTITLEMENT = "no_entitlement"
    SOURCE_OFF_READY = "source_off_ready"
    RELINQUISH_ONLY = "relinquish_only"
    BLOCKED = "blocked"
    INVALIDATED = "invalidated"


class ThermalTerminationSourceAction(StrEnum):
    NONE = "none"
    SET_OFF = "set_off"
    ALREADY_OFF = "already_off"


class ThermalTerminationPumpAction(StrEnum):
    NONE = "none"
    RELINQUISH = "relinquish"


class ThermalTerminationBodyAction(StrEnum):
    NONE = "none"
    KEEP_ACTIVE = "keep_active"


class _CommonAssessment(TypedDict):
    entitlement_id: str
    entitlement_generation: int
    body: ThermalBody
    pump_action: ThermalTerminationPumpAction
    body_action: ThermalTerminationBodyAction


@dataclass(frozen=True, slots=True)
class ThermalTerminationAssessment:
    """Bounded, non-authorizing decision for one current observation epoch."""

    disposition: ThermalTerminationDisposition
    reason_code: str
    entitlement_id: str | None
    entitlement_generation: int | None
    body: ThermalBody | None
    source_action: ThermalTerminationSourceAction
    pump_action: ThermalTerminationPumpAction
    body_action: ThermalTerminationBodyAction
    operation: SetHeatMode | None = None
    monotonic: bool = True
    physical_action_required: bool = False
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("termination reason_code must not be empty")
        if self.command_delivery_enabled:
            raise ValueError("termination assessment must remain command-disabled")
        if self.operation is not None:
            if (
                self.operation.mode is not PhysicalHeatMode.OFF
                or self.body is not ThermalBody.POOL
                or self.operation.equipment_id != ThermalBody.POOL.value
            ):
                raise ValueError("termination operation must be Pool heat source Off")
            if not self.monotonic:
                raise ValueError("termination operation must be monotonic")
        if self.physical_action_required != (self.operation is not None):
            raise ValueError("physical action flag must match termination operation")


class ThermalTerminationPolicy:
    """Evaluate residual provenance against fresh authoritative current truth."""

    pump_rpm_tolerance = 25

    def evaluate(
        self,
        entitlement: ThermalResidualTerminationEntitlement | None,
        evidence: ThermalRuntimeOwnershipEvidence,
        *,
        desired_source: PhysicalHeatMode,
        verification_after: datetime | None = None,
    ) -> ThermalTerminationAssessment:
        if verification_after is not None and verification_after.tzinfo is None:
            raise ValueError("termination verification timestamp must be timezone-aware")
        if entitlement is None:
            return _assessment(
                ThermalTerminationDisposition.NO_ENTITLEMENT,
                "thermal_termination_no_residual_entitlement",
            )
        common: _CommonAssessment = dict(
            entitlement_id=entitlement.entitlement_id,
            entitlement_generation=entitlement.generation,
            body=entitlement.body,
            pump_action=(
                ThermalTerminationPumpAction.RELINQUISH
                if entitlement.pump_setpoint is not None
                else ThermalTerminationPumpAction.NONE
            ),
            body_action=(
                ThermalTerminationBodyAction.KEEP_ACTIVE
                if entitlement.body_activation is not None
                else ThermalTerminationBodyAction.NONE
            ),
        )
        if evidence.evaluated_at < entitlement.retained_at:
            return _assessment(
                ThermalTerminationDisposition.BLOCKED,
                "thermal_termination_evidence_temporal_regression",
                **common,
            )
        hydraulic = _hydraulic_blocker(entitlement, evidence)
        if hydraulic is not None:
            return _assessment(
                ThermalTerminationDisposition.INVALIDATED,
                hydraulic,
                **common,
            )
        external = _external_takeover(entitlement, evidence)
        if external is not None:
            return _assessment(
                ThermalTerminationDisposition.INVALIDATED,
                external,
                **common,
            )
        pump = entitlement.pump_setpoint
        if pump is not None:
            if (
                evidence.pump_rpm is None
                or evidence.configured_pump_speed_rpm is None
                or not evidence.pump_observation_fresh
                or not evidence.pump_observation_usable
                or not evidence.configured_pump_speed_observation_fresh
                or not evidence.configured_pump_speed_observation_usable
            ):
                return _assessment(
                    ThermalTerminationDisposition.BLOCKED,
                    "thermal_termination_pump_evidence_unusable",
                    **common,
                )
            intended_rpm = pump.intended_value
            assert isinstance(intended_rpm, int) and not isinstance(intended_rpm, bool)
            if (
                abs(evidence.pump_rpm - intended_rpm) > self.pump_rpm_tolerance
                or abs(evidence.configured_pump_speed_rpm - intended_rpm)
                > self.pump_rpm_tolerance
            ):
                return _assessment(
                    ThermalTerminationDisposition.INVALIDATED,
                    "thermal_termination_pump_external_takeover",
                    **common,
                )
        source = entitlement.heat_source
        if source is None:
            return _assessment(
                ThermalTerminationDisposition.RELINQUISH_ONLY,
                "thermal_termination_no_owned_active_source",
                **common,
            )
        if (
            evidence.effective_heat_source is None
            or not evidence.heat_source_observation_fresh
            or not evidence.heat_source_observation_usable
        ):
            return _assessment(
                ThermalTerminationDisposition.BLOCKED,
                "thermal_termination_source_evidence_unusable",
                **common,
            )
        if evidence.effective_heat_source is PhysicalHeatMode.OFF:
            if (
                verification_after is not None
                and (
                    evidence.heat_source_observed_at is None
                    or evidence.heat_source_observed_at <= verification_after
                )
            ):
                return _assessment(
                    ThermalTerminationDisposition.BLOCKED,
                    "thermal_termination_source_observation_not_post_delivery",
                    **common,
                )
            return _assessment(
                ThermalTerminationDisposition.RELINQUISH_ONLY,
                "thermal_termination_source_already_off",
                source_action=ThermalTerminationSourceAction.ALREADY_OFF,
                **common,
            )
        if evidence.effective_heat_source is not source.intended_value:
            return _assessment(
                ThermalTerminationDisposition.INVALIDATED,
                "thermal_termination_source_external_takeover",
                **common,
            )
        if desired_source is not PhysicalHeatMode.OFF:
            return _assessment(
                ThermalTerminationDisposition.RELINQUISH_ONLY,
                "thermal_termination_current_policy_still_requires_heat_source",
                **common,
            )
        if entitlement.body is not ThermalBody.POOL:
            return _assessment(
                ThermalTerminationDisposition.BLOCKED,
                "thermal_termination_hot_tub_not_commissioned",
                **common,
            )
        operation = SetHeatMode(
            equipment_id=ThermalBody.POOL.value,
            mode=PhysicalHeatMode.OFF,
            metadata={
                "thermal_termination": True,
                "residual_entitlement_id": entitlement.entitlement_id,
                "residual_generation": entitlement.generation,
            },
        )
        return _assessment(
            ThermalTerminationDisposition.SOURCE_OFF_READY,
            "thermal_termination_owned_source_off_ready",
            source_action=ThermalTerminationSourceAction.SET_OFF,
            operation=operation,
            physical_action_required=True,
            **common,
        )


def _hydraulic_blocker(
    entitlement: ThermalResidualTerminationEntitlement,
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
        if value is None or not fresh or not usable:
            return f"thermal_termination_{prefix}_activity_unusable"
    if evidence.pool_active and evidence.spa_active:
        return "thermal_termination_body_topology_contradictory"
    if entitlement.body is ThermalBody.POOL:
        if evidence.pool_active is not True or evidence.spa_active is not False:
            return "thermal_termination_pool_topology_lost"
    else:
        if evidence.spa_active is not True or evidence.pool_active is not False:
            return "thermal_termination_hot_tub_topology_lost"
    if not evidence.shared_hydraulic_inventory_complete:
        return "thermal_termination_shared_hydraulic_evidence_incomplete"
    for item in evidence.shared_hydraulic_circuits:
        if item.active is None or not item.fresh or not item.usable:
            return f"thermal_termination_shared_hydraulic_unusable:{item.concept}"
        if item.active and item.safety_class is not SharedHydraulicSafetyClass.NON_CONFLICTING:
            return f"thermal_termination_shared_hydraulic_takeover:{item.concept}"
    return None


def _external_takeover(
    entitlement: ThermalResidualTerminationEntitlement,
    evidence: ThermalRuntimeOwnershipEvidence,
) -> str | None:
    prefix = "pool" if entitlement.body is ThermalBody.POOL else "spa"
    concepts = set()
    if entitlement.body_activation is not None:
        concepts.add(f"{prefix}.active")
    if entitlement.pump_setpoint is not None:
        concepts.add("pump.rpm")
    if entitlement.heat_source is not None:
        concepts.add(f"{prefix}.raw_heater_id")
    for event in evidence.external_changes.events:
        if (
            event.observed_at >= entitlement.originating_lease_established_at
            and event.concept in concepts
        ):
            return f"thermal_termination_external_takeover:{event.concept}"
    return None


def _assessment(
    disposition: ThermalTerminationDisposition,
    reason: str,
    *,
    entitlement_id: str | None = None,
    entitlement_generation: int | None = None,
    body: ThermalBody | None = None,
    source_action: ThermalTerminationSourceAction = ThermalTerminationSourceAction.NONE,
    pump_action: ThermalTerminationPumpAction = ThermalTerminationPumpAction.NONE,
    body_action: ThermalTerminationBodyAction = ThermalTerminationBodyAction.NONE,
    operation: SetHeatMode | None = None,
    monotonic: bool = True,
    physical_action_required: bool = False,
) -> ThermalTerminationAssessment:
    return ThermalTerminationAssessment(
        disposition=disposition,
        reason_code=reason,
        entitlement_id=entitlement_id,
        entitlement_generation=entitlement_generation,
        body=body,
        source_action=source_action,
        pump_action=pump_action,
        body_action=body_action,
        operation=operation,
        monotonic=monotonic,
        physical_action_required=physical_action_required,
    )


__all__ = [
    "ThermalTerminationAssessment",
    "ThermalTerminationBodyAction",
    "ThermalTerminationDisposition",
    "ThermalTerminationPolicy",
    "ThermalTerminationPumpAction",
    "ThermalTerminationSourceAction",
]
