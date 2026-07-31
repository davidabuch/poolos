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
from poolos.golden_scenarios import (
    GoldenScenario,
    GoldenScenarioStatus,
    GoldenScenarioSuite,
)
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import ObjectiveType, PlanObjective
from poolos.planning_strategies import build_default_planner
from poolos.restart_recovery import (
    DecisionReplayEngine,
    DecisionReplayStep,
)

NOW = datetime(2026, 7, 31, 19, 0, tzinfo=timezone.utc)


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-golden",
    )


def context(
    context_id: str,
    *,
    trigger: EvaluationTrigger = EvaluationTrigger.MANUAL,
    mode: EvaluationRuntimeMode = EvaluationRuntimeMode.SHADOW,
    previous_decision_id: str | None = None,
    blockers: tuple[str, ...] = (),
) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        context_id=context_id,
        evaluated_at=NOW,
        trigger=trigger,
        runtime_mode=mode,
        goals=(objective(),),
        observation={"spa_temperature": 90.0},
        previous_decision_id=previous_decision_id,
        blockers=blockers,
    )


def planning(alternative_id: str = "heater") -> DecisionPlanningRequest:
    return DecisionPlanningRequest(
        objective=objective(),
        candidates=(
            AlternativeCandidate(
                alternative_id,
                alternative_id.title(),
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


def system() -> tuple[DecisionOrchestrator, InMemoryDecisionFlightRecorder]:
    recorder = InMemoryDecisionFlightRecorder()
    return (
        DecisionOrchestrator(
            ExplainablePlanner(
                planner=build_default_planner(),
                ranking_engine=AlternativeRankingEngine(
                    (RankingCriterion("readiness", "Readiness", 1.0),)
                ),
                recorder=recorder,
            )
        ),
        recorder,
    )


def test_golden_suite_runs_in_stable_id_order_and_reports_failures():
    order: list[str] = []

    def pass_b() -> None:
        order.append("b")

    def fail_a() -> None:
        order.append("a")
        raise AssertionError("expected failure")

    report = GoldenScenarioSuite(
        (
            GoldenScenario("b", "passes", pass_b),
            GoldenScenario("a", "fails", fail_a),
        )
    ).run()

    assert order == ["a", "b"]
    assert report.passed is False
    assert report.passed_count == 1
    assert report.failed_count == 1
    assert report.results[0].status is GoldenScenarioStatus.FAILED


def test_golden_normal_evaluation_and_equivalent_reevaluation():
    orchestrator, recorder = system()

    def scenario() -> None:
        first = orchestrator.evaluate(
            DecisionOrchestrationRequest(context("first"), planning()),
            kernel(),
        )
        assert first.active_record is not None
        second = orchestrator.evaluate(
            DecisionOrchestrationRequest(
                context(
                    "second",
                    trigger=EvaluationTrigger.SCHEDULED,
                    previous_decision_id=first.active_record.decision.decision_id,
                ),
                planning(),
                active_record=first.active_record,
            ),
            kernel(),
        )
        assert second.status is OrchestrationStatus.RETAINED
        assert len(recorder.records) == 1

    report = GoldenScenarioSuite(
        (GoldenScenario("equivalent", "Equivalent decisions are retained", scenario),)
    ).run()
    assert report.passed is True


def test_golden_blocked_context_and_supersession():
    orchestrator, recorder = system()

    def blocked() -> None:
        result = orchestrator.evaluate(
            DecisionOrchestrationRequest(
                context("blocked", blockers=("missing observation",)),
                planning(),
            ),
            kernel(),
        )
        assert result.status is OrchestrationStatus.BLOCKED_CONTEXT
        assert not recorder.records

    def superseded() -> None:
        first = orchestrator.evaluate(
            DecisionOrchestrationRequest(context("first"), planning()),
            kernel(),
        )
        assert first.active_record is not None
        second = orchestrator.evaluate(
            DecisionOrchestrationRequest(
                context(
                    "second",
                    trigger=EvaluationTrigger.GOAL_CHANGED,
                    previous_decision_id=first.active_record.decision.decision_id,
                ),
                planning("solar"),
                active_record=first.active_record,
            ),
            kernel(),
        )
        assert second.status is OrchestrationStatus.COMPLETED
        assert len(recorder.records) == 2

    report = GoldenScenarioSuite(
        (
            GoldenScenario("blocked", "Blocked context does not plan", blocked),
            GoldenScenario("superseded", "Material change supersedes", superseded),
        )
    ).run()
    assert report.passed is True


def test_golden_replay_and_namespace_isolation():
    orchestrator, _ = system()

    def replay() -> None:
        result = DecisionReplayEngine(orchestrator).replay(
            (
                DecisionReplayStep(context("one"), planning()),
                DecisionReplayStep(
                    context(
                        "two",
                        trigger=EvaluationTrigger.SCHEDULED,
                        previous_decision_id="placeholder",
                    ),
                    planning(),
                ),
            ),
            (kernel(), kernel()),
        )
        assert result.verified is True
        assert result.results[1].status is OrchestrationStatus.RETAINED

    def namespace() -> None:
        from poolos.homeassistant.orchestration_diagnostics import (
            HomeAssistantRuntimeDiagnosticEntityIds,
        )

        from dataclasses import fields

        ids = HomeAssistantRuntimeDiagnosticEntityIds()
        values = tuple(getattr(ids, item.name) for item in fields(ids))
        assert all("poolos_sim_" not in value for value in values)

    report = GoldenScenarioSuite(
        (
            GoldenScenario("namespace", "Live diagnostics avoid sim namespace", namespace),
            GoldenScenario("replay", "Replay retains equivalent decision", replay),
        )
    ).run()
    assert report.passed is True
