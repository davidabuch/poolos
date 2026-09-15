"""Home Assistant event adapter for command-free native change classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from homeassistant.core import HomeAssistant

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalNativeChangeMonitor,
    ExternalOwnershipContext,
    ThermalRuntimeExternalChangeEvidence,
)
from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource,
    SpaAutomaticControlSuppression,
    SpaAutomaticControlSuppressionSource,
)
from poolos.thermal_execution_planning import ThermalPlanDisposition
from poolos.thermal_runtime_assessment import ThermalRequestedMode

from .configured_thermal import configured_heater_intent_for_direct_requested_mode
from .thermal_runtime import PoolOSThermalRuntime


EVENT_POOLOS_EXTERNAL_CHANGE = "poolos_external_change"


@dataclass(slots=True)
class PoolOSExternalChangeRuntime:
    """Publish bounded semantic events; never issue reconciliation commands."""

    hass: HomeAssistant
    authority: PoolOSPhysicalCommandAuthority
    thermal_runtime: PoolOSThermalRuntime
    pool_automatic_control: PoolAutomaticControlSuppression | None = None
    spa_automatic_control: SpaAutomaticControlSuppression | None = None
    owned_intent_provider: Callable[[], Mapping[str, object]] | None = None
    monitor: ExternalNativeChangeMonitor = field(init=False)
    _connection_generation: int | None = field(default=None, init=False, repr=False)
    _ownership_blockers: tuple[str, ...] = field(default=(), init=False, repr=False)
    _last_native_values: dict[str, object] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _last_ownership: ExternalOwnershipContext = field(
        default_factory=ExternalOwnershipContext,
        init=False,
        repr=False,
    )
    _thermal_external_evidence: ThermalRuntimeExternalChangeEvidence = field(
        default_factory=ThermalRuntimeExternalChangeEvidence,
        init=False,
        repr=False,
    )
    latest_batch: ExternalChangeBatch = field(
        default_factory=lambda: ExternalChangeBatch(()),
        init=False,
    )

    def __post_init__(self) -> None:
        self.monitor = ExternalNativeChangeMonitor(self.authority)

    def process(
        self,
        native: NativeIntelliCenterObservationSnapshot,
        transport: NativeIntelliCenterTransportSnapshot,
        connection_generation: int,
    ) -> None:
        """Classify one already-published authoritative native snapshot."""

        values = {item.observation_id: item.value for item in native.observations}
        system_mode = values.get("intellicenter.system_mode")
        self.authority.set_controller_mode(
            system_mode if isinstance(system_mode, str) else None
        )
        if self._connection_generation != connection_generation:
            self._connection_generation = connection_generation
            self.monitor.reset_baseline()
            self._thermal_external_evidence.reset()
            self.latest_batch = ExternalChangeBatch(())
            self._last_native_values.clear()
            self._last_ownership = ExternalOwnershipContext()
        ownership = self._ownership()
        batch = self.monitor.process(
            native,
            transport,
            ownership=ownership,
        )
        # Preserve one latest event per canonical thermal/hydraulic takeover
        # concept. Later unrelated transitions or correlated PoolOS consequences
        # cannot erase an earlier lease-relevant takeover. Consumers still apply
        # their own lease-epoch chronology checks.
        self.latest_batch = self._thermal_external_evidence.update(batch)
        if self.pool_automatic_control is not None:
            spa_takeover = any(
                event.concept == "spa.active"
                and event.previous_value is False
                and event.new_value is True
                for event in batch.events
            )
            for event in batch.events:
                if (
                    event.concept == "pool.active"
                    and event.previous_value is True
                    and event.new_value is False
                    and not spa_takeover
                ):
                    self.pool_automatic_control.suppress(
                        source=(
                            PoolAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF
                        ),
                        suppressed_at=event.observed_at,
                        reason="external_authoritative_pool_on_to_off",
                    )
        if self.spa_automatic_control is not None:
            for event in batch.events:
                if (
                    event.concept == "spa.active"
                    and event.previous_value is True
                    and event.new_value is False
                ):
                    self.spa_automatic_control.suppress(
                        source=SpaAutomaticControlSuppressionSource.EXTERNAL_NATIVE_OFF,
                        suppressed_at=event.observed_at,
                        reason="external_authoritative_spa_on_to_off",
                    )
        refreshed_ownership = self._ownership()
        if refreshed_ownership.intended_values != ownership.intended_values:
            self.monitor.recompute_current_ownership(refreshed_ownership)
        self._last_native_values = dict(values)
        self._last_ownership = refreshed_ownership
        for event in batch.events:
            self.hass.bus.async_fire(
                EVENT_POOLOS_EXTERNAL_CHANGE,
                dict(event.as_event_data()),
            )

    def maintenance_exited(self) -> None:
        """Adopt current truth as a fresh prospective comparison baseline."""

        self.monitor.reset_baseline()

    def maintenance_entered(self) -> None:
        """Relinquish contextual ownership without changing native truth."""

        self.monitor.clear_active_drift()

    def refresh_ownership(self) -> None:
        """Recompute drift when thermal intent changes without native movement."""

        ownership = self._ownership()
        if _native_truth_matches_prior_intent_transition(
            self._last_native_values,
            self._last_ownership,
            ownership,
        ):
            # Accepted execution intent may legitimately move ahead of the
            # steady-state planner target (for example 3000-RPM Solar priming).
            # Retiring that temporary intent while native truth still reflects
            # it is an intent handoff, not a new native transition.  Preserve a
            # clean comparison state until a subsequent authoritative snapshot
            # provides new physical evidence.
            self.monitor.clear_active_drift()
        else:
            self.monitor.recompute_current_ownership(ownership)
        self._last_ownership = ownership

    def diagnostics(self) -> dict[str, Any]:
        return {
            **dict(self.monitor.diagnostics()),
            "event_type": EVENT_POOLOS_EXTERNAL_CHANGE,
            "maintenance_mode": self.authority.maintenance_mode,
            "ownership_blockers": list(self._ownership_blockers[:8]),
            "reconciliation_delivery_enabled": False,
        }

    def _ownership(self) -> ExternalOwnershipContext:
        intended: dict[str, Any] = {}
        blockers: list[str] = []
        accepted_intent = (
            {}
            if self.owned_intent_provider is None
            else dict(self.owned_intent_provider())
        )
        configured_modes = (
            (
                "pool",
                self.thermal_runtime.pool_requested_mode,
                self.thermal_runtime.pool_requested_mode_resolved,
            ),
            (
                "spa",
                self.thermal_runtime.hot_tub_requested_mode,
                self.thermal_runtime.hot_tub_requested_mode_resolved,
            ),
        )
        for prefix, requested_mode, resolved in configured_modes:
            concept = f"{prefix}.raw_heater_id"
            if not resolved:
                blockers.append(f"{prefix}_requested_heat_mode_unresolved")
                continue
            heater_id = configured_heater_intent_for_direct_requested_mode(
                requested_mode
            )
            if heater_id is None:
                continue
            if concept not in self.monitor.current_concepts():
                blockers.append(f"{prefix}_native_heater_baseline_unavailable")
                continue
            if concept not in accepted_intent:
                intended[concept] = heater_id

        assessment = self.thermal_runtime.assessment
        if assessment is None:
            self._ownership_blockers = tuple(blockers)
            intended.update(accepted_intent)
            return ExternalOwnershipContext(intended)
        pump_claims: set[int] = set()
        for body_assessment, requested_mode_resolved in (
            (assessment.pool, self.thermal_runtime.pool_requested_mode_resolved),
            (
                assessment.hot_tub,
                self.thermal_runtime.hot_tub_requested_mode_resolved,
            ),
        ):
            if (
                not requested_mode_resolved
                or body_assessment.body_active is not True
                or body_assessment.requested_mode is ThermalRequestedMode.OFF
                or not _assessment_usable_for_ownership(body_assessment)
            ):
                continue
            desired = body_assessment.plan.desired
            if desired.required_pump_rpm is not None:
                pump_claims.add(desired.required_pump_rpm)
        if "pump.rpm" in accepted_intent:
            intended["pump.rpm"] = accepted_intent["pump.rpm"]
        elif len(pump_claims) == 1:
            intended["pump.rpm"] = next(iter(pump_claims))
        elif len(pump_claims) > 1:
            blockers.append("conflicting_thermal_pump_ownership")
        self._ownership_blockers = tuple(blockers)
        intended.update(accepted_intent)
        return ExternalOwnershipContext(intended)


_ALREADY_CONVERGED_TECHNICAL_NONBLOCKERS = frozenset(
    {
        "thermal_plan_not_ready",
        "thermal_step_not_found",
        "thermal_step_specification_missing",
    }
)


def _assessment_usable_for_ownership(body_assessment: Any) -> bool:
    plan = body_assessment.plan
    if (
        plan.disposition is ThermalPlanDisposition.BLOCKED
        or not plan.desired.evidence_usable
        or body_assessment.evidence_blockers
    ):
        return False
    if plan.disposition is ThermalPlanDisposition.READY:
        return bool(body_assessment.technical_preflight.ready)
    if plan.disposition is not ThermalPlanDisposition.ALREADY_CONVERGED:
        return False
    blockers = set(body_assessment.technical_preflight.blocking_reasons)
    return blockers <= _ALREADY_CONVERGED_TECHNICAL_NONBLOCKERS


def _native_truth_matches_prior_intent_transition(
    native_values: Mapping[str, object],
    previous: ExternalOwnershipContext,
    current: ExternalOwnershipContext,
) -> bool:
    """Return whether every current mismatch is still aligned to prior intent."""

    explained_transition = False
    for concept, intended in current.intended_values.items():
        if concept not in native_values:
            continue
        observed = native_values[concept]
        if _intent_aligned(concept, intended, observed):
            continue
        prior = previous.intended_values.get(concept)
        if (
            prior is None
            or prior == intended
            or not _intent_aligned(concept, prior, observed)
        ):
            return False
        explained_transition = True
    return explained_transition


def _intent_aligned(concept: str, intended: object, observed: object) -> bool:
    if concept != "pump.rpm":
        return intended == observed
    try:
        return abs(float(observed) - float(intended)) <= 25.0
    except (TypeError, ValueError, OverflowError):
        return intended == observed


__all__ = ["EVENT_POOLOS_EXTERNAL_CHANGE", "PoolOSExternalChangeRuntime"]
