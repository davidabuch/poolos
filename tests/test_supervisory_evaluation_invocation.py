from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
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
from poolos.planning import ObjectiveType, PlanObjective
from poolos.reevaluation_runtime_submission import ReevaluationRuntimeSubmissionOutcome
from poolos.runtime_trigger_coalescing import RuntimeTriggerCoalescingBoundary
from poolos.supervisory_evaluation_assembly import (
    SupervisoryEvaluationAssemblyRequest,
    SupervisoryEvaluationInputAssembler,
)
from poolos.supervisory_evaluation_invocation import (
    SupervisoryEvaluationInvocationRequest,
    SupervisoryEvaluationInvoker,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 4, 19, 0, tzinfo=UTC)


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
    def __init__(self, *, context_id: str, status: OrchestrationStatus) -> None:
        self.calls = 0
        self.context_id = context_id
        self.status = status

    def evaluate(self, request, kernel) -> DecisionOrchestrationResult:
        self.calls += 1
        blockers = ("telemetry stale",) if self.status is OrchestrationStatus.BLOCKED_CONTEXT else ()
        return DecisionOrchestrationResult(
            status=self.status,
            context_id=self.context_id,
            trigger=request.context.trigger.value,
            runtime_mode=request.context.runtime_mode.value,
            blockers=blockers,
        )


def _assembly(*, runtime_mode: EvaluationRuntimeMode = EvaluationRuntimeMode.SIMULATION):
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
    return SupervisoryEvaluationInputAssembler().assemble(
        SupervisoryEvaluationAssemblyRequest(
            coalescing_batch=batch,
            evaluated_at=NOW,
            runtime_mode=runtime_mode,
            goals=(objective,),
            planning=planning,
            blockers=("telemetry stale",),
        )
    )


def _kernel() -> PoolKernel:
    return cast(PoolKernel, object())


def test_invokes_existing_orchestrator_exactly_once() -> None:
    assembly = _assembly()
    recorder = _RecordingOrchestrator(
        context_id=assembly.context.context_id,
        status=OrchestrationStatus.BLOCKED_CONTEXT,
    )

    result = SupervisoryEvaluationInvoker().invoke(
        SupervisoryEvaluationInvocationRequest(assembly=assembly, invoked_at=NOW),
        cast(DecisionOrchestrator, recorder),
        _kernel(),
    )

    assert recorder.calls == 1
    assert result.orchestration.status is OrchestrationStatus.BLOCKED_CONTEXT
    assert result.status is OrchestrationStatus.BLOCKED_CONTEXT


def test_equivalent_replay_has_stable_identity_despite_later_timestamp() -> None:
    assembly = _assembly()
    invoker = SupervisoryEvaluationInvoker()

    def run(at: datetime):
        orchestrator = _RecordingOrchestrator(
            context_id=assembly.context.context_id,
            status=OrchestrationStatus.BLOCKED_CONTEXT,
        )
        return invoker.invoke(
            SupervisoryEvaluationInvocationRequest(assembly=assembly, invoked_at=at),
            cast(DecisionOrchestrator, orchestrator),
            _kernel(),
        )

    first = run(NOW)
    second = run(NOW + timedelta(minutes=30))

    assert first.invocation_id == second.invocation_id
    assert first.invoked_at != second.invoked_at


def test_invocation_preserves_all_upstream_identities() -> None:
    assembly = _assembly()
    orchestrator = _RecordingOrchestrator(
        context_id=assembly.context.context_id,
        status=OrchestrationStatus.BLOCKED_CONTEXT,
    )

    result = SupervisoryEvaluationInvoker().invoke(
        SupervisoryEvaluationInvocationRequest(assembly=assembly, invoked_at=NOW),
        cast(DecisionOrchestrator, orchestrator),
        _kernel(),
    )

    assert result.assembly_id == assembly.assembly_id
    assert result.coalescing_batch_id == assembly.coalescing_batch_id
    assert result.context_id == assembly.context.context_id
    assert result.provenance["supervisory_evaluation_assembly_id"] == assembly.assembly_id
    assert result.provenance["runtime_trigger_coalescing_batch_id"] == assembly.coalescing_batch_id


def test_invocation_result_is_immutable() -> None:
    assembly = _assembly()
    orchestrator = _RecordingOrchestrator(
        context_id=assembly.context.context_id,
        status=OrchestrationStatus.BLOCKED_CONTEXT,
    )
    result = SupervisoryEvaluationInvoker().invoke(
        SupervisoryEvaluationInvocationRequest(assembly=assembly, invoked_at=NOW),
        cast(DecisionOrchestrator, orchestrator),
        _kernel(),
    )

    with pytest.raises(FrozenInstanceError):
        result.invoked_at = NOW + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_naive_invocation_time_is_rejected_before_orchestrator_call() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SupervisoryEvaluationInvocationRequest(
            assembly=_assembly(), invoked_at=datetime(2026, 8, 4, 19, 0)
        )


def test_invocation_cannot_precede_assembly() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        SupervisoryEvaluationInvocationRequest(
            assembly=_assembly(), invoked_at=NOW - timedelta(seconds=1)
        )


def test_non_simulation_context_is_rejected() -> None:
    with pytest.raises(ValueError, match="simulation-only"):
        SupervisoryEvaluationInvocationRequest(
            assembly=_assembly(runtime_mode=EvaluationRuntimeMode.SHADOW),
            invoked_at=NOW,
        )


def test_inconsistent_assembly_identity_is_rejected() -> None:
    assembly = _assembly()
    inconsistent = replace(assembly, assembly_id="different-assembly")

    with pytest.raises(ValueError, match="assembly identity"):
        SupervisoryEvaluationInvocationRequest(
            assembly=inconsistent,
            invoked_at=NOW,
        )


def test_mismatched_orchestration_context_is_rejected() -> None:
    assembly = _assembly()
    orchestrator = _RecordingOrchestrator(
        context_id="different-context",
        status=OrchestrationStatus.BLOCKED_CONTEXT,
    )

    with pytest.raises(ValueError, match="different context"):
        SupervisoryEvaluationInvoker().invoke(
            SupervisoryEvaluationInvocationRequest(assembly=assembly, invoked_at=NOW),
            cast(DecisionOrchestrator, orchestrator),
            _kernel(),
        )

    assert orchestrator.calls == 1


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        SupervisoryEvaluationInvoker(boundary_name="")
