"""Narrow, fail-closed live execution for commissioned thermal plans.

This module is the only live-authority exception to PoolOS's simulator-only
execution posture.  It accepts Phase 1 thermal plans, authorizes one step at a
time, delegates delivery through an injected thermal-only port, and requires
authoritative native verification before the coordinator may advance.

It performs no polling, retry, Home Assistant import, startup scheduling,
hydraulic routing, body activation, or configuration mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping, Protocol

from .environment import RuntimeMode
from .execution_coordinator import (
    CoordinationDisposition,
    ExecutionCoordinationResult,
    ExecutionCoordinationSession,
    ExecutionCoordinator,
)
from .execution_flight_recorder import ExecutionRecorder
from .execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionLifecycleStatus,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionProposal,
    ExecutionStep,
    StepOutcome,
    VerificationStatus,
)
from .execution_plans import (
    DeterministicExecutionPlanBuilder,
    ExecutionPlanBuildRequest,
    ExecutionStepSpecification,
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
    VerificationEvidenceDisposition,
)
from .hal import CommandReceipt, CommandStatus
from .integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from .native_configuration_policy import (
    AutonomousCapability,
    NativeConfigurationAssessment,
)
from .observations import (
    FreshnessPolicy,
    ObservationSourceKind,
    ObservationStore,
)
from .operating_baselines import PumpOperatingBaselines
from .thermal_execution_planning import (
    ThermalExecutionPlanAssessment,
    ThermalPlanDisposition,
)


COMMISSIONED_THERMAL_PUMP_ID = "p0102"


class ThermalLiveCommissioningScope(StrEnum):
    """The one body, if any, eligible for initial live commissioning."""

    DISABLED = "disabled"
    POOL = "pool"
    HOT_TUB = "hot_tub"


class ThermalLiveAuthorizationDisposition(StrEnum):
    AUTHORIZED = "authorized"
    BLOCKED = "blocked"


class ThermalLiveExecutionStatus(StrEnum):
    READY = "ready"
    AWAITING_VERIFICATION = "awaiting_verification"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ThermalLiveExecutionPolicy:
    """Explicit kill switch and commissioned live scope; both default off."""

    thermal_live_execution_enabled: bool = False
    commissioning_scope: ThermalLiveCommissioningScope = (
        ThermalLiveCommissioningScope.DISABLED
    )
    maximum_plan_age: timedelta = timedelta(minutes=2)
    verification_timeout: timedelta = timedelta(seconds=30)
    observation_freshness: timedelta = timedelta(seconds=30)
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()

    def __post_init__(self) -> None:
        if self.maximum_plan_age <= timedelta(0):
            raise ValueError("maximum_plan_age must be positive")
        if self.verification_timeout <= timedelta(0):
            raise ValueError("verification_timeout must be positive")
        if self.observation_freshness <= timedelta(0):
            raise ValueError("observation_freshness must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class ThermalLiveSafetyEvidence:
    """Explicit current evidence required before each physical step."""

    evaluated_at: datetime
    evaluation_id: str
    current_evaluation_id: str
    current_plan_id: str
    native_transport_available: bool
    manual_transport_available: bool
    required_observations_fresh: bool
    observation_health_acceptable: bool
    body_active: bool
    hydraulic_safety_acceptable: bool
    native_configuration: NativeConfigurationAssessment
    contradictory_evidence: tuple[str, ...] = ()
    interrupted_execution_present: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")
        for name in ("evaluation_id", "current_evaluation_id", "current_plan_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        contradictions = tuple(self.contradictory_evidence)
        if any(not item.strip() for item in contradictions):
            raise ValueError("contradictory_evidence must not contain empty values")
        object.__setattr__(self, "contradictory_evidence", contradictions)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ThermalLiveAuthorizationResult:
    authorization_id: str
    disposition: ThermalLiveAuthorizationDisposition
    evaluated_at: datetime
    plan_id: str
    step_index: int
    operation_id: str | None
    blocking_reasons: tuple[str, ...]
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.authorization_id.strip() or not self.plan_id.strip():
            raise ValueError("authorization_id and plan_id must not be empty")
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.step_index < 0:
            raise ValueError("step_index must not be negative")
        if self.disposition is ThermalLiveAuthorizationDisposition.AUTHORIZED:
            if self.blocking_reasons or self.operation_id is None:
                raise ValueError("authorized result requires only an operation")
        elif not self.blocking_reasons:
            raise ValueError("blocked result requires blocking reasons")
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def authorized(self) -> bool:
        return self.disposition is ThermalLiveAuthorizationDisposition.AUTHORIZED


class ThermalLiveDeliveryPort(Protocol):
    """Injected async port exposing only Phase 2 thermal operations."""

    @property
    def available(self) -> bool: ...

    async def deliver(
        self,
        operation: PoolOperation,
        *,
        correlation_id: str,
    ) -> CommandReceipt: ...


@dataclass(frozen=True, slots=True)
class ThermalLiveStepAttempt:
    step: ExecutionStep
    authorization: ThermalLiveAuthorizationResult
    lifecycle: ExecutionStepLifecycle
    receipt: CommandReceipt | None = None
    verifications: tuple[ExecutionVerificationResult, ...] = ()
    verified_hold_started_at: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.verified_hold_started_at is not None:
            _require_aware(
                self.verified_hold_started_at,
                "verified_hold_started_at",
            )
        object.__setattr__(self, "verifications", tuple(self.verifications))


@dataclass(frozen=True, slots=True)
class ThermalLiveExecutionSession:
    assessment: ThermalExecutionPlanAssessment
    execution_plan: ExecutionPlan
    coordination: ExecutionCoordinationSession
    evaluation_id: str
    status: ThermalLiveExecutionStatus
    started_at: datetime
    updated_at: datetime
    attempts: tuple[ThermalLiveStepAttempt, ...] = ()
    current_attempt: ThermalLiveStepAttempt | None = None
    failure_reason: str | None = None
    outcome: ExecutionOutcome | None = None

    def __post_init__(self) -> None:
        _require_aware(self.started_at, "started_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at cannot precede started_at")
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id must not be empty")
        if self.execution_plan.plan_id != self.coordination.plan_id:
            raise ValueError("coordination must reference execution_plan")
        if self.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION:
            if self.current_attempt is None or self.current_attempt.receipt is None:
                raise ValueError("awaiting verification requires a delivered attempt")
        if self.status in {
            ThermalLiveExecutionStatus.BLOCKED,
            ThermalLiveExecutionStatus.FAILED,
            ThermalLiveExecutionStatus.TIMED_OUT,
            ThermalLiveExecutionStatus.SUPERSEDED,
        } and not self.failure_reason:
            raise ValueError("terminal failure status requires failure_reason")
        object.__setattr__(self, "attempts", tuple(self.attempts))


@dataclass(frozen=True, slots=True)
class ThermalLiveAuthorizationEngine:
    """Authorize exactly one current Phase 1 thermal step, default deny."""

    boundary_name: str = "poolos.thermal_live_authorization"

    def authorize(
        self,
        assessment: ThermalExecutionPlanAssessment,
        *,
        step_index: int,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
    ) -> ThermalLiveAuthorizationResult:
        operation = (
            assessment.operations[step_index]
            if 0 <= step_index < len(assessment.operations)
            else None
        )
        reasons = self._blocking_reasons(
            assessment,
            operation=operation,
            step_index=step_index,
            policy=policy,
            evidence=evidence,
        )
        disposition = (
            ThermalLiveAuthorizationDisposition.BLOCKED
            if reasons
            else ThermalLiveAuthorizationDisposition.AUTHORIZED
        )
        payload = {
            "boundary": self.boundary_name,
            "plan_id": assessment.plan_id,
            "step_index": step_index,
            "operation_id": operation.operation_id if operation else "none",
            "evaluation_id": evidence.evaluation_id,
            "evaluated_at": evidence.evaluated_at.isoformat(),
            "disposition": disposition.value,
            "reasons": reasons,
        }
        authorization_id = "thermal-live-authorization-" + _digest(payload)
        return ThermalLiveAuthorizationResult(
            authorization_id=authorization_id,
            disposition=disposition,
            evaluated_at=evidence.evaluated_at,
            plan_id=assessment.plan_id,
            step_index=step_index,
            operation_id=operation.operation_id if operation else None,
            blocking_reasons=reasons,
            provenance={
                **dict(evidence.metadata),
                "thermal_live_authorization_boundary": self.boundary_name,
                "thermal_live_authorization_id": authorization_id,
                "source_thermal_plan_id": assessment.plan_id,
                "source_evaluation_id": evidence.evaluation_id,
                "requested_mode": assessment.desired.requested_mode,
                "selected_source": assessment.desired.selected_source.value,
                "selected_rpm": str(assessment.desired.required_pump_rpm or ""),
                "source_reason_code": assessment.desired.reason_code,
                "rpm_reason_code": assessment.desired.rpm_reason_code or "",
                "commissioning_scope": policy.commissioning_scope.value,
                "kill_switch_enabled": str(
                    policy.thermal_live_execution_enabled
                ).lower(),
            },
        )

    def technical_preflight_blocking_reasons(
        self,
        assessment: ThermalExecutionPlanAssessment,
        *,
        step_index: int,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
    ) -> tuple[str, ...]:
        """Return technical blockers without creating delivery authorization.

        Only the operator enable and commissioning-scope gates are omitted.
        The returned tuple is diagnostic evidence and cannot be passed to the
        execution engine as authorization.
        """

        operation = (
            assessment.operations[step_index]
            if 0 <= step_index < len(assessment.operations)
            else None
        )
        return self._blocking_reasons(
            assessment,
            operation=operation,
            step_index=step_index,
            policy=policy,
            evidence=evidence,
            include_operator_gates=False,
        )

    def _blocking_reasons(
        self,
        assessment: ThermalExecutionPlanAssessment,
        *,
        operation: PoolOperation | None,
        step_index: int,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
        include_operator_gates: bool = True,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if include_operator_gates:
            if not policy.thermal_live_execution_enabled:
                reasons.append("thermal_live_kill_switch_disabled")
            if policy.commissioning_scope is ThermalLiveCommissioningScope.DISABLED:
                reasons.append("thermal_live_commissioning_scope_disabled")
            elif policy.commissioning_scope.value != assessment.desired.body.value:
                reasons.append("body_outside_commissioning_scope")
        if assessment.disposition is not ThermalPlanDisposition.READY:
            reasons.append("thermal_plan_not_ready")
        if operation is None:
            reasons.append("thermal_step_not_found")
        if step_index >= len(assessment.step_specifications):
            reasons.append("thermal_step_specification_missing")
        elif operation is not None:
            specification = assessment.step_specifications[step_index]
            if specification.operation_id != operation.operation_id:
                reasons.append("thermal_step_identity_mismatch")
            if not specification.expected_observations:
                reasons.append("post_command_expectation_missing")
        if evidence.evaluation_id != evidence.current_evaluation_id:
            reasons.append("evaluation_superseded")
        if evidence.current_plan_id != assessment.plan_id:
            reasons.append("plan_superseded")
        age = evidence.evaluated_at - assessment.desired.evaluated_at
        if age < timedelta(0):
            reasons.append("plan_created_in_future")
        elif age > policy.maximum_plan_age:
            reasons.append("thermal_plan_stale")
        if not evidence.native_transport_available:
            reasons.append("native_observation_transport_unavailable")
        if not evidence.manual_transport_available:
            reasons.append("physical_delivery_transport_unavailable")
        if not evidence.required_observations_fresh:
            reasons.append("authoritative_observations_not_fresh")
        if not evidence.observation_health_acceptable:
            reasons.append("observation_health_unacceptable")
        reasons.extend(
            f"contradictory_evidence:{item}"
            for item in evidence.contradictory_evidence
        )
        if evidence.interrupted_execution_present:
            reasons.append("interrupted_execution_requires_fresh_reevaluation")
        body_activation_step = (
            isinstance(operation, SetBodyActive)
            and operation.active is True
            and operation.equipment_id == assessment.desired.body.value
        )

        if not evidence.hydraulic_safety_acceptable and not body_activation_step:
            reasons.append("hydraulic_safety_model_not_satisfied")
        if not evidence.body_active and not body_activation_step:
            reasons.append("target_body_inactive")
        if operation is not None:
            reasons.extend(
                self._operation_reasons(
                    assessment,
                    operation,
                    policy,
                    step_index=step_index,
                )
            )
        reasons.extend(self._configuration_reasons(assessment, evidence))
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _operation_reasons(
        assessment: ThermalExecutionPlanAssessment,
        operation: PoolOperation,
        policy: ThermalLiveExecutionPolicy,
        *,
        step_index: int,
    ) -> tuple[str, ...]:
        if isinstance(operation, SetBodyActive):
            if operation.equipment_id != assessment.desired.body.value:
                return ("body_activation_body_mismatch",)
            if operation.active is not True:
                return ("autonomous_body_deactivation_not_commissioned",)

            specification = (
                assessment.step_specifications[step_index]
                if 0 <= step_index < len(assessment.step_specifications)
                else None
            )
            if specification is None:
                return ("body_activation_step_specification_missing",)

            expected_concept = (
                "pool.active"
                if assessment.desired.body is ThermalBody.POOL
                else "spa.active"
            )
            if dict(specification.expected_observations) != {
                expected_concept: True
            }:
                return ("body_activation_verification_contract_mismatch",)

            if (
                operation.metadata.get("reason_code")
                != "thermal_body_activation_required"
            ):
                return ("body_activation_reason_mismatch",)

            return ()

        if isinstance(operation, SetPumpSpeed):
            if operation.equipment_id != COMMISSIONED_THERMAL_PUMP_ID:
                return ("uncommissioned_thermal_pump",)

            specification = (
                assessment.step_specifications[step_index]
                if 0 <= step_index < len(assessment.step_specifications)
                else None
            )
            priming_step = (
                specification is not None
                and specification.metadata.get("priming_step") == "true"
            )

            if priming_step:
                assert specification is not None
                if operation.rpm != policy.baselines.priming_rpm:
                    return ("uncommissioned_priming_pump_rpm",)
                if operation.metadata.get("reason_code") != "cold_start_pump_priming":
                    return ("priming_step_reason_mismatch",)
                if specification.metadata.get(
                    "minimum_verified_hold_seconds"
                ) is None:
                    return ("priming_hold_contract_missing",)
                return ()

            expected_rpm = {
                PhysicalHeatMode.SOLAR: policy.baselines.solar_heating_rpm,
                PhysicalHeatMode.GAS: policy.baselines.gas_heating_rpm,
            }.get(assessment.desired.selected_source)
            if expected_rpm is None or operation.rpm != expected_rpm:
                return ("nonthermal_or_uncommissioned_pump_rpm",)
            if assessment.desired.required_pump_rpm != operation.rpm:
                return ("pump_rpm_does_not_match_thermal_plan",)
            return ()
        if isinstance(operation, SetHeatMode):
            if operation.equipment_id != assessment.desired.body.value:
                return ("heat_mode_body_mismatch",)
            if operation.mode is not assessment.desired.selected_source:
                return ("heat_mode_does_not_match_thermal_plan",)
            return ()
        return (f"nonthermal_operation:{type(operation).__name__}",)

    @staticmethod
    def _configuration_reasons(
        assessment: ThermalExecutionPlanAssessment,
        evidence: ThermalLiveSafetyEvidence,
    ) -> tuple[str, ...]:
        relevant = {
            PhysicalHeatMode.SOLAR: {
                AutonomousCapability.SOLAR_SOURCE_SELECTION,
                AutonomousCapability.SOLAR_PUMP_BASELINE,
                AutonomousCapability.GENERAL_PUMP_RPM_OWNERSHIP,
            },
            PhysicalHeatMode.GAS: {
                AutonomousCapability.GAS_PUMP_BASELINE,
                AutonomousCapability.GENERAL_PUMP_RPM_OWNERSHIP,
            },
            PhysicalHeatMode.OFF: set(),
        }[assessment.desired.selected_source]
        disabled = set(evidence.native_configuration.disabled_capabilities)
        affected = relevant & disabled
        if not affected:
            return ()
        conflicts = tuple(
            conflict.code
            for conflict in evidence.native_configuration.conflicts
            if affected & set(conflict.affected_capabilities)
        )
        return tuple(f"native_configuration_conflict:{code}" for code in conflicts)


@dataclass(slots=True)
class ThermalLiveExecutionEngine:
    """Event-driven one-step-at-a-time thermal execution coordinator."""

    authorization_engine: ThermalLiveAuthorizationEngine = field(
        default_factory=ThermalLiveAuthorizationEngine
    )
    coordinator: ExecutionCoordinator = field(default_factory=ExecutionCoordinator)
    step_state_machine: ExecutionStepStateMachine = field(
        default_factory=ExecutionStepStateMachine
    )
    verification_engine: ExecutionVerificationEngine = field(
        default_factory=ExecutionVerificationEngine
    )
    recorder: ExecutionRecorder | None = None

    def begin(
        self,
        assessment: ThermalExecutionPlanAssessment,
        *,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
    ) -> ThermalLiveExecutionSession:
        authorization = self.authorization_engine.authorize(
            assessment,
            step_index=0,
            policy=policy,
            evidence=evidence,
        )
        if not authorization.authorized:
            raise ValueError(
                "thermal live execution not authorized:"
                + ",".join(authorization.blocking_reasons)
            )
        proposal = self._proposal(assessment, evidence)
        generic_authorization = ExecutionAuthorization(
            authorization_id=authorization.authorization_id,
            proposal_id=proposal.proposal_id,
            evaluated_at=evidence.evaluated_at,
            disposition=AuthorizationDisposition.AUTHORIZED,
            reason="Scoped thermal live execution authorized",
            metadata=authorization.provenance,
        )
        built = DeterministicExecutionPlanBuilder(
            plan_id_prefix="thermal-live-plan"
        ).build(
            ExecutionPlanBuildRequest(
                proposal=proposal,
                authorization=generic_authorization,
                step_specifications=self._live_step_specifications(assessment),
                metadata={
                    **dict(authorization.provenance),
                    "thermal_live_execution": "true",
                },
            )
        )
        if not built.built or built.plan is None:
            raise ValueError("thermal live execution plan construction failed")
        plan = built.plan
        if self.recorder is not None:
            self.recorder.record_proposal(proposal)
            self.recorder.record_authorization(generic_authorization)
            self.recorder.record_plan(plan)
        admitted = self.coordinator.admit(plan, occurred_at=evidence.evaluated_at)
        self._record_coordination(admitted)
        if not admitted.accepted:
            raise ValueError(admitted.rejection_reason or "thermal plan admission failed")
        started = self.coordinator.start(
            plan,
            admitted.session,
            occurred_at=evidence.evaluated_at,
        )
        self._record_coordination(started)
        if started.disposition is not CoordinationDisposition.READY:
            raise ValueError(started.rejection_reason or "thermal plan start failed")
        return ThermalLiveExecutionSession(
            assessment=assessment,
            execution_plan=plan,
            coordination=started.session,
            evaluation_id=evidence.evaluation_id,
            status=ThermalLiveExecutionStatus.READY,
            started_at=evidence.evaluated_at,
            updated_at=evidence.evaluated_at,
        )

    async def deliver_current_step(
        self,
        session: ThermalLiveExecutionSession,
        *,
        policy: ThermalLiveExecutionPolicy,
        evidence: ThermalLiveSafetyEvidence,
        delivery: ThermalLiveDeliveryPort,
    ) -> ThermalLiveExecutionSession:
        if session.status is not ThermalLiveExecutionStatus.READY:
            raise ValueError("session is not ready for step delivery")
        selected = self.coordinator.current_step(
            session.execution_plan,
            session.coordination,
        )
        if selected.current_step is None:
            return self._terminal(
                session,
                ThermalLiveExecutionStatus.FAILED,
                "current_step_unavailable",
                evidence.evaluated_at,
            )
        step = selected.current_step
        step_index = step.sequence - 1
        authorization = self.authorization_engine.authorize(
            session.assessment,
            step_index=step_index,
            policy=policy,
            evidence=evidence,
        )
        if not authorization.authorized:
            status = (
                ThermalLiveExecutionStatus.SUPERSEDED
                if {"evaluation_superseded", "plan_superseded"}
                & set(authorization.blocking_reasons)
                else ThermalLiveExecutionStatus.BLOCKED
            )
            return self._terminal(
                session,
                status,
                ",".join(authorization.blocking_reasons),
                evidence.evaluated_at,
            )
        binding_reasons = self._operation_binding_reasons(
            session,
            step=step,
            authorization=authorization,
        )
        if binding_reasons:
            return self._terminal(
                session,
                ThermalLiveExecutionStatus.BLOCKED,
                ",".join(binding_reasons),
                evidence.evaluated_at,
            )
        if not delivery.available:
            return self._terminal(
                session,
                ThermalLiveExecutionStatus.BLOCKED,
                "physical_delivery_port_unavailable",
                evidence.evaluated_at,
            )
        lifecycle = self.step_state_machine.initialize(
            plan_id=session.execution_plan.plan_id,
            step_id=step.step_id,
            initialized_at=evidence.evaluated_at,
        )
        delivering = self.step_state_machine.transition(
            lifecycle,
            to_status=ExecutionStepStatus.DELIVERING,
            occurred_at=evidence.evaluated_at,
            reason="Scoped thermal live step delivery started.",
            actor="thermal-live-execution",
            metadata={"authorization_id": authorization.authorization_id},
        )
        if not delivering.applied:
            return self._terminal(
                session,
                ThermalLiveExecutionStatus.FAILED,
                delivering.rejection_reason or "delivery_transition_rejected",
                evidence.evaluated_at,
            )
        correlation_id = (
            f"{session.execution_plan.plan_id}:{step.step_id}:"
            f"{authorization.authorization_id}"
        )
        try:
            receipt = await delivery.deliver(
                step.operation,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            failed = self.step_state_machine.transition(
                delivering.lifecycle,
                to_status=ExecutionStepStatus.FAILED,
                occurred_at=evidence.evaluated_at,
                reason=f"delivery_exception:{type(exc).__name__}",
                actor="thermal-live-execution",
            )
            attempt = ThermalLiveStepAttempt(
                step=step,
                authorization=authorization,
                lifecycle=failed.lifecycle,
                failure_reason=f"delivery_exception:{type(exc).__name__}",
            )
            return self._terminal(
                replace(session, current_attempt=attempt),
                ThermalLiveExecutionStatus.FAILED,
                f"delivery_exception:{type(exc).__name__}",
                evidence.evaluated_at,
            )
        if not receipt.accepted:
            status = (
                ThermalLiveExecutionStatus.TIMED_OUT
                if receipt.status is CommandStatus.TIMED_OUT
                else ThermalLiveExecutionStatus.FAILED
            )
            step_status = (
                ExecutionStepStatus.TIMED_OUT
                if receipt.status is CommandStatus.TIMED_OUT
                else ExecutionStepStatus.FAILED
            )
            failed = self.step_state_machine.transition(
                delivering.lifecycle,
                to_status=step_status,
                occurred_at=evidence.evaluated_at,
                reason=f"delivery_{receipt.status.value}",
                actor="thermal-live-execution",
                metadata={"command_id": receipt.command_id},
            )
            attempt = ThermalLiveStepAttempt(
                step=step,
                authorization=authorization,
                lifecycle=failed.lifecycle,
                receipt=receipt,
                failure_reason=f"delivery_{receipt.status.value}",
            )
            return self._terminal(
                replace(session, current_attempt=attempt),
                status,
                f"delivery_{receipt.status.value}",
                evidence.evaluated_at,
            )
        delivered = self.step_state_machine.transition(
            delivering.lifecycle,
            to_status=ExecutionStepStatus.DELIVERED,
            occurred_at=evidence.evaluated_at,
            reason="Thermal delivery accepted; native confirmation required.",
            actor="thermal-live-execution",
            metadata={"command_id": receipt.command_id},
        )
        if not delivered.applied:
            return self._terminal(
                session,
                ThermalLiveExecutionStatus.FAILED,
                delivered.rejection_reason or "delivered_transition_rejected",
                evidence.evaluated_at,
            )
        attempt = ThermalLiveStepAttempt(
            step=step,
            authorization=authorization,
            lifecycle=delivered.lifecycle,
            receipt=receipt,
        )
        return replace(
            session,
            status=ThermalLiveExecutionStatus.AWAITING_VERIFICATION,
            updated_at=evidence.evaluated_at,
            current_attempt=attempt,
        )

    def verify_current_step(
        self,
        session: ThermalLiveExecutionSession,
        observations: ObservationStore,
        *,
        policy: ThermalLiveExecutionPolicy,
        evaluated_at: datetime,
        source_id: str | None = None,
    ) -> ThermalLiveExecutionSession:
        if session.status is not ThermalLiveExecutionStatus.AWAITING_VERIFICATION:
            raise ValueError("session is not awaiting verification")
        _require_aware(evaluated_at, "evaluated_at")
        attempt = session.current_attempt
        assert attempt is not None and attempt.receipt is not None
        lifecycle = attempt.lifecycle
        if lifecycle.status is ExecutionStepStatus.DELIVERED:
            verifying = self.step_state_machine.transition(
                lifecycle,
                to_status=ExecutionStepStatus.VERIFYING,
                occurred_at=evaluated_at,
                reason="Authoritative native verification started.",
                actor="thermal-live-execution",
            )
            if not verifying.applied:
                return self._terminal(
                    session,
                    ThermalLiveExecutionStatus.FAILED,
                    verifying.rejection_reason or "verification_transition_rejected",
                    evaluated_at,
                )
            lifecycle = verifying.lifecycle
        minimum_hold = _minimum_verified_hold(attempt.step)
        hold_in_progress = (
            minimum_hold > timedelta(0)
            and attempt.verified_hold_started_at is not None
        )

        verification = self.verification_engine.verify(
            ExecutionVerificationRequest(
                plan_id=session.execution_plan.plan_id,
                step=attempt.step,
                observations=observations,
                verification_started_at=(
                    evaluated_at
                    if hold_in_progress
                    else attempt.receipt.issued_at
                ),
                evaluated_at=evaluated_at,
                timeout=policy.verification_timeout,
                freshness_policy=FreshnessPolicy(
                    max_age=policy.observation_freshness
                ),
                source_kind=ObservationSourceKind.LIVE,
                source_id=source_id,
                metadata={
                    "source_thermal_plan_id": session.assessment.plan_id,
                    "source_authorization_id": attempt.authorization.authorization_id,
                    "source_command_id": attempt.receipt.command_id,
                },
            )
        )
        if self.recorder is not None:
            self.recorder.record_verification(verification)
        updated_attempt = replace(
            attempt,
            lifecycle=lifecycle,
            verifications=(*attempt.verifications, verification),
        )
        updated = replace(
            session,
            updated_at=evaluated_at,
            current_attempt=updated_attempt,
        )
        if verification.status is VerificationStatus.VERIFIED:
            if minimum_hold > timedelta(0):
                hold_started_at = attempt.verified_hold_started_at

                if hold_started_at is None:
                    holding_attempt = replace(
                        updated_attempt,
                        verified_hold_started_at=evaluated_at,
                    )
                    return replace(
                        updated,
                        updated_at=evaluated_at,
                        current_attempt=holding_attempt,
                    )

                if evaluated_at - hold_started_at < minimum_hold:
                    return updated

            verified = self.step_state_machine.transition(
                lifecycle,
                to_status=ExecutionStepStatus.VERIFIED,
                occurred_at=evaluated_at,
                reason="Authoritative native expectation verified.",
                actor="thermal-live-execution",
                metadata={"verification_id": verification.verification_id},
            )
            if not verified.applied:
                return self._terminal(
                    updated,
                    ThermalLiveExecutionStatus.FAILED,
                    verified.rejection_reason or "verified_transition_rejected",
                    evaluated_at,
                )
            finished_attempt = replace(updated_attempt, lifecycle=verified.lifecycle)
            advanced = self.coordinator.acknowledge_step_completion(
                session.execution_plan,
                session.coordination,
                step_id=attempt.step.step_id,
                occurred_at=evaluated_at,
                reason="Thermal step delivery and native verification completed.",
                metadata={"verification_id": verification.verification_id},
            )
            self._record_coordination(advanced)
            attempts = (*session.attempts, finished_attempt)
            if advanced.disposition is CoordinationDisposition.STOPPED:
                completed = self.coordinator.complete_plan(
                    session.execution_plan,
                    advanced.session,
                    occurred_at=evaluated_at,
                    metadata={"completed_by": "thermal-live-execution"},
                )
                self._record_coordination(completed)
                if not completed.accepted:
                    return self._terminal(
                        updated,
                        ThermalLiveExecutionStatus.FAILED,
                        completed.rejection_reason or "plan_completion_rejected",
                        evaluated_at,
                    )
                outcome = self._outcome(
                    session,
                    attempts,
                    status=ExecutionLifecycleStatus.VERIFIED,
                    completed_at=evaluated_at,
                )
                if self.recorder is not None:
                    self.recorder.record_outcome(outcome)
                return replace(
                    session,
                    coordination=completed.session,
                    status=ThermalLiveExecutionStatus.COMPLETED,
                    updated_at=evaluated_at,
                    attempts=attempts,
                    current_attempt=None,
                    outcome=outcome,
                )
            if advanced.disposition is not CoordinationDisposition.READY:
                return self._terminal(
                    updated,
                    ThermalLiveExecutionStatus.FAILED,
                    advanced.rejection_reason or "coordinator_advance_rejected",
                    evaluated_at,
                )
            return replace(
                session,
                coordination=advanced.session,
                status=ThermalLiveExecutionStatus.READY,
                updated_at=evaluated_at,
                attempts=attempts,
                current_attempt=None,
            )

        unusable = {
            VerificationEvidenceDisposition.MISSING,
            VerificationEvidenceDisposition.STALE,
            VerificationEvidenceDisposition.FUTURE,
            VerificationEvidenceDisposition.UNUSABLE,
            VerificationEvidenceDisposition.LOW_CONFIDENCE,
        }

        # Once a priming hold has begun, the commanded priming state has
        # already converged. Fresh usable evidence that no longer satisfies
        # that verified state breaks continuity and must fail closed rather
        # than receiving the normal post-command convergence grace period.
        if (
            hold_in_progress
            and verification.status is not VerificationStatus.VERIFIED
            and not (
                unusable
                & {item.disposition for item in verification.evidence}
            )
        ):
            return self._terminal(
                updated,
                ThermalLiveExecutionStatus.FAILED,
                "priming_verified_hold_continuity_lost",
                evaluated_at,
            )
        if unusable & {item.disposition for item in verification.evidence}:
            return self._terminal(
                updated,
                ThermalLiveExecutionStatus.FAILED,
                "authoritative_verification_evidence_unusable",
                evaluated_at,
            )
        if verification.status is VerificationStatus.TIMED_OUT:
            return self._terminal(
                updated,
                ThermalLiveExecutionStatus.TIMED_OUT,
                verification.reason,
                evaluated_at,
            )
        if verification.status is VerificationStatus.FAILED:
            return self._terminal(
                updated,
                ThermalLiveExecutionStatus.FAILED,
                verification.reason,
                evaluated_at,
            )
        return updated

    @staticmethod
    def _proposal(
        assessment: ThermalExecutionPlanAssessment,
        evidence: ThermalLiveSafetyEvidence,
    ) -> ExecutionProposal:
        operations = tuple(
            ThermalLiveExecutionEngine._live_operation(
                operation,
                source_thermal_plan_id=assessment.plan_id,
            )
            for operation in assessment.operations
        )
        return ExecutionProposal(
            proposal_id=f"thermal-live-proposal:{assessment.plan_id}",
            decision_id=evidence.evaluation_id,
            context_id=f"thermal-context:{evidence.evaluation_id}",
            objective_id=f"thermal:{assessment.desired.body.value}",
            created_at=assessment.desired.evaluated_at,
            runtime_mode=RuntimeMode.LIVE,
            operations=operations,
            reason=assessment.desired.reason_code,
            expected_final_state=assessment.expected_final_state,
            metadata={
                "thermal_planning_path": "true",
                "source_thermal_plan_id": assessment.plan_id,
                "requested_mode": assessment.desired.requested_mode,
                "selected_source": assessment.desired.selected_source.value,
                "selected_rpm": str(assessment.desired.required_pump_rpm or ""),
                "source_reason_code": assessment.desired.reason_code,
                "rpm_reason_code": assessment.desired.rpm_reason_code or "",
                "rationale": " | ".join(assessment.desired.rationale),
            },
        )

    @staticmethod
    def _live_step_specifications(
        assessment: ThermalExecutionPlanAssessment,
    ) -> tuple[ExecutionStepSpecification, ...]:
        return tuple(
            ExecutionStepSpecification(
                operation_id=specification.operation_id,
                preconditions={
                    **dict(specification.preconditions),
                    "command_delivery_enabled": True,
                    "thermal_live_authorization_required": True,
                },
                expected_observations=specification.expected_observations,
                verification_required=specification.verification_required,
                metadata={
                    **dict(specification.metadata),
                    "source_thermal_plan_id": assessment.plan_id,
                    "thermal_live_authorization_required": "true",
                },
            )
            for specification in assessment.step_specifications
        )

    @staticmethod
    def _live_operation(
        operation: PoolOperation,
        *,
        source_thermal_plan_id: str,
    ) -> PoolOperation:
        """Return the exact typed live derivative of one Phase 1 operation."""

        return replace(
            operation,
            metadata={
                **dict(operation.metadata),
                "command_delivery_enabled": True,
                "thermal_live_authorized_path": True,
                "source_thermal_plan_id": source_thermal_plan_id,
            },
        )

    @staticmethod
    def _operation_binding_reasons(
        session: ThermalLiveExecutionSession,
        *,
        step: ExecutionStep,
        authorization: ThermalLiveAuthorizationResult,
    ) -> tuple[str, ...]:
        """Bind the authorized Phase 1 operation to the exact delivered object."""

        step_index = step.sequence - 1
        if not 0 <= step_index < len(session.assessment.operations):
            return ("authorized_operation_step_out_of_range",)
        assessment_operation = session.assessment.operations[step_index]
        expected_live_operation = ThermalLiveExecutionEngine._live_operation(
            assessment_operation,
            source_thermal_plan_id=session.assessment.plan_id,
        )
        reasons: list[str] = []
        if authorization.operation_id != assessment_operation.operation_id:
            reasons.append("authorization_operation_id_mismatch")
        if step.operation.operation_id != assessment_operation.operation_id:
            reasons.append("execution_plan_operation_id_mismatch")
        if step.operation != expected_live_operation:
            reasons.append("execution_plan_operation_payload_mismatch")
        return tuple(reasons)

    def _record_coordination(self, result: ExecutionCoordinationResult) -> None:
        if self.recorder is None:
            return
        if result.lifecycle_transition is not None:
            self.recorder.record_transition(result.lifecycle_transition)
        if result.event is not None:
            self.recorder.record_coordination_event(result.event)

    def _terminal(
        self,
        session: ThermalLiveExecutionSession,
        status: ThermalLiveExecutionStatus,
        reason: str,
        occurred_at: datetime,
    ) -> ThermalLiveExecutionSession:
        attempts = session.attempts
        if session.current_attempt is not None:
            attempts = (*attempts, replace(session.current_attempt, failure_reason=reason))
        lifecycle_status = {
            ThermalLiveExecutionStatus.TIMED_OUT: ExecutionLifecycleStatus.TIMED_OUT,
            ThermalLiveExecutionStatus.SUPERSEDED: ExecutionLifecycleStatus.SUPERSEDED,
            ThermalLiveExecutionStatus.BLOCKED: ExecutionLifecycleStatus.ABORTED,
        }.get(status, ExecutionLifecycleStatus.FAILED)
        outcome = self._outcome(
            session,
            attempts,
            status=lifecycle_status,
            completed_at=occurred_at,
            failure_reason=reason,
        )
        if self.recorder is not None:
            self.recorder.record_outcome(outcome)
        return replace(
            session,
            status=status,
            updated_at=occurred_at,
            attempts=attempts,
            current_attempt=None,
            failure_reason=reason,
            outcome=outcome,
        )

    @staticmethod
    def _outcome(
        session: ThermalLiveExecutionSession,
        attempts: tuple[ThermalLiveStepAttempt, ...],
        *,
        status: ExecutionLifecycleStatus,
        completed_at: datetime,
        failure_reason: str | None = None,
    ) -> ExecutionOutcome:
        step_outcomes = tuple(
            StepOutcome(
                step_id=attempt.step.step_id,
                status=(
                    ExecutionLifecycleStatus.VERIFIED
                    if attempt.lifecycle.status is ExecutionStepStatus.VERIFIED
                    else status
                ),
                verification_status=(
                    attempt.verifications[-1].status
                    if attempt.verifications
                    else VerificationStatus.PENDING
                ),
                started_at=attempt.lifecycle.initialized_at,
                completed_at=completed_at,
                receipt_ids=(
                    (attempt.receipt.command_id,) if attempt.receipt is not None else ()
                ),
                failure_reason=(
                    attempt.failure_reason
                    if attempt.lifecycle.status is not ExecutionStepStatus.VERIFIED
                    else None
                ),
                metadata={
                    "source_authorization_id": attempt.authorization.authorization_id,
                    "source_reason_code": session.assessment.desired.reason_code,
                    "rpm_reason_code": session.assessment.desired.rpm_reason_code or "",
                },
            )
            for attempt in attempts
        )
        outcome_id = "thermal-live-outcome-" + _digest(
            {
                "plan_id": session.execution_plan.plan_id,
                "status": status.value,
                "completed_at": completed_at.isoformat(),
                "failure_reason": failure_reason or "",
            }
        )
        return ExecutionOutcome(
            outcome_id=outcome_id,
            plan_id=session.execution_plan.plan_id,
            proposal_id=session.execution_plan.proposal_id,
            decision_id=session.execution_plan.decision_id,
            context_id=session.execution_plan.context_id,
            status=status,
            started_at=session.started_at,
            completed_at=completed_at,
            step_outcomes=step_outcomes,
            failure_reason=failure_reason,
            metadata={
                "source_thermal_plan_id": session.assessment.plan_id,
                "requested_mode": session.assessment.desired.requested_mode,
                "selected_source": session.assessment.desired.selected_source.value,
                "selected_rpm": str(
                    session.assessment.desired.required_pump_rpm or ""
                ),
                "source_reason_code": session.assessment.desired.reason_code,
                "rpm_reason_code": session.assessment.desired.rpm_reason_code or "",
            },
        )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _minimum_verified_hold(step: ExecutionStep) -> timedelta:
    """Return an explicitly commissioned verified-state hold duration."""

    raw = step.metadata.get("minimum_verified_hold_seconds")
    if raw is None:
        return timedelta(0)

    try:
        seconds = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "minimum_verified_hold_seconds must be an integer"
        ) from exc

    if seconds <= 0:
        raise ValueError(
            "minimum_verified_hold_seconds must be positive"
        )

    if step.metadata.get("priming_step") != "true":
        raise ValueError(
            "verified hold is currently commissioned only for priming steps"
        )

    return timedelta(seconds=seconds)


__all__ = [
    "COMMISSIONED_THERMAL_PUMP_ID",
    "ThermalLiveAuthorizationDisposition",
    "ThermalLiveAuthorizationEngine",
    "ThermalLiveAuthorizationResult",
    "ThermalLiveCommissioningScope",
    "ThermalLiveDeliveryPort",
    "ThermalLiveExecutionEngine",
    "ThermalLiveExecutionPolicy",
    "ThermalLiveExecutionSession",
    "ThermalLiveExecutionStatus",
    "ThermalLiveSafetyEvidence",
    "ThermalLiveStepAttempt",
]
