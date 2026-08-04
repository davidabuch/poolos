from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.alternative_ranking import AlternativeCandidate
from poolos.decision_planning import DecisionPlanningRequest
from poolos.evaluation_context import EvaluationRuntimeMode, EvaluationTrigger
from poolos.evaluation_triggers import EvaluationTriggerRequest, TriggerUrgency
from poolos.planning import ObjectiveType, PlanObjective
from poolos.reevaluation_runtime_submission import ReevaluationRuntimeSubmissionOutcome
from poolos.runtime_trigger_coalescing import RuntimeTriggerCoalescingBoundary
from poolos.supervisory_evaluation_assembly import (
    SupervisoryEvaluationAssemblyRequest,
    SupervisoryEvaluationInputAssembler,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 4, 18, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Request:
    submission_id: str
    trigger_request: EvaluationTriggerRequest


@dataclass(frozen=True)
class _Submission:
    result_id: str
    outcome: ReevaluationRuntimeSubmissionOutcome
    request: _Request
    submitted_at: datetime
    accepted_submission_ids: tuple[str, ...]


def _submission(submission_id: str = "submission-a") -> _Submission:
    return _Submission(
        result_id=f"result-{submission_id}",
        outcome=ReevaluationRuntimeSubmissionOutcome.ACCEPTED,
        request=_Request(
            submission_id=submission_id,
            trigger_request=EvaluationTriggerRequest(
                trigger=EvaluationTrigger.EXPECTED_CHANGE_REACHED,
                requested_at=NOW - timedelta(minutes=10),
                urgency=TriggerUrgency.NORMAL,
                source="poolos.due_reevaluation_trigger_boundary",
                reason="Scheduled expected change reached: spa readiness",
            ),
        ),
        submitted_at=NOW - timedelta(minutes=5),
        accepted_submission_ids=(submission_id,),
    )


def _batch():
    return RuntimeTriggerCoalescingBoundary().coalesce(
        (_submission(),), coalesced_at=NOW - timedelta(minutes=1)
    )


def _objective(objective_id: str = "goal-spa") -> PlanObjective:
    return PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=2),
        objective_id=objective_id,
    )


def _planning(objective: PlanObjective) -> DecisionPlanningRequest:
    return DecisionPlanningRequest(
        objective=objective,
        candidates=(
            AlternativeCandidate(
                "heater",
                "Heater only",
                {"readiness": 1.0},
                reasons=("Meets the deadline.",),
            ),
        ),
    )


def _request(**changes) -> SupervisoryEvaluationAssemblyRequest:
    objective = changes.pop("objective", _objective())
    values = {
        "coalescing_batch": _batch(),
        "evaluated_at": NOW,
        "runtime_mode": EvaluationRuntimeMode.SIMULATION,
        "goals": (objective,),
        "planning": _planning(objective),
        "observation": {"spa_temperature": 90.0},
        "forecast": {"energy_price": 0.22},
        "active_policy_ids": ("energy_aware",),
        "freshness": {"spa_temperature": "fresh"},
        "metadata": {"source": "test"},
    }
    values.update(changes)
    return SupervisoryEvaluationAssemblyRequest(**values)


def test_valid_input_reuses_existing_context_and_orchestration_models() -> None:
    result = SupervisoryEvaluationInputAssembler().assemble(_request())

    assert result.context.context_id.startswith("decision-evaluation-context-")
    assert result.context.trigger is EvaluationTrigger.EXPECTED_CHANGE_REACHED
    assert result.context.runtime_mode is EvaluationRuntimeMode.SIMULATION
    assert result.orchestration_request.context is result.context
    assert result.orchestration_request.coalesced_trigger is not None
    assert result.orchestration_request.planning.objective.objective_id == "goal-spa"


def test_equivalent_inputs_produce_identical_assembly() -> None:
    assembler = SupervisoryEvaluationInputAssembler()

    first = assembler.assemble(_request())
    second = assembler.assemble(_request())

    assert first == second
    assert first.assembly_id == second.assembly_id
    assert first.context.context_id == second.context.context_id


def test_goal_and_policy_input_order_is_normalized() -> None:
    primary = _objective("goal-primary")
    secondary = _objective("goal-secondary")
    assembler = SupervisoryEvaluationInputAssembler()

    first = assembler.assemble(
        _request(
            objective=primary,
            goals=(secondary, primary),
            planning=_planning(primary),
            active_policy_ids=("z-policy", "a-policy"),
            blockers=("z-blocker", "a-blocker"),
        )
    )
    second = assembler.assemble(
        _request(
            objective=primary,
            goals=(primary, secondary),
            planning=_planning(primary),
            active_policy_ids=("a-policy", "z-policy"),
            blockers=("a-blocker", "z-blocker"),
        )
    )

    assert first == second
    assert first.context.active_policy_ids == ("a-policy", "z-policy")
    assert first.context.blockers == ("a-blocker", "z-blocker")


def test_planning_objective_must_be_present_in_goals() -> None:
    context_goal = _objective("context-goal")
    planning_goal = _objective("planning-goal")

    with pytest.raises(ValueError, match="planning objective must be present"):
        _request(goals=(context_goal,), planning=_planning(planning_goal))


def test_batch_without_consumed_trigger_is_rejected() -> None:
    rejected = replace(
        _submission(),
        outcome=ReevaluationRuntimeSubmissionOutcome.REJECTED,
        accepted_submission_ids=(),
    )
    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (rejected,), coalesced_at=NOW - timedelta(minutes=1)
    )

    with pytest.raises(ValueError, match="coalesced trigger evidence"):
        SupervisoryEvaluationInputAssembler().assemble(
            _request(coalescing_batch=batch)
        )


def test_future_coalescing_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="from the future"):
        SupervisoryEvaluationInputAssembler().assemble(
            _request(evaluated_at=NOW - timedelta(minutes=2))
        )


def test_naive_evaluation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(evaluated_at=datetime(2026, 8, 4, 18, 0))


def test_non_json_identity_evidence_is_rejected() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        _request(observation={"bad": object()})


def test_context_identity_changes_when_factual_evidence_changes() -> None:
    assembler = SupervisoryEvaluationInputAssembler()
    first = assembler.assemble(_request(observation={"spa_temperature": 90.0}))
    second = assembler.assemble(_request(observation={"spa_temperature": 91.0}))

    assert first.context.context_id != second.context.context_id
    assert first.assembly_id != second.assembly_id


def test_blockers_are_preserved_without_invoking_evaluation() -> None:
    result = SupervisoryEvaluationInputAssembler().assemble(
        _request(blockers=("telemetry stale",))
    )

    assert result.context.planning_allowed is False
    assert result.context.blockers == ("telemetry stale",)


def test_context_and_provenance_are_immutable() -> None:
    result = SupervisoryEvaluationInputAssembler().assemble(_request())

    with pytest.raises(FrozenInstanceError):
        result.assembled_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.context.observation["spa_temperature"] = 95.0  # type: ignore[index]


def test_assembly_metadata_preserves_coalescing_traceability() -> None:
    result = SupervisoryEvaluationInputAssembler().assemble(_request())

    assert (
        result.context.metadata["runtime_trigger_coalescing_batch_id"]
        == result.coalescing_batch_id
    )
    assert result.context.metadata["runtime_trigger_consumed_submission_count"] == "1"
    assert result.provenance["supervisory_evaluation_context_id"] == result.context.context_id
