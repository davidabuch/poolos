"""Typed source disposition for winding down an owned body session.

Ongoing THERMAL authority and the narrow authority to unwind a PoolOS-created
BODY lifecycle are different things.  This module decides only whether source
selection is already safe, must be reduced to Off, or must be preserved because
of positively attributable operator intent.  It never delivers a command.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .integration import PhysicalHeatMode, ThermalBody
from .ownership_evidence import OwnershipDomain
from .thermal_runtime_ownership import (
    ThermalResidualTerminationEntitlement,
    ThermalRuntimeOwnershipEvidence,
)


class ThermalSourceCleanupDisposition(StrEnum):
    """Session-scoped disposition of the selected source during shutdown."""

    EVIDENCE_UNUSABLE = "evidence_unusable"
    SELECTED_OFF = "selected_off"
    SELECTED_OFF_NOT_CURRENT_FOR_CLEANUP = "selected_off_not_current_for_cleanup"
    OWNED_SOURCE_OFF_REQUIRED = "owned_source_off_required"
    BODY_SESSION_SOURCE_OFF_REQUIRED = "body_session_source_off_required"
    OPERATOR_SELECTION_PRESERVED = "operator_selection_preserved"
    CURRENT_POLICY_REQUIRES_SOURCE = "current_policy_requires_source"
    NO_SOURCE_CLEANUP_CAPABILITY = "no_source_cleanup_capability"


@dataclass(frozen=True, slots=True)
class ThermalSourceCleanupAssessment:
    """Command-free source decision bound to one residual/evidence epoch."""

    disposition: ThermalSourceCleanupDisposition
    reason_code: str
    selected_source: PhysicalHeatMode | None
    selected_source_current: bool
    source_off_authorized: bool = False
    source_cleanup_complete: bool = False
    body_shutdown_source_safe: bool = False
    filtration_handoff_source_safe: bool = False
    operator_selection_preserved: bool = False
    reactivation_possible_while_body_active: bool = False


class ThermalSourceCleanupPolicy:
    """Resolve source selection without manufacturing THERMAL ownership."""

    def evaluate(
        self,
        entitlement: ThermalResidualTerminationEntitlement,
        evidence: ThermalRuntimeOwnershipEvidence,
        *,
        desired_source: PhysicalHeatMode,
    ) -> ThermalSourceCleanupAssessment:
        source = evidence.effective_heat_source
        source_observation_usable = bool(
            source is not None
            and evidence.heat_source_observation_fresh
            and evidence.heat_source_observation_usable
            and evidence.heat_source_observed_at is not None
            and evidence.heat_source_observed_at <= evidence.evaluated_at
        )
        if not source_observation_usable:
            return _assessment(
                ThermalSourceCleanupDisposition.EVIDENCE_UNUSABLE,
                "thermal_source_cleanup_evidence_unusable",
                source,
                selected_source_current=False,
            )
        assert source is not None
        assert evidence.heat_source_observed_at is not None
        if source is PhysicalHeatMode.OFF:
            if evidence.heat_source_observed_at < entitlement.retained_at:
                return _assessment(
                    ThermalSourceCleanupDisposition.SELECTED_OFF_NOT_CURRENT_FOR_CLEANUP,
                    "thermal_source_cleanup_selected_off_not_current_for_cleanup",
                    source,
                    selected_source_current=True,
                )
            return _assessment(
                ThermalSourceCleanupDisposition.SELECTED_OFF,
                "thermal_source_cleanup_selected_off",
                source,
                selected_source_current=True,
                source_cleanup_complete=True,
                body_shutdown_source_safe=True,
                filtration_handoff_source_safe=True,
            )

        source_concept = (
            "pool.raw_heater_id"
            if entitlement.body is ThermalBody.POOL
            else "spa.raw_heater_id"
        )
        operator = any(
            event.concept == source_concept
            and _event_matches_selected_source(event.new_value, source)
            and event.operator_applies(
                generation=(
                    entitlement.body_session_generation or entitlement.generation
                ),
                session_id=entitlement.body_session_id or entitlement.lease_id,
                domain=OwnershipDomain.THERMAL,
                equipment_id=source_concept,
                established_at=entitlement.originating_lease_established_at,
                evaluated_at=evidence.evaluated_at,
            )
            for event in evidence.external_changes.events
        )
        if operator:
            # BODY completion ends this session-scoped override without
            # rewriting the operator's selected source.  A filtration handoff
            # would keep the same body session alive and could reactivate it.
            return _assessment(
                ThermalSourceCleanupDisposition.OPERATOR_SELECTION_PRESERVED,
                "thermal_source_cleanup_operator_selection_preserved",
                source,
                selected_source_current=True,
                body_shutdown_source_safe=True,
                operator_selection_preserved=True,
                reactivation_possible_while_body_active=True,
            )
        if desired_source is not PhysicalHeatMode.OFF:
            return _assessment(
                ThermalSourceCleanupDisposition.CURRENT_POLICY_REQUIRES_SOURCE,
                "thermal_source_cleanup_current_policy_requires_source",
                source,
                selected_source_current=True,
                reactivation_possible_while_body_active=True,
            )
        if entitlement.heat_source is not None:
            return _assessment(
                ThermalSourceCleanupDisposition.OWNED_SOURCE_OFF_REQUIRED,
                "thermal_source_cleanup_owned_source_off_required",
                source,
                selected_source_current=True,
                source_off_authorized=True,
                reactivation_possible_while_body_active=True,
            )
        if (entitlement.body_activation is not None or entitlement.body_adoption is not None):
            # This exact safe reduction is authority to unwind the accepted
            # BODY session.  It does not claim ongoing THERMAL policy ownership
            # and cannot select Solar or Gas.
            return _assessment(
                ThermalSourceCleanupDisposition.BODY_SESSION_SOURCE_OFF_REQUIRED,
                "thermal_source_cleanup_body_session_source_off_required",
                source,
                selected_source_current=True,
                source_off_authorized=True,
                reactivation_possible_while_body_active=True,
            )
        return _assessment(
            ThermalSourceCleanupDisposition.NO_SOURCE_CLEANUP_CAPABILITY,
            "thermal_source_cleanup_no_capability",
            source,
            selected_source_current=True,
            reactivation_possible_while_body_active=True,
        )


def _assessment(
    disposition: ThermalSourceCleanupDisposition,
    reason: str,
    source: PhysicalHeatMode | None,
    *,
    selected_source_current: bool,
    source_off_authorized: bool = False,
    source_cleanup_complete: bool = False,
    body_shutdown_source_safe: bool = False,
    filtration_handoff_source_safe: bool = False,
    operator_selection_preserved: bool = False,
    reactivation_possible_while_body_active: bool = False,
) -> ThermalSourceCleanupAssessment:
    return ThermalSourceCleanupAssessment(
        disposition=disposition,
        reason_code=reason,
        selected_source=source,
        selected_source_current=selected_source_current,
        source_off_authorized=source_off_authorized,
        source_cleanup_complete=source_cleanup_complete,
        body_shutdown_source_safe=body_shutdown_source_safe,
        filtration_handoff_source_safe=filtration_handoff_source_safe,
        operator_selection_preserved=operator_selection_preserved,
        reactivation_possible_while_body_active=reactivation_possible_while_body_active,
    )


def _event_matches_selected_source(value: object, source: PhysicalHeatMode) -> bool:
    expected = {
        PhysicalHeatMode.OFF: ("00000", "off", PhysicalHeatMode.OFF),
        PhysicalHeatMode.GAS: ("H0001", "gas", PhysicalHeatMode.GAS),
        PhysicalHeatMode.SOLAR: ("H0002", "solar", PhysicalHeatMode.SOLAR),
    }[source]
    return any(value == item for item in expected)


__all__ = [
    "ThermalSourceCleanupAssessment",
    "ThermalSourceCleanupDisposition",
    "ThermalSourceCleanupPolicy",
]
