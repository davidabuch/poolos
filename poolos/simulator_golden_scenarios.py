"""Permanent deterministic golden scenarios for closed-loop simulator execution.

The scenario runner composes the real simulator-only execution boundaries.  It
is intentionally independent from Home Assistant and physical delivery.  Its
results summarize externally meaningful lifecycle outcomes so architectural
regressions are detected without coupling tests to private implementation calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

from .closed_loop_simulator_execution import (
    ClosedLoopExecutionDisposition,
    ClosedLoopExecutionResult,
    ClosedLoopSimulatorExecutionEngine,
)
from .delivery import DeliveryEndpointKind
from .environment import RuntimeMode, build_runtime_environment
from .execution_coordinator import ExecutionCoordinator
from .execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from .execution_simulator_delivery import SimulatorStepDeliveryEngine
from .execution_step_state_machine import ExecutionStepStatus
from .hal import CommandReceipt, CommandStatus
from .integration import (
    OperationTranslationHandler,
    PoolOperation,
    SetPumpSpeed,
    StartPump,
    TranslationContext,
    TranslationResult,
    TranslatorRegistry,
    VendorCommand,
)
from .observations import ObservationStore
from .simulator_execution_gateway import SimulatorExecutionGateway
from .simulator_faults import (
    SimulatorFaultKind,
    SimulatorFaultPlan,
    SimulatorFaultRecoveryAction,
    SimulatorFaultRule,
)


class SimulatorGoldenScenarioId(str, Enum):
    """Stable identifiers for permanent closed-loop simulator scenarios."""

    SINGLE_STEP_SUCCESS = "single_step_success"
    MULTI_STEP_SUCCESS = "multi_step_success"
    DELIVERY_REJECTED = "delivery_rejected"
    DELIVERY_FAILED = "delivery_failed"
    DELIVERY_TIMED_OUT = "delivery_timed_out"
    OBSERVATION_MISSING = "observation_missing"
    OBSERVATION_STALE = "observation_stale"
    OBSERVATION_MISMATCH = "observation_mismatch"
    VERIFICATION_TIMED_OUT = "verification_timed_out"
    DETERMINISTIC_REPLAY = "deterministic_replay"


@dataclass(frozen=True, slots=True)
class SimulatorGoldenScenarioDefinition:
    """Immutable specification for one simulator golden scenario."""

    scenario_id: SimulatorGoldenScenarioId
    description: str
    expected_disposition: ClosedLoopExecutionDisposition
    expected_plan_status: ExecutionLifecycleStatus
    fault_kind: SimulatorFaultKind | None = None
    expected_recovery_actions: tuple[SimulatorFaultRecoveryAction, ...] = ()

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("description must not be empty")
        actions = tuple(self.expected_recovery_actions)
        if len(actions) != len(set(actions)):
            raise ValueError("expected_recovery_actions must be unique")
        if self.fault_kind is None and actions:
            raise ValueError("recovery actions require a fault kind")
        object.__setattr__(self, "expected_recovery_actions", actions)


SIMULATOR_GOLDEN_SCENARIOS: tuple[SimulatorGoldenScenarioDefinition, ...] = (
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.SINGLE_STEP_SUCCESS,
        "One delivered and verified simulator step completes its plan.",
        ClosedLoopExecutionDisposition.COMPLETED,
        ExecutionLifecycleStatus.COMPLETED,
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.MULTI_STEP_SUCCESS,
        "Each simulator step verifies independently before the plan completes.",
        ClosedLoopExecutionDisposition.COMPLETED,
        ExecutionLifecycleStatus.COMPLETED,
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.DELIVERY_REJECTED,
        "Rejected simulator delivery terminates the step and plan without advancement.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.DELIVERY_REJECTED,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.AWAIT_OPERATOR,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.DELIVERY_FAILED,
        "Failed simulator delivery terminates the step and plan without advancement.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.DELIVERY_FAILED,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.AWAIT_OPERATOR,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.DELIVERY_TIMED_OUT,
        "Timed-out simulator delivery terminates the step and plan without retry.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.DELIVERY_TIMED_OUT,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.AWAIT_OPERATOR,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.OBSERVATION_MISSING,
        "Missing simulated evidence prevents verification and coordinator advancement.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.OBSERVATION_MISSING,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.REEVALUATE,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.OBSERVATION_STALE,
        "Stale simulated evidence prevents verification and coordinator advancement.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.OBSERVATION_STALE,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.REEVALUATE,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.OBSERVATION_MISMATCH,
        "Contradictory simulated evidence fails verification without advancement.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.OBSERVATION_MISMATCH,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.REEVALUATE,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.VERIFICATION_TIMED_OUT,
        "Verification timeout terminates the step and plan without retry.",
        ClosedLoopExecutionDisposition.FAILED,
        ExecutionLifecycleStatus.EXECUTING,
        SimulatorFaultKind.VERIFICATION_TIMEOUT,
        (
            SimulatorFaultRecoveryAction.TERMINATE_STEP,
            SimulatorFaultRecoveryAction.TERMINATE_PLAN,
            SimulatorFaultRecoveryAction.REEVALUATE,
        ),
    ),
    SimulatorGoldenScenarioDefinition(
        SimulatorGoldenScenarioId.DETERMINISTIC_REPLAY,
        "Identical closed-loop inputs produce equivalent immutable outcomes.",
        ClosedLoopExecutionDisposition.COMPLETED,
        ExecutionLifecycleStatus.COMPLETED,
    ),
)

SIMULATOR_GOLDEN_SCENARIO_INDEX: Mapping[
    SimulatorGoldenScenarioId, SimulatorGoldenScenarioDefinition
] = MappingProxyType({item.scenario_id: item for item in SIMULATOR_GOLDEN_SCENARIOS})


def validate_simulator_golden_catalog() -> None:
    """Raise when the permanent simulator scenario catalog is incomplete."""

    identifiers = tuple(item.scenario_id for item in SIMULATOR_GOLDEN_SCENARIOS)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("simulator golden scenario IDs must be unique")
    if set(identifiers) != set(SimulatorGoldenScenarioId):
        raise ValueError("simulator golden scenario catalog is incomplete")


@dataclass(frozen=True, slots=True)
class _GoldenTranslator:
    vendor: str = "golden-simulator"

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, (StartPump, SetPumpSpeed))

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        del context
        if isinstance(operation, StartPump):
            name = "pump.start"
            parameters: Mapping[str, Any] = {}
        elif isinstance(operation, SetPumpSpeed):
            name = "pump.set_speed"
            parameters = {"rpm": operation.rpm}
        else:
            raise TypeError(f"unsupported golden operation: {type(operation).__name__}")
        return TranslationResult(
            commands=(
                VendorCommand(
                    vendor=self.vendor,
                    operation=name,
                    target=operation.equipment_id,
                    parameters=parameters,
                ),
            )
        )


@dataclass(slots=True)
class _RecordingSimulatorEndpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SIMULATOR
    endpoint_id: str = "golden-simulator-endpoint"
    vendor: str = "golden-simulator"
    commands: list[VendorCommand] = field(default_factory=list)

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        del timeout
        self.commands.append(command)
        return CommandReceipt(
            status=CommandStatus.ACKNOWLEDGED,
            command_id=correlation_id,
            message="golden simulator acknowledged command",
            verification_required=True,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatorGoldenScenarioResult:
    """Immutable outcome summary for one permanent scenario execution."""

    scenario_id: SimulatorGoldenScenarioId
    execution: ClosedLoopExecutionResult
    delivered_command_count: int
    completed_step_ids: tuple[str, ...]
    step_statuses: tuple[ExecutionStepStatus, ...]
    outcome_fingerprint: str
    replay_equivalent: bool | None = None

    def __post_init__(self) -> None:
        if self.delivered_command_count < 0:
            raise ValueError("delivered_command_count must not be negative")
        object.__setattr__(self, "completed_step_ids", tuple(self.completed_step_ids))
        object.__setattr__(self, "step_statuses", tuple(self.step_statuses))
        if not self.outcome_fingerprint.strip():
            raise ValueError("outcome_fingerprint must not be empty")


@dataclass(frozen=True, slots=True)
class SimulatorGoldenScenarioRunner:
    """Execute the permanent scenarios through real simulator-only boundaries."""

    occurred_at: datetime = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

    def run(self, scenario_id: SimulatorGoldenScenarioId) -> SimulatorGoldenScenarioResult:
        definition = SIMULATOR_GOLDEN_SCENARIO_INDEX[scenario_id]
        first = self._execute_once(definition)
        if scenario_id is not SimulatorGoldenScenarioId.DETERMINISTIC_REPLAY:
            return first
        second = self._execute_once(definition)
        return SimulatorGoldenScenarioResult(
            scenario_id=first.scenario_id,
            execution=first.execution,
            delivered_command_count=first.delivered_command_count,
            completed_step_ids=first.completed_step_ids,
            step_statuses=first.step_statuses,
            outcome_fingerprint=first.outcome_fingerprint,
            replay_equivalent=first.outcome_fingerprint == second.outcome_fingerprint,
        )

    def run_all(self) -> tuple[SimulatorGoldenScenarioResult, ...]:
        validate_simulator_golden_catalog()
        return tuple(self.run(definition.scenario_id) for definition in SIMULATOR_GOLDEN_SCENARIOS)

    def _execute_once(
        self,
        definition: SimulatorGoldenScenarioDefinition,
    ) -> SimulatorGoldenScenarioResult:
        endpoint = _RecordingSimulatorEndpoint()
        registry = TranslatorRegistry()
        registry.register(_GoldenTranslator())
        translation = OperationTranslationHandler(
            registry,
            lambda operation: TranslationContext(
                vendor="golden-simulator",
                controller_model="deterministic-golden-runner",
            ),
        )
        environment = build_runtime_environment(
            mode=RuntimeMode.SIMULATION,
            installation_id="golden-simulator-installation",
            endpoints=(endpoint,),
        )
        delivery = SimulatorStepDeliveryEngine(
            translation_handler=translation,
            gateway=SimulatorExecutionGateway.from_environment(environment),
        )
        coordinator = ExecutionCoordinator()
        plan = self._plan(definition.scenario_id)
        admitted = coordinator.admit(plan, occurred_at=self.occurred_at)
        started = coordinator.start(plan, admitted.session, occurred_at=self.occurred_at)
        engine = ClosedLoopSimulatorExecutionEngine(
            delivery_engine=delivery,
            coordinator=coordinator,
            fault_plan=self._fault_plan(definition, plan),
        )
        execution = engine.execute(
            plan,
            started.session,
            ObservationStore(),
            occurred_at=self.occurred_at,
        )
        fingerprint = self._fingerprint(execution, len(endpoint.commands))
        return SimulatorGoldenScenarioResult(
            scenario_id=definition.scenario_id,
            execution=execution,
            delivered_command_count=len(endpoint.commands),
            completed_step_ids=execution.session.completed_step_ids,
            step_statuses=tuple(item.step_lifecycle.status for item in execution.step_results),
            outcome_fingerprint=fingerprint,
        )

    def _plan(self, scenario_id: SimulatorGoldenScenarioId) -> ExecutionPlan:
        multi_step = scenario_id in {
            SimulatorGoldenScenarioId.MULTI_STEP_SUCCESS,
            SimulatorGoldenScenarioId.DETERMINISTIC_REPLAY,
        }
        operations: tuple[PoolOperation, ...] = (
            StartPump(
                equipment_id="filter-pump",
                operation_id="golden-operation-1",
            ),
        )
        if multi_step:
            operations += (
                SetPumpSpeed(
                    equipment_id="filter-pump",
                    operation_id="golden-operation-2",
                    rpm=2200,
                ),
            )
        steps = tuple(
            ExecutionStep(
                step_id=f"golden-plan:step:{index}",
                sequence=index,
                operation=operation,
                expected_observations=self._expected(operation),
            )
            for index, operation in enumerate(operations, start=1)
        )
        return ExecutionPlan(
            plan_id="golden-plan",
            proposal_id="golden-proposal",
            authorization_id="golden-authorization",
            decision_id="golden-decision",
            context_id="golden-context",
            created_at=self.occurred_at,
            steps=steps,
            expected_final_state=steps[-1].expected_observations,
        )

    @staticmethod
    def _expected(operation: PoolOperation) -> Mapping[str, Any]:
        if isinstance(operation, StartPump):
            return {f"pump.{operation.equipment_id}.running": True}
        if isinstance(operation, SetPumpSpeed):
            return {
                f"pump.{operation.equipment_id}.running": True,
                f"pump.{operation.equipment_id}.speed_rpm": operation.rpm,
            }
        raise TypeError(f"unsupported golden operation: {type(operation).__name__}")

    @staticmethod
    def _fault_plan(
        definition: SimulatorGoldenScenarioDefinition,
        plan: ExecutionPlan,
    ) -> SimulatorFaultPlan:
        if definition.fault_kind is None:
            return SimulatorFaultPlan()
        replacement: Any | None = None
        if definition.fault_kind is SimulatorFaultKind.OBSERVATION_MISMATCH:
            replacement = False
        return SimulatorFaultPlan(
            (
                SimulatorFaultRule(
                    rule_id=f"golden-fault:{definition.scenario_id.value}",
                    step_id=plan.steps[0].step_id,
                    kind=definition.fault_kind,
                    replacement_value=replacement,
                ),
            )
        )

    @staticmethod
    def _fingerprint(execution: ClosedLoopExecutionResult, command_count: int) -> str:
        payload = {
            "disposition": execution.disposition.value,
            "plan_status": execution.session.lifecycle.status.value,
            "completed_step_ids": execution.session.completed_step_ids,
            "step_statuses": tuple(
                item.step_lifecycle.status.value for item in execution.step_results
            ),
            "verification_statuses": tuple(
                item.verification.status.value for item in execution.step_results
            ),
            "observations": tuple(
                (
                    observation.observation_id,
                    observation.value,
                    (
                        observation.observed_at.isoformat()
                        if observation.observed_at is not None
                        else None
                    ),
                    observation.source_kind.value,
                    observation.source_id,
                )
                for observation in execution.observations
            ),
            "faults": tuple(
                (
                    fault.record_id,
                    fault.kind.value,
                    tuple(action.value for action in fault.recovery_actions),
                    fault.reason,
                )
                for fault in execution.fault_records
            ),
            "failure_reason": execution.failure_reason,
            "command_count": command_count,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode()).hexdigest()


__all__ = [
    "SIMULATOR_GOLDEN_SCENARIOS",
    "SIMULATOR_GOLDEN_SCENARIO_INDEX",
    "SimulatorGoldenScenarioDefinition",
    "SimulatorGoldenScenarioId",
    "SimulatorGoldenScenarioResult",
    "SimulatorGoldenScenarioRunner",
    "validate_simulator_golden_catalog",
]
