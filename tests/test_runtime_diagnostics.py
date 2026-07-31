from datetime import datetime, timedelta, timezone

from poolos.alternative_ranking import (
    AlternativeCandidate,
    AlternativeRankingEngine,
    RankingCriterion,
)
from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.decision_flight_recorder import InMemoryDecisionFlightRecorder
from poolos.decision_orchestrator import (
    DecisionOrchestrationRequest,
    DecisionOrchestrator,
)
from poolos.decision_planning import DecisionPlanningRequest, ExplainablePlanner
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.evaluation_context import (
    DecisionEvaluationContext,
    EvaluationRuntimeMode,
    EvaluationTrigger,
)
from poolos.homeassistant.decision_intelligence import (
    HomeAssistantDecisionPublicationResult,
)
from poolos.homeassistant.orchestration_diagnostics import (
    HomeAssistantRuntimeDiagnosticProjector,
    HomeAssistantRuntimeDiagnosticPublisher,
)
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import ObjectiveType, PlanObjective
from poolos.planning_strategies import build_default_planner
from poolos.runtime_diagnostics import (
    SupervisoryRuntimeHealth,
    SupervisoryRuntimeMonitor,
)

NOW = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-runtime-diagnostics",
    )


def context(*, blockers: tuple[str, ...] = ()) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        context_id="runtime-context",
        evaluated_at=NOW,
        trigger=EvaluationTrigger.OBSERVATION_CHANGED,
        runtime_mode=EvaluationRuntimeMode.SHADOW,
        goals=(objective(),),
        observation={"spa_temperature": 90.0},
        blockers=blockers,
    )


def planning() -> DecisionPlanningRequest:
    return DecisionPlanningRequest(
        objective=objective(),
        candidates=(
            AlternativeCandidate(
                "heater",
                "Heater only",
                {"readiness": 1.0},
            ),
        ),
    )


def kernel() -> PoolKernel:
    value = PoolKernel(clock=FixedClock(NOW))
    value.bodies.register(Body("spa", "Spa", BodyType.SPA))
    value.equipment.register(
        Equipment(
            "pump",
            "Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            body=BodyType.SPA,
        )
    )
    value.equipment.register(
        Equipment(
            "heater",
            "Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            body=BodyType.SPA,
        )
    )
    value.update_body_state(
        "spa",
        BodyState(BodyType.SPA, TemperatureState(90.0, 100.0, False), False, False),
    )
    return value


def orchestrator() -> DecisionOrchestrator:
    return DecisionOrchestrator(
        ExplainablePlanner(
            planner=build_default_planner(),
            ranking_engine=AlternativeRankingEngine(
                (RankingCriterion("readiness", "Readiness", 1.0),)
            ),
            recorder=InMemoryDecisionFlightRecorder(),
        )
    )


def test_runtime_monitor_reports_healthy_completed_evaluation():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )
    monitor = SupervisoryRuntimeMonitor()
    snapshot = monitor.observe(
        result,
        evaluated_at=NOW,
        next_reevaluation=NOW + timedelta(minutes=15),
    )

    assert snapshot.health is SupervisoryRuntimeHealth.HEALTHY
    assert snapshot.evaluation_count == 1
    assert snapshot.context_valid is True
    assert snapshot.decision_changed is True
    assert snapshot.active_decision_id is not None
    assert monitor.latest is snapshot


def test_runtime_monitor_reports_blocked_context():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(blockers=("telemetry stale",)), planning()),
        kernel(),
    )
    snapshot = SupervisoryRuntimeMonitor().observe(result, evaluated_at=NOW)

    assert snapshot.health is SupervisoryRuntimeHealth.BLOCKED
    assert snapshot.context_valid is False
    assert snapshot.blockers == ("telemetry stale",)
    assert snapshot.active_decision_id is None


def test_runtime_monitor_increments_evaluation_count():
    runtime = orchestrator()
    result = runtime.evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )
    monitor = SupervisoryRuntimeMonitor()
    first = monitor.observe(result, evaluated_at=NOW)
    second = monitor.observe(result, evaluated_at=NOW + timedelta(minutes=1))

    assert first.evaluation_count == 1
    assert second.evaluation_count == 2


def test_homeassistant_runtime_projection_has_stable_entities():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )
    snapshot = SupervisoryRuntimeMonitor().observe(result, evaluated_at=NOW)
    projection = HomeAssistantRuntimeDiagnosticProjector().project(snapshot)

    states = {item.entity_id: item.state for item in projection.publications}
    assert states["sensor.poolos_runtime_health"] == "healthy"
    assert states["sensor.poolos_runtime_evaluation_count"] == "1"
    assert states["binary_sensor.poolos_runtime_context_valid"] == "on"
    assert states["binary_sensor.poolos_runtime_decision_changed"] == "on"
    assert len(states) == 8


class Executor:
    def __init__(self) -> None:
        self.calls = []

    def publish_state(self, publication, *, timeout=None):
        self.calls.append(publication)
        return HomeAssistantDecisionPublicationResult(True, publication.entity_id)


def test_runtime_publisher_deduplicates_accepted_states():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )
    snapshot = SupervisoryRuntimeMonitor().observe(result, evaluated_at=NOW)
    executor = Executor()
    publisher = HomeAssistantRuntimeDiagnosticPublisher(executor)

    assert len(publisher.publish(snapshot)) == 8
    assert publisher.publish(snapshot) == ()
    assert len(executor.calls) == 8
