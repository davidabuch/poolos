from datetime import datetime, timedelta, timezone

import pytest

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
    OrchestrationStatus,
)
from poolos.decision_planning import DecisionPlanningRequest, ExplainablePlanner
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.evaluation_context import (
    DecisionEvaluationContext,
    EvaluationRuntimeMode,
    EvaluationTrigger,
)
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import ObjectiveType, PlanObjective
from poolos.planning_strategies import build_default_planner

NOW = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-10-12",
    )


def context(*, blockers: tuple[str, ...] = ()) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        context_id="context-1",
        evaluated_at=NOW,
        trigger=EvaluationTrigger.OBSERVATION_CHANGED,
        runtime_mode=EvaluationRuntimeMode.SHADOW,
        goals=(objective(),),
        observation={"spa_temperature": 90.0},
        forecast={"energy_price": 0.22},
        active_policy_ids=("energy_aware",),
        freshness={"spa_temperature": "fresh"},
        previous_decision_id="decision-previous",
        blockers=blockers,
        metadata={"source": "test"},
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


def planning() -> DecisionPlanningRequest:
    return DecisionPlanningRequest(
        objective=objective(),
        candidates=(
            AlternativeCandidate(
                "heater",
                "Heater only",
                {"readiness": 1.0},
                reasons=("Meets the deadline.",),
            ),
        ),
    )


def orchestrator(*, recorder=True) -> DecisionOrchestrator:
    flight_recorder = InMemoryDecisionFlightRecorder() if recorder else None
    return DecisionOrchestrator(
        ExplainablePlanner(
            planner=build_default_planner(),
            ranking_engine=AlternativeRankingEngine(
                (RankingCriterion("readiness", "Readiness", 1.0),)
            ),
            recorder=flight_recorder,
        )
    )


def test_context_freezes_mappings_and_exposes_goal():
    value = context()

    assert value.goal("goal-10-12").body_id == "spa"
    assert value.planning_allowed is True
    with pytest.raises(TypeError):
        value.observation["spa_temperature"] = 95.0  # type: ignore[index]


def test_context_rejects_duplicate_goal_ids():
    duplicated = objective()
    with pytest.raises(ValueError, match="goal objective IDs must be unique"):
        DecisionEvaluationContext(
            context_id="duplicate",
            evaluated_at=NOW,
            trigger=EvaluationTrigger.MANUAL,
            runtime_mode=EvaluationRuntimeMode.SIMULATION,
            goals=(duplicated, duplicated),
        )


def test_request_requires_exact_context_objective():
    different = PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=99.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-10-12",
    )
    with pytest.raises(ValueError, match="must match"):
        DecisionOrchestrationRequest(
            context(),
            DecisionPlanningRequest(different, planning().candidates),
        )


def test_orchestrator_completes_records_and_projects_without_execution():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )

    assert result.status is OrchestrationStatus.COMPLETED
    assert result.decision is not None
    assert result.decision.flight_record is not None
    assert result.home_assistant is not None
    assert len(result.home_assistant.publications) == 6
    assert result.decision.plan.steps


def test_orchestrator_adds_context_traceability_metadata():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )

    assert result.decision is not None
    metadata = result.decision.explanation.metadata
    assert metadata["evaluation_context_id"] == "context-1"
    assert metadata["evaluation_trigger"] == "observation_changed"
    assert metadata["runtime_mode"] == "shadow"
    assert metadata["previous_decision_id"] == "decision-previous"


def test_context_blocker_prevents_planner_and_recorder_invocation():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(blockers=("telemetry stale",)), planning()),
        kernel(),
    )

    assert result.status is OrchestrationStatus.BLOCKED_CONTEXT
    assert result.decision is None
    assert result.home_assistant is None
    assert result.blockers == ("telemetry stale",)


def test_orchestrator_without_recorder_returns_decision_without_projection():
    result = orchestrator(recorder=False).evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )

    assert result.status is OrchestrationStatus.COMPLETED
    assert result.decision is not None
    assert result.decision.flight_record is None
    assert result.home_assistant is None


def test_orchestration_diagnostics_are_immutable():
    result = orchestrator().evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )

    assert result.diagnostics["goal_count"] == "1"
    with pytest.raises(TypeError):
        result.diagnostics["goal_count"] = "2"  # type: ignore[index]
