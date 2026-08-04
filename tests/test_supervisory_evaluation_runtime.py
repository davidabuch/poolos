from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from poolos.alternative_ranking import AlternativeCandidate
from poolos.decision_orchestrator import (
    DecisionOrchestrationResult,
    DecisionOrchestrator,
    OrchestrationStatus,
)
from poolos.decision_planning import DecisionPlanningRequest
from poolos.evaluation_context import EvaluationRuntimeMode, EvaluationTrigger
from poolos.evaluation_triggers import EvaluationTriggerRequest, TriggerUrgency
from poolos.kernel import PoolKernel
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalTarget,
)
from poolos.planning import ObjectiveType, PlanObjective
from poolos.reevaluation_runtime_submission import ReevaluationRuntimeSubmissionOutcome
from poolos.runtime_trigger_coalescing import RuntimeTriggerCoalescingBoundary
from poolos.supervisory_evaluation_assembly import SupervisoryEvaluationAssemblyRequest
from poolos.supervisory_evaluation_runtime import (
    SupervisoryEvaluationRuntime,
    SupervisoryEvaluationRuntimeRequest,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 4, 21, 0, tzinfo=UTC)


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


class _RecordingOrchestrator:
    def __init__(self, context_id: str) -> None:
        self.context_id = context_id
        self.calls = 0

    def evaluate(self, request, kernel) -> DecisionOrchestrationResult:
        self.calls += 1
        return DecisionOrchestrationResult(
            status=OrchestrationStatus.BLOCKED_CONTEXT,
            context_id=self.context_id,
            trigger=request.context.trigger.value,
            runtime_mode=request.context.runtime_mode.value,
            blockers=("telemetry stale",),
        )


def _assembly_request() -> SupervisoryEvaluationAssemblyRequest:
    objective = PlanObjective(
        objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
        body_id="spa",
        target_temperature=100.0,
        earliest_start=NOW,
        deadline=NOW + timedelta(hours=2),
        objective_id="goal-spa",
    )
    submission = _Submission(
        result_id="result-submission-a",
        outcome=ReevaluationRuntimeSubmissionOutcome.ACCEPTED,
        request=_Request(
            submission_id="submission-a",
            trigger_request=EvaluationTriggerRequest(
                trigger=EvaluationTrigger.EXPECTED_CHANGE_REACHED,
                requested_at=NOW - timedelta(minutes=10),
                urgency=TriggerUrgency.NORMAL,
                source="poolos.due_reevaluation_trigger_boundary",
                reason="Scheduled expected change reached: spa readiness",
            ),
        ),
        submitted_at=NOW - timedelta(minutes=5),
        accepted_submission_ids=("submission-a",),
    )
    batch = RuntimeTriggerCoalescingBoundary().coalesce(
        (submission,), coalesced_at=NOW - timedelta(minutes=1)
    )
    planning = DecisionPlanningRequest(
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
    return SupervisoryEvaluationAssemblyRequest(
        coalescing_batch=batch,
        evaluated_at=NOW,
        runtime_mode=EvaluationRuntimeMode.SIMULATION,
        goals=(objective,),
        planning=planning,
        blockers=("telemetry stale",),
    )


def _kernel() -> PoolKernel:
    return cast(PoolKernel, object())


def _run(at: datetime = NOW):
    runtime = SupervisoryEvaluationRuntime()
    assembly_request = _assembly_request()
    provisional = runtime.assembler.assemble(assembly_request)
    orchestrator = _RecordingOrchestrator(provisional.context.context_id)
    result = runtime.run(
        SupervisoryEvaluationRuntimeRequest(
            assembly_request=assembly_request,
            invoked_at=at,
        ),
        cast(DecisionOrchestrator, orchestrator),
        _kernel(),
    )
    return result, orchestrator


def test_composes_complete_blocked_cycle() -> None:
    result, orchestrator = _run()

    assert orchestrator.calls == 1
    assert result.invocation.status is OrchestrationStatus.BLOCKED_CONTEXT
    assert result.operational_evaluation.disposition is OperationalDisposition.BLOCK
    assert result.operational_instruction.action is OperationalAction.HALT
    assert result.operational_instruction.target is OperationalTarget.OPERATOR_REVIEW


def test_preserves_one_context_across_every_stage() -> None:
    result, _ = _run()
    context_id = result.assembly.context.context_id

    assert result.invocation.context_id == context_id
    assert result.operational_evaluation.context_id == context_id
    assert result.operational_instruction.context_id == context_id


def test_runtime_identity_is_stable_across_replay_time() -> None:
    first, _ = _run(NOW)
    second, _ = _run(NOW + timedelta(minutes=30))

    assert first.runtime_id == second.runtime_id
    assert first.completed_at != second.completed_at


def test_provenance_preserves_upstream_identities() -> None:
    result, _ = _run()

    assert (
        result.provenance["supervisory_evaluation_assembly_id"]
        == result.assembly.assembly_id
    )
    assert (
        result.provenance["supervisory_evaluation_invocation_id"]
        == result.invocation.invocation_id
    )
    assert result.provenance["supervisory_evaluation_runtime_id"] == result.runtime_id


def test_runtime_result_is_immutable() -> None:
    result, _ = _run()

    with pytest.raises(FrozenInstanceError):
        result.completed_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_naive_invocation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SupervisoryEvaluationRuntimeRequest(
            assembly_request=_assembly_request(),
            invoked_at=datetime(2026, 8, 4, 21, 0),
        )


def test_invocation_time_cannot_precede_evaluation() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        SupervisoryEvaluationRuntimeRequest(
            assembly_request=_assembly_request(),
            invoked_at=NOW - timedelta(seconds=1),
        )


def test_empty_runtime_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        SupervisoryEvaluationRuntime(boundary_name="")


def test_runtime_exposes_command_free_operational_instruction_only() -> None:
    result, _ = _run()

    assert result.operational_instruction.action is OperationalAction.HALT
    assert result.operational_instruction.target is OperationalTarget.OPERATOR_REVIEW
    assert "execution" not in result.provenance
