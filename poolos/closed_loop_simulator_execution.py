"""Closed-loop simulator execution for one immutable execution plan.

This module composes the existing coordinator, simulator delivery, canonical
observation store, and verification engine.  It deliberately keeps plan and
step lifecycle separate: the plan remains ``EXECUTING`` while each step moves
through delivery and verification states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .execution_coordinator import (
    CoordinationDisposition,
    ExecutionCoordinationSession,
    ExecutionCoordinator,
)
from .execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep, VerificationStatus
from .execution_simulator_delivery import (
    SimulatorStepDeliveryEngine,
    SimulatorStepDeliveryRequest,
    SimulatorStepDeliveryResult,
)
from .execution_step_state_machine import (
    ExecutionStepLifecycle,
    ExecutionStepStateMachine,
    ExecutionStepStatus,
)
from .execution_verification import (
    ExecutionVerificationEngine,
    ExecutionVerificationRequest,
    ExecutionVerificationResult,
)
from .integration import SetHeatMode, SetHydraulicRoute, SetPumpSpeed, StartPump, StopPump
from .observations import (
    FreshnessPolicy,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
)


class ClosedLoopExecutionDisposition(str, Enum):
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


@dataclass(slots=True)
class SimulatedEquipmentState:
    """Minimal deterministic state mutated by canonical operations."""

    values: dict[str, Any] = field(default_factory=dict)

    def apply(self, step: ExecutionStep) -> Mapping[str, Any]:
        operation = step.operation
        changed: dict[str, Any]
        if isinstance(operation, StartPump):
            changed = {f"pump.{operation.equipment_id}.running": True}
        elif isinstance(operation, StopPump):
            changed = {
                f"pump.{operation.equipment_id}.running": False,
                f"pump.{operation.equipment_id}.speed_rpm": 0,
            }
        elif isinstance(operation, SetPumpSpeed):
            changed = {
                f"pump.{operation.equipment_id}.running": True,
                f"pump.{operation.equipment_id}.speed_rpm": operation.rpm,
            }
        elif isinstance(operation, SetHydraulicRoute):
            changed = {
                f"hydraulics.{operation.equipment_id}.suction_body_id": operation.suction_body_id,
                f"hydraulics.{operation.equipment_id}.return_body_id": operation.return_body_id,
            }
        elif isinstance(operation, SetHeatMode):
            changed = {f"heat.{operation.equipment_id}.mode": operation.mode}
        else:
            raise TypeError(f"unsupported simulated operation: {type(operation).__name__}")
        self.values.update(changed)
        return MappingProxyType(changed)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosedLoopStepResult:
    step: ExecutionStep
    delivery: SimulatorStepDeliveryResult
    step_lifecycle: ExecutionStepLifecycle
    verification: ExecutionVerificationResult
    observations: tuple[PoolObservation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosedLoopExecutionResult:
    disposition: ClosedLoopExecutionDisposition
    plan: ExecutionPlan
    session: ExecutionCoordinationSession
    step_results: tuple[ClosedLoopStepResult, ...]
    observations: tuple[PoolObservation, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_results", tuple(self.step_results))
        object.__setattr__(self, "observations", tuple(self.observations))
        if self.disposition is ClosedLoopExecutionDisposition.COMPLETED:
            if self.failure_reason is not None:
                raise ValueError("completed execution cannot contain failure_reason")
            if self.session.lifecycle.status is not ExecutionLifecycleStatus.COMPLETED:
                raise ValueError("completed execution requires completed plan lifecycle")
        elif not self.failure_reason:
            raise ValueError("non-completed execution requires failure_reason")


@dataclass(slots=True)
class ClosedLoopSimulatorExecutionEngine:
    """Run an admitted plan to completion through simulator-only feedback."""

    delivery_engine: SimulatorStepDeliveryEngine
    coordinator: ExecutionCoordinator = field(default_factory=ExecutionCoordinator)
    verification_engine: ExecutionVerificationEngine = field(default_factory=ExecutionVerificationEngine)
    step_state_machine: ExecutionStepStateMachine = field(default_factory=ExecutionStepStateMachine)
    simulated_state: SimulatedEquipmentState = field(default_factory=SimulatedEquipmentState)
    source_id: str = "poolos-closed-loop-simulator"
    freshness_policy: FreshnessPolicy = field(
        default_factory=lambda: FreshnessPolicy(max_age=timedelta(minutes=1))
    )
    verification_timeout: timedelta = timedelta(seconds=30)

    def execute(
        self,
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        observations: ObservationStore,
        *,
        occurred_at: datetime,
    ) -> ClosedLoopExecutionResult:
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if session.plan_id != plan.plan_id:
            raise ValueError("session plan_id must match plan")
        if session.lifecycle.status is not ExecutionLifecycleStatus.EXECUTING:
            raise ValueError("plan lifecycle must be EXECUTING")
        if session.stopped:
            raise ValueError("closed-loop execution requires an active session")

        current_session = session
        step_results: list[ClosedLoopStepResult] = []
        generated: list[PoolObservation] = []
        cursor = occurred_at

        while True:
            selected = self.coordinator.current_step(plan, current_session)
            if selected.disposition is not CoordinationDisposition.READY or selected.current_step is None:
                return self._failed(plan, current_session, step_results, generated, selected.rejection_reason or "current_step_unavailable")
            step = selected.current_step
            step_lifecycle = self.step_state_machine.initialize(
                plan_id=plan.plan_id,
                step_id=step.step_id,
                initialized_at=cursor,
            )
            delivery = self.delivery_engine.deliver(
                self._delivery_request(plan, step, step_lifecycle, cursor)
            )
            if not delivery.delivered:
                return self._failed(
                    plan,
                    current_session,
                    step_results,
                    generated,
                    delivery.failure_reason or delivery.disposition.value,
                )

            changed = self.simulated_state.apply(step)
            step_observations = tuple(
                PoolObservation(
                    observation_id=observation_id,
                    value=value,
                    observed_at=cursor,
                    source_kind=ObservationSourceKind.SIMULATED,
                    source_id=self.source_id,
                    quality=ObservationQuality.GOOD,
                    confidence=1.0,
                )
                for observation_id, value in sorted(changed.items())
            )
            observations.extend(step_observations)
            generated.extend(step_observations)

            verifying = self.step_state_machine.transition(
                delivery.lifecycle,
                to_status=ExecutionStepStatus.VERIFYING,
                occurred_at=cursor,
                reason="Simulator observations published for verification.",
                actor="closed-loop-simulator",
                metadata={"step_id": step.step_id},
            )
            if not verifying.applied:
                return self._failed(plan, current_session, step_results, generated, verifying.rejection_reason or "step_verifying_transition_rejected")

            verification = self.verification_engine.verify(
                ExecutionVerificationRequest(
                    plan_id=plan.plan_id,
                    step=step,
                    observations=observations,
                    verification_started_at=cursor,
                    evaluated_at=cursor,
                    timeout=self.verification_timeout,
                    freshness_policy=self.freshness_policy,
                    source_kind=ObservationSourceKind.SIMULATED,
                    source_id=self.source_id,
                )
            )
            if verification.status not in {
                VerificationStatus.VERIFIED,
                VerificationStatus.NOT_REQUIRED,
            }:
                target = (
                    ExecutionStepStatus.TIMED_OUT
                    if verification.status is VerificationStatus.TIMED_OUT
                    else ExecutionStepStatus.FAILED
                )
                failed_step = self.step_state_machine.transition(
                    verifying.lifecycle,
                    to_status=target,
                    occurred_at=cursor,
                    reason=f"verification_{verification.status.value}",
                    actor="closed-loop-simulator",
                ).lifecycle
                step_results.append(
                    ClosedLoopStepResult(
                        step=step,
                        delivery=delivery,
                        step_lifecycle=failed_step,
                        verification=verification,
                        observations=step_observations,
                    )
                )
                return self._failed(plan, current_session, step_results, generated, verification.reason)

            verified = self.step_state_machine.transition(
                verifying.lifecycle,
                to_status=ExecutionStepStatus.VERIFIED,
                occurred_at=cursor,
                reason="Expected simulated observations verified.",
                actor="closed-loop-simulator",
            )
            if not verified.applied:
                return self._failed(plan, current_session, step_results, generated, verified.rejection_reason or "step_verified_transition_rejected")
            step_results.append(
                ClosedLoopStepResult(
                    step=step,
                    delivery=delivery,
                    step_lifecycle=verified.lifecycle,
                    verification=verification,
                    observations=step_observations,
                )
            )

            cursor += timedelta(microseconds=1)
            advanced = self.coordinator.acknowledge_step_completion(
                plan,
                current_session,
                step_id=step.step_id,
                occurred_at=cursor,
                reason="Simulator delivery and observation verification completed.",
                metadata={"verification_id": verification.verification_id},
            )
            if not advanced.accepted:
                return self._failed(plan, current_session, step_results, generated, advanced.rejection_reason or "coordinator_advance_rejected")
            current_session = advanced.session
            if advanced.disposition is CoordinationDisposition.STOPPED:
                cursor += timedelta(microseconds=1)
                completed = self.coordinator.complete_plan(
                    plan,
                    current_session,
                    occurred_at=cursor,
                    metadata={"completed_by": "closed-loop-simulator"},
                )
                if not completed.accepted:
                    return self._failed(plan, current_session, step_results, generated, completed.rejection_reason or "plan_completion_rejected")
                return ClosedLoopExecutionResult(
                    disposition=ClosedLoopExecutionDisposition.COMPLETED,
                    plan=plan,
                    session=completed.session,
                    step_results=tuple(step_results),
                    observations=tuple(generated),
                )
            cursor += timedelta(microseconds=1)

    @staticmethod
    def _failed(
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        step_results: list[ClosedLoopStepResult],
        observations: list[PoolObservation],
        reason: str,
    ) -> ClosedLoopExecutionResult:
        return ClosedLoopExecutionResult(
            disposition=ClosedLoopExecutionDisposition.FAILED,
            plan=plan,
            session=session,
            step_results=tuple(step_results),
            observations=tuple(observations),
            failure_reason=reason,
        )

    @staticmethod
    def _delivery_request(
        plan: ExecutionPlan,
        step: ExecutionStep,
        lifecycle: ExecutionStepLifecycle,
        occurred_at: datetime,
    ) -> SimulatorStepDeliveryRequest:
        return SimulatorStepDeliveryRequest(
            plan=plan,
            step=step,
            lifecycle=lifecycle,
            occurred_at=occurred_at,
        )
