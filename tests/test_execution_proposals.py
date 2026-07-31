from dataclasses import replace
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
)
from poolos.decision_planning import DecisionPlanningRequest, ExplainablePlanner
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.evaluation_context import (
    DecisionEvaluationContext,
    EvaluationRuntimeMode,
    EvaluationTrigger,
)
from poolos.execution_proposals import (
    ExecutionProposalGenerator,
    ExecutionProposalRequest,
    ProposalGenerationDisposition,
)
from poolos.integration import StartPump
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.planning import ObjectiveType, PlanObjective
from poolos.planning_strategies import build_default_planner

NOW = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)


def objective() -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=3),
        objective_id="goal-10-13b",
    )


def context(
    *,
    context_id: str = "context-10-13b",
    blockers: tuple[str, ...] = (),
    previous_decision_id: str | None = None,
) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        context_id=context_id,
        evaluated_at=NOW,
        trigger=EvaluationTrigger.OBSERVATION_CHANGED,
        runtime_mode=EvaluationRuntimeMode.SIMULATION,
        goals=(objective(),),
        observation={"spa_temperature": 90.0},
        blockers=blockers,
        previous_decision_id=previous_decision_id,
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


def planning(*, actionable: bool = True) -> DecisionPlanningRequest:
    candidates = (
        AlternativeCandidate(
            "heater",
            "Heater only",
            {"readiness": 1.0},
            reasons=("Meets the deadline.",),
        ),
    ) if actionable else ()
    return DecisionPlanningRequest(objective=objective(), candidates=candidates)


def orchestrator(*, recorder: bool = True) -> DecisionOrchestrator:
    return DecisionOrchestrator(
        ExplainablePlanner(
            planner=build_default_planner(),
            ranking_engine=AlternativeRankingEngine(
                (RankingCriterion("readiness", "Readiness", 1.0),)
            ),
            recorder=InMemoryDecisionFlightRecorder() if recorder else None,
        )
    )


def operation() -> StartPump:
    return StartPump(equipment_id="pump", operation_id="operation-start-pump")


def completed_result(*, recorder: bool = True, actionable: bool = True):
    return orchestrator(recorder=recorder).evaluate(
        DecisionOrchestrationRequest(context(), planning(actionable=actionable)),
        kernel(),
    )


def test_generates_proposal_for_current_recorded_changed_selection() -> None:
    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=completed_result(),
            operations=(operation(),),
            expected_final_state={"pump.running": True},
            metadata={
                "source": "test",
                "selected_alternative_id": "spoofed",
            },
        )
    )

    assert result.generated
    assert result.disposition is ProposalGenerationDisposition.GENERATED
    assert result.proposal is not None
    assert result.proposal.proposal_id.startswith("execution-proposal:")
    assert result.proposal.objective_id == "goal-10-13b"
    assert result.proposal.operations == (operation(),)
    assert result.proposal.expected_final_state["pump.running"] is True
    assert result.proposal.metadata["selected_alternative_id"] == "heater"
    assert result.proposal.metadata["source"] == "test"


def test_generation_is_deterministic_for_same_accepted_decision() -> None:
    orchestration = completed_result()
    request = ExecutionProposalRequest(
        orchestration=orchestration,
        operations=(operation(),),
    )
    generator = ExecutionProposalGenerator()

    first = generator.generate(request)
    second = generator.generate(request)

    assert first.proposal == second.proposal
    assert first.proposal is not None
    assert first.proposal.proposal_id == (
        f"execution-proposal:{orchestration.decision.explanation.decision_id}"
    )


def test_blocked_context_does_not_generate_proposal() -> None:
    orchestration = orchestrator().evaluate(
        DecisionOrchestrationRequest(
            context(blockers=("telemetry stale",)),
            planning(),
        ),
        kernel(),
    )

    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(orchestration=orchestration)
    )

    assert not result.generated
    assert result.disposition is ProposalGenerationDisposition.BLOCKED_CONTEXT
    assert result.proposal is None


def test_retained_decision_does_not_generate_duplicate_proposal() -> None:
    recorder = InMemoryDecisionFlightRecorder()
    value = DecisionOrchestrator(
        ExplainablePlanner(
            planner=build_default_planner(),
            ranking_engine=AlternativeRankingEngine(
                (RankingCriterion("readiness", "Readiness", 1.0),)
            ),
            recorder=recorder,
        )
    )
    first = value.evaluate(
        DecisionOrchestrationRequest(context(), planning()),
        kernel(),
    )
    assert first.active_record is not None
    retained_context = context(
        context_id="context-retained",
        previous_decision_id=first.active_record.decision.decision_id,
    )
    retained = value.evaluate(
        DecisionOrchestrationRequest(
            retained_context,
            planning(),
            active_record=first.active_record,
        ),
        kernel(),
    )

    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=retained,
            operations=(operation(),),
        )
    )

    assert result.disposition is ProposalGenerationDisposition.RETAINED_DECISION
    assert result.proposal is None
    assert len(recorder.records) == 1


def test_non_selected_decision_is_not_actionable() -> None:
    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=completed_result(actionable=False),
            operations=(operation(),),
        )
    )

    assert result.disposition is ProposalGenerationDisposition.NOT_ACTIONABLE
    assert result.proposal is None


def test_unrecorded_decision_does_not_generate_proposal() -> None:
    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=completed_result(recorder=False),
            operations=(operation(),),
        )
    )

    assert result.disposition is ProposalGenerationDisposition.UNRECORDED_DECISION
    assert result.proposal is None


def test_stale_decision_does_not_generate_proposal() -> None:
    orchestration = completed_result()
    assert orchestration.active_record is not None
    stale_decision = replace(
        orchestration.active_record.decision,
        decision_id="superseded-decision",
    )
    stale_record = replace(orchestration.active_record, decision=stale_decision)
    stale_orchestration = replace(orchestration, active_record=stale_record)

    result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=stale_orchestration,
            operations=(operation(),),
        )
    )

    assert result.disposition is ProposalGenerationDisposition.STALE_DECISION
    assert result.proposal is None


def test_actionable_decision_requires_operations() -> None:
    with pytest.raises(ValueError, match="at least one PoolOperation"):
        ExecutionProposalGenerator().generate(
            ExecutionProposalRequest(orchestration=completed_result())
        )


def test_request_rejects_noncanonical_operations() -> None:
    with pytest.raises(TypeError, match="PoolOperation"):
        ExecutionProposalRequest(
            orchestration=completed_result(),
            operations=("switch.turn_on",),  # type: ignore[arg-type]
        )


def test_request_and_generated_proposal_freeze_mappings() -> None:
    request = ExecutionProposalRequest(
        orchestration=completed_result(),
        operations=(operation(),),
        expected_final_state={"pump.running": True},
        metadata={"source": "test"},
    )
    generated = ExecutionProposalGenerator().generate(request)
    assert generated.proposal is not None

    with pytest.raises(TypeError):
        request.metadata["source"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        generated.proposal.expected_final_state[  # type: ignore[index]
            "pump.running"
        ] = False
