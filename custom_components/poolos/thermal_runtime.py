"""Home Assistant evidence assembly for command-free Phase 3 diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any

from poolos.integration import ThermalBody
from poolos.native_configuration_policy import (
    NativeConfigurationGuard,
    NativeConfigurationInput,
    NativeRpmAssignment,
)
from poolos.thermal_live_execution import (
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionPolicy,
)
from poolos.thermal_runtime_assessment import (
    ThermalRequestedMode,
    ThermalRuntimeAssessment,
    ThermalRuntimeEvaluator,
    ThermalRuntimeEvidence,
)

from .observation import ObservationSnapshot

if TYPE_CHECKING:
    from .coordinator import PoolOSCoordinator
    from .filtration_runtime import PoolOSFiltrationRuntime
    from .manual_intellicenter import ManualIntelliCenterControl


_EVALUATION_ERROR_MESSAGE_LIMIT = 256
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PoolOSThermalRuntime:
    """Own operator configuration and publish pure current readiness evidence."""

    coordinator: PoolOSCoordinator
    manual_intellicenter: ManualIntelliCenterControl | None
    filtration_runtime: PoolOSFiltrationRuntime | None = None
    evaluator: ThermalRuntimeEvaluator = field(default_factory=ThermalRuntimeEvaluator)
    effective_live_enabled: bool = False
    commissioning_scope: ThermalLiveCommissioningScope = (
        ThermalLiveCommissioningScope.DISABLED
    )
    pool_requested_mode: ThermalRequestedMode = ThermalRequestedMode.SOLAR
    hot_tub_requested_mode: ThermalRequestedMode = (
        ThermalRequestedMode.SOLAR_PREFERRED
    )
    assessment: ThermalRuntimeAssessment | None = None
    last_error: str | None = None
    _latest_authoritative_snapshot: ObservationSnapshot | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _assessment_observer: Callable[[], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def set_assessment_observer(self, observer: Callable[[], None]) -> None:
        """Register bounded diagnostics that follow assessment changes."""

        self._assessment_observer = observer

    def set_effective_live_enabled(self, enabled: bool) -> None:
        """Change readiness configuration only; never execute a plan."""

        self.effective_live_enabled = bool(enabled)
        self.refresh(publish=True)

    def set_commissioning_scope(
        self, scope: ThermalLiveCommissioningScope
    ) -> None:
        """Change one-body diagnostic scope without physical side effects."""

        self.commissioning_scope = ThermalLiveCommissioningScope(scope)
        self.refresh(publish=True)

    def set_requested_mode(
        self,
        body: ThermalBody,
        mode: ThermalRequestedMode,
        *,
        publish: bool = True,
    ) -> None:
        """Accept direct selector runtime state without reading HA entities."""

        if body is ThermalBody.POOL:
            self.pool_requested_mode = ThermalRequestedMode(mode)
        else:
            self.hot_tub_requested_mode = ThermalRequestedMode(mode)
        self.refresh(publish=publish)

    def refresh(
        self,
        snapshot: ObservationSnapshot | None = None,
        *,
        publish: bool = False,
    ) -> None:
        """Recompute plans and dry-run readiness from current immutable evidence."""

        authoritative = self._select_authoritative_snapshot(snapshot)
        native = self.coordinator.native_intellicenter_snapshot
        if authoritative is None:
            self.assessment = None
            self.last_error = "authoritative_observation_snapshot_unavailable"
            self._notify_assessment_observer()
            if publish:
                self.coordinator.async_update_listeners()
            return
        values = (
            {}
            if native is None
            else {item.observation_id: item.value for item in native.observations}
        )
        missing = set(() if native is None else native.missing_concepts)
        if native is None:
            missing.update(
                {
                    "pool.active",
                    "pool.temperature",
                    "pool.target_temperature",
                    "pool.raw_heater_id",
                    "spa.active",
                    "spa.temperature",
                    "spa.target_temperature",
                    "spa.raw_heater_id",
                    "pump.rpm",
                    "solar.temperature",
                    "solar.active",
                }
            )
        stale_sources = set(authoritative.stale_entities)
        stale = tuple(
            item.observation_id
            for item in (() if native is None else native.observations)
            if item.source_id in stale_sources
        )
        health = self.coordinator.health_incident_diagnostics()
        policy = ThermalLiveExecutionPolicy(
            thermal_live_execution_enabled=self.effective_live_enabled,
            commissioning_scope=self.commissioning_scope,
        )
        filtration = (
            None
            if self.filtration_runtime is None
            else self.filtration_runtime.assessment
        )
        try:
            self.assessment = self.evaluator.evaluate(
                ThermalRuntimeEvidence(
                    evaluated_at=authoritative.generated_at,
                    native_values=values,
                    pool_requested_mode=self.pool_requested_mode,
                    hot_tub_requested_mode=self.hot_tub_requested_mode,
                    native_transport_available=(
                        native is not None and native.available
                    ),
                    manual_transport_available=(
                        self.manual_intellicenter is not None
                        and self.manual_intellicenter.available
                    ),
                    immediate_observation_healthy=authoritative.healthy,
                    stale_native_concepts=stale,
                    missing_native_concepts=tuple(missing),
                    native_configuration=NativeConfigurationGuard().evaluate(
                        self._native_configuration_input()
                    ),
                    filtration_debt=(
                        None
                        if filtration is None
                        else filtration.total_remaining_runtime
                    ),
                    pending_durable_incident_confirmation=bool(
                        health.get("pending_confirmation", False)
                    ),
                    durable_incident_confirmed=bool(
                        health.get("unhealthy_seen_since_start", False)
                    ),
                ),
                live_policy=policy,
            )
        except (TypeError, ValueError) as exc:
            self.assessment = None
            self.last_error = _bounded_evaluation_error(exc)
        else:
            self.last_error = None
        self._notify_assessment_observer()
        if publish:
            self.coordinator.async_update_listeners()

    def _notify_assessment_observer(self) -> None:
        observer = self._assessment_observer
        if observer is None:
            return
        try:
            observer()
        except Exception:
            LOGGER.exception(
                "PoolOS external ownership diagnostics refresh failed; "
                "thermal assessment publication continues"
            )

    def _select_authoritative_snapshot(
        self,
        snapshot: ObservationSnapshot | None,
    ) -> ObservationSnapshot | None:
        """Never regress stateful policy trackers to older evidence."""

        latest = self._latest_authoritative_snapshot
        for candidate in (self.coordinator.data, snapshot):
            if candidate is None:
                continue
            if latest is None or candidate.generated_at >= latest.generated_at:
                latest = candidate
        self._latest_authoritative_snapshot = latest
        return latest

    def _native_configuration_input(self) -> NativeConfigurationInput:
        transport = self.coordinator.independent_intellicenter_transport
        snapshot = None if transport is None else transport.latest_snapshot
        if snapshot is None:
            return NativeConfigurationInput()
        solar_preferred = any(
            str(body.selected_heat_mode or "").casefold() == "solar_preferred"
            for body in snapshot.bodies
        )
        assignments: list[NativeRpmAssignment] = []
        for item in snapshot.raw_inventory:
            if item.object_type.upper() != "PMPCIRC" or item.native_id == "p0102":
                continue
            attributes = {attribute.name.upper(): attribute.value for attribute in item.attributes}
            rpm = _integer(attributes.get("RPM"))
            if rpm is None:
                continue
            purpose = (item.name or item.subtype or item.native_id).strip()
            assignments.append(NativeRpmAssignment(purpose, rpm))
        return NativeConfigurationInput(
            native_solar_preferred=solar_preferred,
            rpm_assignments=tuple(assignments),
        )

    def body_diagnostics(self, body: ThermalBody) -> dict[str, Any]:
        if self.assessment is None:
            return self._unavailable_diagnostics(body.value)
        assessment = (
            self.assessment.pool
            if body is ThermalBody.POOL
            else self.assessment.hot_tub
        )
        return dict(assessment.diagnostics())

    def global_diagnostics(self) -> dict[str, Any]:
        if self.assessment is None:
            return self._unavailable_diagnostics("global")
        return dict(self.assessment.global_diagnostics())

    def _unavailable_diagnostics(self, body: str) -> dict[str, Any]:
        return {
            "body": body,
            "state": "UNAVAILABLE",
            "error": self.last_error,
            "effective_thermal_live_enabled": self.effective_live_enabled,
            "commissioning_scope": self.commissioning_scope.value,
            "authority": "none",
            "automatic_execution_driver_enabled": False,
            "command_delivery_performed": False,
        }


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _bounded_evaluation_error(exc: TypeError | ValueError) -> str:
    prefix = f"thermal_runtime_evaluation_failed:{type(exc).__name__}"
    printable = "".join(
        character if character.isprintable() else " " for character in str(exc)
    )
    message = " ".join(printable.split())[:_EVALUATION_ERROR_MESSAGE_LIMIT]
    return prefix if not message else f"{prefix}:{message}"


__all__ = ["PoolOSThermalRuntime"]
