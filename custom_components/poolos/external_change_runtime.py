"""Home Assistant event adapter for command-free native change classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from poolos.external_change import (
    ExternalNativeChangeMonitor,
    ExternalOwnershipContext,
)
from poolos.integration import PhysicalHeatMode
from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterTransportSnapshot,
)
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.thermal_execution_planning import ThermalPlanDisposition
from poolos.thermal_runtime_assessment import ThermalRequestedMode

from .thermal_runtime import PoolOSThermalRuntime


EVENT_POOLOS_EXTERNAL_CHANGE = "poolos_external_change"

_HEATER_IDS = {
    PhysicalHeatMode.OFF: "00000",
    PhysicalHeatMode.GAS: "H0001",
    PhysicalHeatMode.SOLAR: "H0002",
}


@dataclass(slots=True)
class PoolOSExternalChangeRuntime:
    """Publish bounded semantic events; never issue reconciliation commands."""

    hass: HomeAssistant
    authority: PoolOSPhysicalCommandAuthority
    thermal_runtime: PoolOSThermalRuntime
    monitor: ExternalNativeChangeMonitor = field(init=False)
    _connection_generation: int | None = field(default=None, init=False, repr=False)
    _ownership_blockers: tuple[str, ...] = field(default=(), init=False, repr=False)

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
        batch = self.monitor.process(
            native,
            transport,
            ownership=self._ownership(),
        )
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

        self.monitor.recompute_current_ownership(self._ownership())

    def diagnostics(self) -> dict[str, Any]:
        return {
            **dict(self.monitor.diagnostics()),
            "event_type": EVENT_POOLOS_EXTERNAL_CHANGE,
            "maintenance_mode": self.authority.maintenance_mode,
            "ownership_blockers": list(self._ownership_blockers[:8]),
            "reconciliation_delivery_enabled": False,
        }

    def _ownership(self) -> ExternalOwnershipContext:
        assessment = self.thermal_runtime.assessment
        if assessment is None:
            self._ownership_blockers = ()
            return ExternalOwnershipContext()
        intended: dict[str, Any] = {}
        pump_claims: set[int] = set()
        for body_assessment, prefix in (
            (assessment.pool, "pool"),
            (assessment.hot_tub, "spa"),
        ):
            if (
                body_assessment.body_active is not True
                or body_assessment.requested_mode is ThermalRequestedMode.OFF
                or not _assessment_usable_for_ownership(body_assessment)
            ):
                continue
            desired = body_assessment.plan.desired
            intended[f"{prefix}.raw_heater_id"] = _HEATER_IDS[
                desired.selected_source
            ]
            if desired.required_pump_rpm is not None:
                pump_claims.add(desired.required_pump_rpm)
        blockers: list[str] = []
        if len(pump_claims) == 1:
            intended["pump.rpm"] = next(iter(pump_claims))
        elif len(pump_claims) > 1:
            blockers.append("conflicting_thermal_pump_ownership")
        self._ownership_blockers = tuple(blockers)
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


__all__ = ["EVENT_POOLOS_EXTERNAL_CHANGE", "PoolOSExternalChangeRuntime"]
