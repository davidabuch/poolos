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
    SimulatorStepDeliveryDisposition,
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
from .simulator_faults import (
    SimulatorFaultKind,
    SimulatorFaultPlan,
    SimulatorFaultRecord,
    SimulatorFaultRule,
    build_fault_record,
)
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
    fault_records: tuple[SimulatorFaultRecord, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_results", tuple(self.step_results))
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "fault_records", tuple(self.fault_records))
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
    fault_plan: SimulatorFaultPlan = field(default_factory=SimulatorFaultPlan)

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
        faults: list[SimulatorFaultRecord] = []
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
            step_faults = self.fault_plan.for_step(step.step_id)
            delivery_fault = self._delivery_fault(step_faults)
            delivery = (
                self._inject_delivery_fault(plan, step, step_lifecycle, cursor, delivery_fault)
                if delivery_fault is not None
                else self.delivery_engine.deliver(
                    self._delivery_request(plan, step, step_lifecycle, cursor)
                )
            )
            if delivery_fault is not None:
                faults.append(build_fault_record(
                    delivery_fault, plan_id=plan.plan_id, occurred_at=cursor,
                    reason=delivery.failure_reason or delivery.disposition.value,
                ))
            if not delivery.delivered:
                return self._failed(
                    plan,
                    current_session,
                    step_results,
                    generated,
                    delivery.failure_reason or delivery.disposition.value,
                    faults,
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
            step_observations, observation_fault_records = self._apply_observation_faults(
                plan.plan_id, step, step_observations, step_faults, cursor
            )
            faults.extend(observation_fault_records)
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

            evaluated_at = (
                cursor + self.verification_timeout
                if any(rule.kind is SimulatorFaultKind.VERIFICATION_TIMEOUT for rule in step_faults)
                else cursor
            )
            verification = self.verification_engine.verify(
                ExecutionVerificationRequest(
                    plan_id=plan.plan_id,
                    step=step,
                    observations=observations,
                    verification_started_at=cursor,
                    evaluated_at=evaluated_at,
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
                return self._failed(plan, current_session, step_results, generated, verification.reason, faults)

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
                    fault_records=tuple(faults),
                )
            cursor += timedelta(microseconds=1)


    @staticmethod
    def _delivery_fault(rules: tuple[SimulatorFaultRule, ...]) -> SimulatorFaultRule | None:
        delivery_kinds = {
            SimulatorFaultKind.DELIVERY_REJECTED,
            SimulatorFaultKind.DELIVERY_FAILED,
            SimulatorFaultKind.DELIVERY_TIMED_OUT,
        }
        return next((rule for rule in rules if rule.kind in delivery_kinds), None)

    def _inject_delivery_fault(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        lifecycle: ExecutionStepLifecycle,
        occurred_at: datetime,
        rule: SimulatorFaultRule,
    ) -> SimulatorStepDeliveryResult:
        delivering = self.step_state_machine.transition(
            lifecycle,
            to_status=ExecutionStepStatus.DELIVERING,
            occurred_at=occurred_at,
            reason=f"Injected simulator fault {rule.kind.value}.",
            actor="simulator-fault-injector",
            metadata={"rule_id": rule.rule_id},
        )
        if not delivering.applied or delivering.transition is None:
            raise ValueError(delivering.rejection_reason or "fault delivering transition rejected")
        disposition = {
            SimulatorFaultKind.DELIVERY_REJECTED: SimulatorStepDeliveryDisposition.REJECTED,
            SimulatorFaultKind.DELIVERY_FAILED: SimulatorStepDeliveryDisposition.FAILED,
            SimulatorFaultKind.DELIVERY_TIMED_OUT: SimulatorStepDeliveryDisposition.TIMED_OUT,
        }[rule.kind]
        target = (
            ExecutionStepStatus.TIMED_OUT
            if disposition is SimulatorStepDeliveryDisposition.TIMED_OUT
            else ExecutionStepStatus.FAILED
        )
        finished = self.step_state_machine.transition(
            delivering.lifecycle,
            to_status=target,
            occurred_at=occurred_at,
            reason=f"injected_{rule.kind.value}",
            actor="simulator-fault-injector",
            metadata={"rule_id": rule.rule_id},
        )
        if not finished.applied or finished.transition is None:
            raise ValueError(finished.rejection_reason or "fault terminal transition rejected")
        return SimulatorStepDeliveryResult(
            attempt_id=f"simulator-fault-attempt:{plan.plan_id}:{step.step_id}:{rule.rule_id}",
            plan_id=plan.plan_id,
            step_id=step.step_id,
            disposition=disposition,
            lifecycle=finished.lifecycle,
            transitions=(delivering.transition, finished.transition),
            receipts=(),
            failure_reason=f"injected_{rule.kind.value}",
            metadata={"fault_rule_id": rule.rule_id},
        )

    @staticmethod
    def _apply_observation_faults(
        plan_id: str,
        step: ExecutionStep,
        observations: tuple[PoolObservation, ...],
        rules: tuple[SimulatorFaultRule, ...],
        occurred_at: datetime,
    ) -> tuple[tuple[PoolObservation, ...], tuple[SimulatorFaultRecord, ...]]:
        current = list(observations)
        records: list[SimulatorFaultRecord] = []
        for rule in rules:
            if rule.kind is SimulatorFaultKind.OBSERVATION_MISSING:
                target = rule.observation_id or next(iter(step.expected_observations), None)
                current = [item for item in current if item.observation_id != target]
            elif rule.kind is SimulatorFaultKind.OBSERVATION_STALE:
                target = rule.observation_id or next(iter(step.expected_observations), None)
                current = [
                    PoolObservation(
                        observation_id=item.observation_id, value=item.value,
                        observed_at=item.observed_at - rule.stale_by if item.observed_at is not None else None if item.observation_id == target else item.observed_at,
                        source_kind=item.source_kind, source_id=item.source_id,
                        unit=item.unit, truth_level=item.truth_level, quality=item.quality, confidence=item.confidence, evidence=item.evidence,
                    )
                    for item in current
                ]
            elif rule.kind is SimulatorFaultKind.OBSERVATION_MISMATCH:
                target = rule.observation_id or next(iter(step.expected_observations), None)
                current = [
                    PoolObservation(
                        observation_id=item.observation_id,
                        value=rule.replacement_value if item.observation_id == target else item.value,
                        observed_at=item.observed_at, source_kind=item.source_kind,
                        source_id=item.source_id, quality=item.quality,
                        unit=item.unit, truth_level=item.truth_level, confidence=item.confidence, evidence=item.evidence,
                    )
                    for item in current
                ]
            elif rule.kind is SimulatorFaultKind.VERIFICATION_TIMEOUT:
                target = rule.observation_id or next(iter(step.expected_observations), None)
                current = [item for item in current if item.observation_id != target]
            else:
                continue
            records.append(build_fault_record(
                rule, plan_id=plan_id, occurred_at=occurred_at, reason=f"injected_{rule.kind.value}"
            ))
        return tuple(current), tuple(records)

    @staticmethod
    def _failed(
        plan: ExecutionPlan,
        session: ExecutionCoordinationSession,
        step_results: list[ClosedLoopStepResult],
        observations: list[PoolObservation],
        reason: str,
        fault_records: list[SimulatorFaultRecord] | None = None,
    ) -> ClosedLoopExecutionResult:
        return ClosedLoopExecutionResult(
            disposition=ClosedLoopExecutionDisposition.FAILED,
            plan=plan,
            session=session,
            step_results=tuple(step_results),
            observations=tuple(observations),
            fault_records=tuple(fault_records or ()),
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
