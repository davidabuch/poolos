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
from poolos.decision_intelligence import (
    CheckStatus,
    DecisionCheck,
    DecisionEvidence,
    DecisionOutcome,
    EvidenceKind,
)
from poolos.decision_planning import DecisionPlanningRequest, ExplainablePlanner
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import ObjectiveType, PlanObjective
from poolos.planning_strategies import build_default_planner

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


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
        BodyState(
            BodyType.SPA,
            TemperatureState(90.0, 100.0, False),
            False,
            False,
        ),
    )
    return value


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-1",
    )


def explainable(recorder=None) -> ExplainablePlanner:
    return ExplainablePlanner(
        planner=build_default_planner(),
        ranking_engine=AlternativeRankingEngine(
            (
                RankingCriterion("readiness", "Readiness", 2.0),
                RankingCriterion("cost", "Cost", 1.0),
            )
        ),
        recorder=recorder,
    )


def candidates() -> tuple[AlternativeCandidate, ...]:
    return (
        AlternativeCandidate(
            "heater",
            "Heater only",
            {"readiness": 1.0, "cost": 0.4},
            reasons=("Meets the requested deadline.",),
        ),
        AlternativeCandidate(
            "delay",
            "Delay heating",
            {"readiness": 0.5, "cost": 1.0},
            reasons=("Costs less but reduces schedule margin.",),
        ),
    )


def test_explainable_planner_creates_plan_and_selected_decision():
    result = explainable().create_plan(
        DecisionPlanningRequest(objective(), candidates()),
        kernel(),
    )

    assert result.plan.objective_id == "goal-1"
    assert result.explanation.outcome is DecisionOutcome.SELECTED
    assert result.explanation.selected_alternative_id == "heater"
    assert result.explanation.decision_id == result.plan.plan_id
    assert result.explanation.metadata["plan_id"] == result.plan.plan_id
    assert "Selected Heater only" in result.human.text
    assert "[alternatives]" in result.technical.text


def test_blocking_check_prevents_selected_outcome_but_preserves_ranking():
    check = DecisionCheck(
        "ownership",
        "Control ownership",
        CheckStatus.FAILED,
        "Manual control currently owns the heater.",
        blocking=True,
    )
    result = explainable().create_plan(
        DecisionPlanningRequest(objective(), candidates(), checks=(check,)),
        kernel(),
    )

    assert result.ranking.selected_alternative_id == "heater"
    assert result.explanation.outcome is DecisionOutcome.BLOCKED
    assert result.explanation.selected_alternative_id is None
    assert result.explanation.blocking_checks == (check,)


def test_no_candidates_produces_no_action_decision():
    result = explainable().create_plan(
        DecisionPlanningRequest(objective(), ()),
        kernel(),
    )

    assert result.explanation.outcome is DecisionOutcome.NO_ACTION
    assert result.explanation.alternatives == ()
    assert result.explanation.confidence == 0.0


def test_only_infeasible_candidates_produce_deferred_decision():
    candidate = AlternativeCandidate(
        "solar",
        "Solar only",
        {"readiness": 0.9, "cost": 1.0},
        feasible=False,
        reasons=("Forecast solar gain is insufficient.",),
    )
    result = explainable().create_plan(
        DecisionPlanningRequest(objective(), (candidate,)),
        kernel(),
    )

    assert result.explanation.outcome is DecisionOutcome.DEFERRED
    assert result.explanation.selected_alternative_id is None


def test_request_evidence_metadata_and_confidence_are_preserved():
    evidence = DecisionEvidence(
        "spa_temperature",
        "90.0",
        EvidenceKind.OBSERVATION,
        "poolos.state",
        observed_at=NOW,
    )
    result = explainable().create_plan(
        DecisionPlanningRequest(
            objective(),
            candidates(),
            evidence=(evidence,),
            summary="Custom planning summary",
            next_change="The ownership lease expires",
            confidence=0.91,
            metadata={"source": "simulation"},
        ),
        kernel(),
    )

    assert result.explanation.evidence == (evidence,)
    assert result.explanation.summary == "Custom planning summary"
    assert result.explanation.confidence == 0.91
    assert result.explanation.metadata["source"] == "simulation"


def test_recorder_is_invoked_automatically():
    recorder = InMemoryDecisionFlightRecorder()
    result = explainable(recorder).create_plan(
        DecisionPlanningRequest(objective(), candidates()),
        kernel(),
    )

    assert result.flight_record is recorder.latest
    assert result.flight_record is not None
    assert result.flight_record.plan_id == result.plan.plan_id
    assert result.flight_record.sequence == 1
