"""Home Assistant lifecycle bridge for default-off grid-outage safety."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from homeassistant.core import HomeAssistant

from poolos.external_change import ExternalChangeBatch
from poolos.filtration_policy import FiltrationDisposition
from poolos.grid_outage_physical_safety import (
    GridOutagePhysicalSafetyEngine,
    GridOutageReductionCandidate,
    OutageCirculationDisposition,
    GridOutageSafetyFrame,
    GridOutageSafetyLifecycle,
    grid_outage_external_preemption_reason,
)
from poolos.physical_command_authority import (
    GridOutageDispatchContext,
    GridOutageDispatchPurpose,
    PhysicalAuthorityReason,
    PoolOSPhysicalCommandAuthority,
)
from poolos.grid_outage_confirmation import GridOutageDisposition
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrationAssessment
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeOwnershipManager,
    ThermalRuntimeOwnershipStatus,
)
from poolos.integration import ThermalBody

from .coordinator import PoolOSCoordinator
from .grid_outage_delivery import ManualIntelliCenterGridOutageDelivery
from .manual_intellicenter import (
    ManualIntelliCenterCommandNotDispatchedError,
    ManualIntelliCenterControl,
)
from .observation import ObservationSnapshot
from .thermal_runtime import PoolOSThermalRuntime


LOGGER = logging.getLogger(__name__)


def thermal_pool_shutdown_entitlement_present(
    ownership: ThermalRuntimeOwnershipManager,
) -> bool:
    """Return reduction-only Pool BODY termination provenance.

    Normal owned BODY authority qualifies directly. A residual termination
    entitlement retained when normal ownership is relinquished also qualifies
    when it contains Pool BODY activation/adoption provenance. Residual proof
    never restores normal ownership and is usable only for reduction.
    """

    lease = ownership.state.lease
    if (
        lease is not None
        and lease.status is ThermalRuntimeOwnershipStatus.OWNED
        and lease.body is ThermalBody.POOL
        and lease.owns_body
    ):
        return True

    residual = ownership.residual_termination
    return bool(
        residual is not None
        and residual.body is ThermalBody.POOL
        and (
            residual.body_activation is not None
            or residual.body_adoption is not None
        )
    )


@dataclass(slots=True)
class PoolOSGridOutageSafetyRuntime:
    """Own one event-driven, one-shot-at-a-time outage safety lifecycle."""

    hass: HomeAssistant
    coordinator: PoolOSCoordinator
    thermal_runtime: PoolOSThermalRuntime
    authority: PoolOSPhysicalCommandAuthority
    manual: ManualIntelliCenterControl | None
    pool_shutdown_entitlement_provider: Callable[[], bool] = field(
        default=lambda: False,
        repr=False,
    )
    engine: GridOutagePhysicalSafetyEngine = field(default_factory=GridOutagePhysicalSafetyEngine)
    _task: asyncio.Task[object] | None = field(default=None, init=False, repr=False)
    _pending: (
        tuple[
            ObservationSnapshot,
            ThermalRuntimeOrchestrationAssessment,
            ExternalChangeBatch,
        ]
        | None
    ) = field(default=None, init=False, repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)
    _pool_shutdown_entitlement_epoch: str | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _pool_shutdown_entitled: bool = field(default=False, init=False, repr=False)
    _filtration_satisfied_commissioning_override: bool = field(
        default=False,
        init=False,
        repr=False,
    )

    @property
    def enabled(self) -> bool:
        return self.engine.gate_requested

    def set_enabled(self, enabled: bool) -> None:
        """Change the independent gate without processing cached evidence."""

        now = datetime.now(UTC)
        self.engine.set_enabled(enabled, changed_at=now)
        self.authority.configure_grid_outage_safety(enabled=enabled)
        self.coordinator.async_update_listeners()

    @property
    def filtration_satisfied_commissioning_override(self) -> bool:
        """Return the restart-reset commissioning-only ledger override."""

        return self._filtration_satisfied_commissioning_override

    def set_filtration_satisfied_commissioning_override(self, enabled: bool) -> None:
        """Override only the outage frame; never mutate the production ledger."""

        self._filtration_satisfied_commissioning_override = bool(enabled)
        self.coordinator.async_update_listeners()


    def observe(
        self,
        snapshot: ObservationSnapshot,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        external_changes: ExternalChangeBatch = ExternalChangeBatch(()),
    ) -> None:
        """Evaluate one authoritative frame and schedule at most one reduction."""

        if self._unloaded or orchestration.outage is None:
            return

        # Capture positive Pool BODY termination provenance at the observation
        # boundary, before any normal executor later in this same orchestration
        # callback can relinquish ownership because the grid is no longer
        # authoritatively ON. _process_frame may be delayed behind an in-flight
        # Safety delivery, so sampling only there is too late.
        outage = orchestration.outage
        if outage.disposition is GridOutageDisposition.ON_GRID:
            self._pool_shutdown_entitlement_epoch = None
            self._pool_shutdown_entitled = False
        elif outage.disposition is GridOutageDisposition.OFF_GRID_PENDING:
            if self._pool_shutdown_entitlement_epoch is None:
                self._pool_shutdown_entitlement_epoch = (
                    f"pending|{getattr(outage, 'source_id', '')}|"
                    f"{getattr(outage, 'outage_epoch_started_at', None)}"
                )
            if not self._pool_shutdown_entitled:
                self._pool_shutdown_entitled = bool(
                    self.pool_shutdown_entitlement_provider()
                )

        if self._task is not None:
            # Authoritative grid return ends the Safety domain immediately even
            # if an older reduction delivery is still resolving. Otherwise keep
            # the already-established domain until the pending frame is evaluated.
            if orchestration.outage.disposition is GridOutageDisposition.ON_GRID:
                self.authority.set_grid_outage_domain_state(
                    active=False,
                    outage_epoch_id=None,
                )
            # A newer frame must invalidate queued physical dispatch authority,
            # but not the independently tracked confirmed-outage Safety domain.
            self.authority.begin_grid_outage_frame(
                outage_epoch_id=None,
                frame_identity=orchestration.snapshot_identity,
            )
            self._pending = (snapshot, orchestration, external_changes)
            return
        self._process_frame(snapshot, orchestration, external_changes)

    def orchestration_failed(self, snapshot: ObservationSnapshot, error: Exception) -> None:
        """Invalidate outage readiness without suppressing native publication."""

        if self._unloaded:
            return
        self.authority.begin_grid_outage_frame(
            outage_epoch_id=None,
            frame_identity=(f"failed:{snapshot.generated_at.isoformat()}:{type(error).__name__}"),
        )
        self._pending = None
        self.engine.fail_closed(
            failed_at=snapshot.generated_at,
            reason=type(error).__name__,
        )

    def _process_frame(
        self,
        snapshot: ObservationSnapshot,
        orchestration: ThermalRuntimeOrchestrationAssessment,
        external_changes: ExternalChangeBatch,
    ) -> None:
        """Process one frame while no delivery coroutine is in flight."""

        assert orchestration.outage is not None
        outage = orchestration.outage
        if outage.disposition is GridOutageDisposition.ON_GRID:
            self._pool_shutdown_entitlement_epoch = None
            self._pool_shutdown_entitled = False
        elif (
            outage.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
            and outage.confirmed_at is not None
        ):
            outage_epoch = (
                f"{getattr(outage, 'source_id', '')}|"
                f"{getattr(outage, 'outage_epoch_started_at', None)}|"
                f"{outage.confirmed_at.isoformat()}"
            )
            if self._pool_shutdown_entitlement_epoch is None:
                self._pool_shutdown_entitled = bool(
                    self.pool_shutdown_entitlement_provider()
                )
            self._pool_shutdown_entitlement_epoch = outage_epoch

        base_reason = self.authority.base_authority_reason
        manual_ready = self.manual is not None and self.manual.available
        filtration_runtime = getattr(self.thermal_runtime, "filtration_runtime", None)
        filtration = None if filtration_runtime is None else filtration_runtime.assessment
        simulated_outage = str(getattr(outage, "source_id", "")).startswith(
            "poolos_simulation:"
        )
        if (
            filtration is not None
            and self._filtration_satisfied_commissioning_override
            and simulated_outage
            and outage.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
        ):
            filtration = replace(
                filtration,
                evaluated_at=snapshot.generated_at,
                remaining_runtime=timedelta(0),
                total_remaining_runtime=timedelta(0),
                disposition=FiltrationDisposition.SATISFIED,
                independent_disposition=FiltrationDisposition.SATISFIED,
                next_suitable_at=None,
                reason_code="commissioning_grid_outage_filtration_satisfied_override",
                rationale=(
                    "Commissioning-only outage frame override; production ledger unchanged.",
                ),
                currently_earning_credit=False,
            )
        prior_assessment = self.engine.assessment
        prior_attempt = (
            None
            if prior_assessment is None
            else getattr(prior_assessment, "attempt", None)
        )
        prior_candidate = (
            None
            if prior_attempt is None
            else getattr(prior_attempt, "candidate", None)
        )
        candidate_formed_at = (
            None
            if prior_candidate is None
            else getattr(prior_candidate, "formed_at", None)
        )
        authority_not_before = (
            candidate_formed_at
            if candidate_formed_at is not None
            else snapshot.generated_at
        )
        external_preemption_reason = grid_outage_external_preemption_reason(
            external_changes,
            authority_not_before=authority_not_before,
            evaluated_at=snapshot.generated_at,
        )
        thermal_assessment = getattr(self.thermal_runtime, "assessment", None)
        frame = GridOutageSafetyFrame(
            frame_identity=orchestration.snapshot_identity,
            observed_at=snapshot.generated_at,
            observations=tuple(snapshot.observations),
            outage=orchestration.outage,
            filtration=filtration,
            physical_authority_ready=(base_reason is PhysicalAuthorityReason.ALLOWED),
            transport_ready=manual_ready,
            pool_pump_circuit_id=(
                None
                if thermal_assessment is None
                else thermal_assessment.pool_pump_circuit_id
            ),
            pool_shutdown_authorized=self._pool_shutdown_entitled,
            external_preemption_reason=external_preemption_reason,
        )
        assessment = self.engine.evaluate(frame)
        outage_domain_active = (
            assessment.outage_epoch_id is not None
            and assessment.lifecycle
            not in {
                GridOutageSafetyLifecycle.ENDED,
                GridOutageSafetyLifecycle.INACTIVE,
                GridOutageSafetyLifecycle.UNLOADED,
            }
        )
        pump_ceiling_required = bool(
            assessment.circulation is not None
            and assessment.circulation.disposition
            is OutageCirculationDisposition.REQUIRED
        )
        self.authority.set_grid_outage_domain_state(
            active=outage_domain_active,
            outage_epoch_id=(
                assessment.outage_epoch_id if outage_domain_active else None
            ),
            pump_ceiling_required=pump_ceiling_required,
        )
        self.authority.begin_grid_outage_frame(
            outage_epoch_id=assessment.outage_epoch_id,
            frame_identity=frame.frame_identity,
        )
        candidate = assessment.candidate
        if (
            candidate is None
            or assessment.lifecycle is not GridOutageSafetyLifecycle.CANDIDATE_READY
        ):
            return
        registered = self.authority.register_grid_outage_candidate(
            outage_epoch_id=candidate.outage_epoch_id,
            frame_identity=candidate.frame_identity,
            candidate_id=candidate.candidate_id,
            purpose=GridOutageDispatchPurpose(candidate.kind.value),
            operation=candidate.operation,
            target=candidate.target,
            requested_value=candidate.requested_value,
        )
        if self._task is not None:
            return
        context = self.authority.bind_grid_outage_dispatch(registered)
        self._task = self.hass.async_create_task(
            self._deliver(candidate, context),
            "PoolOS confirmed grid outage physical safety",
        )
        self._task.add_done_callback(self._task_done)

    async def _deliver(
        self,
        candidate: GridOutageReductionCandidate,
        context: GridOutageDispatchContext,
    ) -> None:
        manual = self.manual
        if manual is None:
            self.engine.record_pre_dispatch_rejection(
                candidate,
                rejected_at=datetime.now(UTC),
                reason="manual_transport_unavailable",
            )
            return
        delivery = ManualIntelliCenterGridOutageDelivery(manual, context)
        try:
            await delivery.deliver(candidate)
        except ManualIntelliCenterCommandNotDispatchedError as exc:
            self.engine.record_pre_dispatch_rejection(
                candidate,
                rejected_at=datetime.now(UTC),
                reason=str(exc),
            )
            return
        except Exception as exc:
            self.engine.record_delivery_failure(
                failed_at=datetime.now(UTC), reason=type(exc).__name__
            )
            return
        self.engine.record_accepted_delivery(candidate, accepted_at=datetime.now(UTC))

    def _task_done(self, task: asyncio.Task[object]) -> None:
        if task is not self._task:
            return
        self._task = None
        try:
            task.result()
        except asyncio.CancelledError:
            if not self._unloaded:
                self.engine.record_delivery_failure(
                    failed_at=datetime.now(UTC), reason="task_cancelled"
                )
        except Exception:
            LOGGER.exception("PoolOS grid-outage safety task failed closed")
            self.engine.record_delivery_failure(
                failed_at=datetime.now(UTC), reason="runtime_exception"
            )
        if not self._unloaded:
            self.coordinator.async_update_listeners()
        pending = self._pending
        self._pending = None
        if not self._unloaded and pending is not None:
            self._process_frame(*pending)

    def prepare_unload(self) -> None:
        """Invalidate all authority and await any command already inside dispatch."""

        if self._unloaded:
            return
        self._unloaded = True
        self.authority.set_grid_outage_domain_state(
            active=False,
            outage_epoch_id=None,
        )
        self.authority.unload_grid_outage_safety()
        self.engine.unload(unloaded_at=datetime.now(UTC))
        self._pending = None
        self._pool_shutdown_entitlement_epoch = None
        self._pool_shutdown_entitled = False
        self._filtration_satisfied_commissioning_override = False

    async def async_unload(self) -> None:
        """Drain command-free work after the synchronous scheduling fence."""

        self.prepare_unload()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception("PoolOS grid-outage task ended during unload")
        self._task = None

    def diagnostics(self) -> dict[str, object]:
        assessment = self.engine.assessment
        if assessment is None:
            return {
                "state": GridOutageSafetyLifecycle.INACTIVE.value,
                "outage_gate_requested": self.enabled,
                "outage_gate_effective": self.enabled and not self._unloaded,
                "gate_generation": self.engine.gate_generation,
                "command_delivery_performed": False,
                "command_delivery_enabled": False,
                "effective_state_resets_off_on_restart": True,
            }
        return {
            **dict(assessment.diagnostics()),
            "outage_gate_requested": self.enabled,
            "outage_gate_effective": self.enabled and not self._unloaded,
            "gate_generation": self.engine.gate_generation,
            "effective_state_resets_off_on_restart": True,
            "automatic_thermal_gate_independent": True,
            "thermal_live_gate_independent": True,
            "commissioning_scope_independent": True,
            "pool_shutdown_entitlement_latched": self._pool_shutdown_entitled,
            "filtration_satisfied_commissioning_override": (
                self._filtration_satisfied_commissioning_override
            ),
            "filtration_satisfied_override_requires_simulated_outage": True,
            "production_filtration_ledger_mutated_by_override": False,
        }


__all__ = ["PoolOSGridOutageSafetyRuntime"]
