"""Public API for the hardware-independent PoolOS domain and kernel."""

from .authority import (
    AuthorityDecision,
    AuthorityDecisionReason,
    AuthorityLease,
    AuthorityLevel,
    ControlAuthority,
    ControlSource,
    ControlSourceType,
)
from .bodies import Body, BodyRegistry
from .capabilities import Capability
from .clock import Clock, FixedClock, SystemClock
from .commands import Command, CommandAction
from .config import PoolOSConfig
from .enums import (
    BodyType,
    CommandPriority,
    EquipmentType,
    HeatingSource,
    PolicyPriority,
    RecommendationSeverity,
)
from .equipment import Equipment
from .events import EventBus, PoolEvent
from .default_policies import (
    CirculationSafetyPolicy,
    HeatingDemandPolicy,
    SanitizerCirculationInterlockPolicy,
    build_default_policy_engine,
)
from .execution import (
    CommandExecutor,
    ExecutionEngine,
    ExecutionRecord,
    ExecutionStatus,
)
from .exceptions import (
    DuplicatePolicyError,
    DuplicateRegistrationError,
    PoolOSError,
    UnknownBodyError,
    UnknownEquipmentError,
    UnknownPolicyError,
    DuplicatePlanningStrategyError,
    PlanningStrategyNotFoundError,
    PlanNotFoundError,
    DuplicateScheduledPlanError,
    ScheduledPlanNotFoundError,
    ScheduledStepNotFoundError,
)
from .kernel import PoolKernel
from .models import BodyState, TemperatureState
from .policies import (
    Policy,
    PolicyContext,
    PolicyEngine,
    PolicyEvaluation,
    PolicyOutcome,
    PolicySuppression,
)
from .planning import (
    ConditionKind,
    FailureBehavior,
    ObjectiveType,
    Plan,
    PlanCondition,
    PlanObjective,
    PlanStatus,
    PlanStep,
    Planner,
    PlanningStrategy,
)
from .planning_strategies import (
    PrepareBodyByDeadlineStrategy,
    build_default_planner,
)
from .scheduling import (
    ScheduledPlan,
    ScheduledPlanStatus,
    ScheduledStepStatus,
    Scheduler,
    SchedulerEvaluation,
    StepRuntime,
)
from .registry import EquipmentRegistry
from .state import EquipmentState, RuntimeState

# Retain the enum-only list expected by the original Milestone 1 contract test.
# Additional supported symbols remain directly importable from ``poolos``.
from .simulator_faults import (
    SimulatorFaultKind,
    SimulatorFaultPlan,
    SimulatorFaultRecord,
    SimulatorFaultRecoveryAction,
    SimulatorFaultRule,
)

__all__ = [
    "BodyType",
    "CommandPriority",
    "EquipmentType",
    "HeatingSource",
    "PolicyPriority",
    "RecommendationSeverity",
]
from .simulation import (
    BodyThermalModel,
    Simulation,
    SimulationClock,
    SimulationEvent,
    SimulationEventKind,
    SimulationExecutor,
    SimulationResult,
    SimulationScenario,
    SimulationSnapshot,
    WeatherState,
)
from .scenarios import power_outage_scenario, spa_heat_scenario
from .runtime import PoolRuntime, RuntimeCycle, RuntimeStatus
from .constraints import (
    Constraint,
    ConstraintContext,
    ConstraintDecision,
    ConstraintDisposition,
    ConstraintEngine,
    ConstraintEvaluation,
)
from .reconciliation import (
    DriftCategory,
    ReconciliationDisposition,
    ReconciliationEngine,
    ReconciliationEvaluation,
    ReconciliationExpectation,
    ReconciliationRecord,
    VerificationObservation,
    VerificationPolicy,
)

from .runtime_memory import (
    MemorySample,
    MemorySummary,
    RuntimeMemory,
)
from .runtime_context import RuntimeContext
from .event_bus import RuntimeEventPublisher, RuntimeEventTopic
from .runtime import RuntimeExplanation

from .domain import (
    ConfidenceBand,
    Evidence,
    FreshnessPolicy,
    Feature,
    HydraulicRoute,
    Installation,
    Observation,
    ObservationFreshness,
    ObservationQuality,
    ObservationStore,
    PoolObservation,
    PoolSystem,
    Resource,
    ResourceType,
    TruthLevel,
)
from .equipment import FilterEquipment

from .environment import (
    DeliverySafetyPolicy,
    ObservationPolicy,
    ObservationSourceKind,
    PoolRuntimeEnvironment,
    RuntimeEnvironmentBuilder,
    RuntimeEnvironmentError,
    RuntimeMode,
    build_runtime_environment,
)

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

from .execution_proposals import (
    ExecutionProposalGenerator,
    ExecutionProposalRequest,
    ProposalGenerationDisposition,
    ProposalGenerationResult,
)

from .execution_authorization import (
    ExecutionAuthorizationEngine,
    ExecutionAuthorizationRequest,
)

from .execution_plans import (
    DeterministicExecutionPlanBuilder,
    ExecutionPlanBuildRequest,
    ExecutionPlanBuildResult,
    ExecutionStepSpecification,
    PlanBuildDisposition,
)

from .execution_state_machine import (
    ExecutionLifecycle,
    ExecutionStateMachine,
    ExecutionStateTransition,
    ExecutionTransitionResult,
    TransitionDisposition,
)

from .execution_coordinator import (
    CoordinationDisposition,
    CoordinationEventKind,
    ExecutionCoordinationEvent,
    ExecutionCoordinationResult,
    ExecutionCoordinationSession,
    ExecutionCoordinator,
)

from .execution_verification import (
    ExecutionVerificationEngine,
    ExecutionVerificationEvidence,
    ExecutionVerificationRequest,
    ExecutionVerificationResult,
    VerificationEvidenceDisposition,
)

from .execution_flight_recorder import (
    ExecutionArtifact,
    ExecutionFlightRecord,
    ExecutionRecorder,
    ExecutionRecordType,
    ExecutionTimeline,
    InMemoryExecutionFlightRecorder,
)

from .execution_restart_recovery import (
    ExecutionRecoveryAssessment,
    ExecutionRecoveryClassification,
    ExecutionRecoveryDisposition,
    ExecutionRecoveryRecommendation,
    ExecutionRecoveryRequest,
    ExecutionRestartRecoveryEngine,
)

from .execution_golden_scenarios import (
    EXECUTION_GOLDEN_SCENARIO_INDEX,
    EXECUTION_GOLDEN_SCENARIOS,
    ExecutionGoldenScenarioDefinition,
    ExecutionGoldenScenarioId,
    validate_execution_golden_catalog,
)

from .simulator_execution_gateway import (
    SimulatorExecutionGateway,
    SimulatorExecutionGatewayError,
    SimulatorGatewayRoute,
)

from .execution_simulator_delivery import (
    SimulatorExecutionReceipt,
    SimulatorStepDeliveryDisposition,
    SimulatorStepDeliveryEngine,
    SimulatorStepDeliveryRequest,
    SimulatorStepDeliveryResult,
)

from .execution_step_state_machine import (
    ExecutionStepLifecycle,
    ExecutionStepStateMachine,
    ExecutionStepStatus,
    ExecutionStepTransition,
    ExecutionStepTransitionResult,
)

from .closed_loop_simulator_execution import (
    ClosedLoopExecutionDisposition,
    ClosedLoopExecutionResult,
    ClosedLoopSimulatorExecutionEngine,
    ClosedLoopStepResult,
    SimulatedEquipmentState,
)

from .post_delivery_observation_verification import (
    PostDeliveryObservationVerifier,
    PostDeliveryVerificationDisposition,
    PostDeliveryVerificationRequest,
    PostDeliveryVerificationResult,
)

from .execution_reconciliation_planning import (
    ExecutionReconciliationDisposition,
    ExecutionReconciliationPlanner,
    ExecutionReconciliationRequest,
    ExecutionReconciliationResult,
)

from .recovery_coordinator import (
    RecoveryCoordinationRequest,
    RecoveryCoordinator,
    RecoveryDirective,
    RecoveryDirectiveDisposition,
    RecoveryPolicy,
)

from .operational_intent import (
    IntentCriterion,
    OperationalIntent,
    OperationalIntentLifecycle,
    OperationalIntentPriority,
    OperationalIntentSafetyClass,
    OperationalIntentSource,
    OperationalIntentType,
    canonical_intent_order,
)

from .intent_arbitration import (
    DEFAULT_INTENT_ARBITRATION_POLICY,
    IntentArbitrationDecision,
    IntentArbitrationPolicy,
    IntentArbitrationResult,
    IntentDisposition,
    OperationalIntentArbitrator,
)

from .pump_optimization import (
    PumpCandidateEvaluation,
    PumpOperationOptimizer,
    PumpOptimizationDisposition,
    PumpOptimizationPolicy,
    PumpOptimizationResult,
)

from .operator_recommendation import (
    OperatorRecommendation,
    OperatorRecommendationBuilder,
    OperatorRecommendationStatus,
)

from .operational_intelligence import (
    OperationalIntelligencePipeline,
    OperationalIntelligenceResult,
)
