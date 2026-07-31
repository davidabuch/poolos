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
from poolos.decision_orchestrator import DecisionOrchestrationRequest, DecisionOrchestrator
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
from poolos.restart_recovery import (
    DecisionReplayEngine,
    DecisionReplayExpectation,
    DecisionReplayStep,
    RestartRecoveryEngine,
    RestartRecoveryRequest,
    RestartRecoveryStatus,
)

NOW = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-recovery",
    )


def context(
    context_id: str,
    *,
    trigger: EvaluationTrigger,
    previous_decision_id: str | None = None,
    blockers: tuple[str, ...] = (),
) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        context_id=context_id,
        evaluated_at=NOW,
        trigger=trigger,
        runtime_mode=EvaluationRuntimeMode.SHADOW,
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
    orchestrator = DecisionOrchestrator(
        ExplainablePlanner(
            planner=build_default_planner(),
            ranking_engine=AlternativeRankingEngine(
                (RankingCriterion("readiness", "Readiness", 1.0),)
            ),
            recorder=recorder,
        )
    )
    return orchestrator, recorder


def seed(orchestrator: DecisionOrchestrator):
    return orchestrator.evaluate(
        DecisionOrchestrationRequest(
            context("initial", trigger=EvaluationTrigger.MANUAL),
            planning(),
        ),
        kernel(),
    )


def test_restart_request_requires_restart_trigger():
    with pytest.raises(ValueError, match="restart_recovery"):
        RestartRecoveryRequest(
            context("wrong", trigger=EvaluationTrigger.MANUAL),
            planning(),
        )


def test_restart_without_history_initializes_from_current_facts():
    orchestrator, recorder = system()
    result = RestartRecoveryEngine(orchestrator, recorder).recover(
        RestartRecoveryRequest(
            context("restart", trigger=EvaluationTrigger.RESTART_RECOVERY),
            planning(),
        ),
        kernel(),
    )

    assert result.status is RestartRecoveryStatus.INITIALIZED
    assert result.previous_record is None
    assert result.active_record is recorder.latest
    assert len(recorder.records) == 1


def test_restart_with_unchanged_facts_retains_latest_record():
    orchestrator, recorder = system()
    first = seed(orchestrator)
    assert first.active_record is not None
    result = RestartRecoveryEngine(orchestrator, recorder).recover(
        RestartRecoveryRequest(
            context(
                "restart",
                trigger=EvaluationTrigger.RESTART_RECOVERY,
                previous_decision_id=first.active_record.decision.decision_id,
            ),
            planning(),
        ),
        kernel(),
    )

    assert result.status is RestartRecoveryStatus.RETAINED
    assert result.active_record is first.active_record
    assert len(recorder.records) == 1


def test_restart_with_changed_facts_supersedes_latest_record():
    orchestrator, recorder = system()
    first = seed(orchestrator)
    assert first.active_record is not None
    result = RestartRecoveryEngine(orchestrator, recorder).recover(
        RestartRecoveryRequest(
            context(
                "restart",
                trigger=EvaluationTrigger.RESTART_RECOVERY,
                previous_decision_id=first.active_record.decision.decision_id,
            ),
            planning("solar"),
        ),
        kernel(),
    )

    assert result.status is RestartRecoveryStatus.SUPERSEDED
    assert result.active_record is recorder.latest
    assert result.active_record is not first.active_record
    assert len(recorder.records) == 2


def test_restart_blocker_does_not_restore_or_append_decision():
    orchestrator, recorder = system()
    first = seed(orchestrator)
    assert first.active_record is not None
    result = RestartRecoveryEngine(orchestrator, recorder).recover(
        RestartRecoveryRequest(
            context(
                "restart",
                trigger=EvaluationTrigger.RESTART_RECOVERY,
                previous_decision_id=first.active_record.decision.decision_id,
                blockers=("telemetry stale",),
            ),
            planning(),
        ),
        kernel(),
    )

    assert result.status is RestartRecoveryStatus.BLOCKED
    assert result.active_record is None
    assert len(recorder.records) == 1


def test_restart_rejects_stale_history_reference():
    orchestrator, recorder = system()
    seed(orchestrator)
    with pytest.raises(ValueError, match="latest recorded decision"):
        RestartRecoveryEngine(orchestrator, recorder).recover(
            RestartRecoveryRequest(
                context(
                    "restart",
                    trigger=EvaluationTrigger.RESTART_RECOVERY,
                    previous_decision_id="stale-decision",
                ),
                planning(),
            ),
            kernel(),
        )


def test_replay_reproduces_expected_decision_signatures():
    orchestrator, _ = system()
    first_context = context("one", trigger=EvaluationTrigger.MANUAL)
    first = orchestrator.evaluate(
        DecisionOrchestrationRequest(first_context, planning()),
        kernel(),
    )
    assert first.active_record is not None
    second_context = context(
        "two",
        trigger=EvaluationTrigger.SCHEDULED,
        previous_decision_id=first.active_record.decision.decision_id,
    )
    expected_first = DecisionReplayExpectation.from_result(first)

    replay_orchestrator, _ = system()
    result = DecisionReplayEngine(replay_orchestrator).replay(
        (
            DecisionReplayStep(first_context, planning(), expected_first),
            DecisionReplayStep(
                second_context,
                planning(),
                DecisionReplayExpectation(
                    outcome="selected",
                    selected_alternative_id="heater",
                    stability_disposition="retain_equivalent",
                    orchestration_status="retained",
                ),
            ),
        ),
        (kernel(), kernel()),
    )

    assert result.verified is True
    assert len(result.results) == 2
    assert result.results[1].active_record is result.results[0].active_record


def test_replay_reports_signature_mismatch_without_actuation():
    orchestrator, _ = system()
    result = DecisionReplayEngine(orchestrator).replay(
        (
            DecisionReplayStep(
                context("one", trigger=EvaluationTrigger.MANUAL),
                planning(),
                DecisionReplayExpectation(
                    outcome="blocked",
                    selected_alternative_id=None,
                    stability_disposition="initial",
                    orchestration_status="completed",
                ),
            ),
        ),
        (kernel(),),
    )

    assert result.verified is False
    assert result.results[0].decision is not None


def test_replay_requires_matching_step_and_kernel_counts():
    orchestrator, _ = system()
    with pytest.raises(ValueError, match="equal length"):
        DecisionReplayEngine(orchestrator).replay((), (kernel(),))
