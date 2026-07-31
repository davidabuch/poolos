"""Contract tests for Epic 10.13I execution restart recovery."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_coordinator import (
    CoordinationEventKind,
    ExecutionCoordinationEvent,
)
from poolos.execution_flight_recorder import InMemoryExecutionFlightRecorder
from poolos.execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionLifecycleStatus,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionProposal,
    ExecutionStep,
    VerificationStatus,
)
from poolos.execution_restart_recovery import (
    ExecutionRecoveryClassification,
    ExecutionRecoveryDisposition,
    ExecutionRecoveryRecommendation,
    ExecutionRecoveryRequest,
    ExecutionRestartRecoveryEngine,
)
from poolos.execution_state_machine import ExecutionStateTransition
from poolos.execution_verification import (
    ExecutionVerificationEvidence,
    ExecutionVerificationResult,
    VerificationEvidenceDisposition,
)
from poolos.integration import StartPump


NOW = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)
RECOVERED_AT = NOW + timedelta(minutes=5)


def artifacts(
    *,
    authorization_disposition: AuthorizationDisposition = (
        AuthorizationDisposition.AUTHORIZED
    ),
    verification_status: VerificationStatus = VerificationStatus.VERIFIED,
    outcome_status: ExecutionLifecycleStatus = ExecutionLifecycleStatus.VERIFIED,
):
    operation = StartPump(
        equipment_id="main-pump",
        operation_id="operation-1",
    )
    proposal = ExecutionProposal(
        proposal_id="proposal-1",
        decision_id="decision-1",
        context_id="context-1",
        objective_id="objective-1",
        created_at=NOW,
        runtime_mode=RuntimeMode.SIMULATION,
        operations=(operation,),
        reason="Start simulated circulation.",
        expected_final_state={"pump.main-pump.running": True},
    )
    blockers = ()
    if authorization_disposition is not AuthorizationDisposition.AUTHORIZED:
        blockers = ("temporary_or_permanent_blocker",)
    authorization = ExecutionAuthorization(
        authorization_id="authorization-1",
        proposal_id=proposal.proposal_id,
        evaluated_at=NOW + timedelta(seconds=1),
        disposition=authorization_disposition,
        reason="Authorization evaluated.",
        blocking_reasons=blockers,
    )
    step = ExecutionStep(
        step_id="step-1",
        sequence=1,
        operation=operation,
        expected_observations={"pump.main-pump.running": True},
    )
    plan = ExecutionPlan(
        plan_id="plan-1",
        proposal_id=proposal.proposal_id,
        authorization_id=authorization.authorization_id,
        decision_id=proposal.decision_id,
        context_id=proposal.context_id,
        created_at=NOW + timedelta(seconds=2),
        steps=(step,),
        expected_final_state=proposal.expected_final_state,
    )
    planned = ExecutionStateTransition(
        transition_id="transition-planned",
        plan_id=plan.plan_id,
        from_status=ExecutionLifecycleStatus.AUTHORIZED,
        to_status=ExecutionLifecycleStatus.PLANNED,
        occurred_at=NOW + timedelta(seconds=3),
        reason="Plan admitted.",
    )
    executing = ExecutionStateTransition(
        transition_id="transition-executing",
        plan_id=plan.plan_id,
        from_status=ExecutionLifecycleStatus.PLANNED,
        to_status=ExecutionLifecycleStatus.EXECUTING,
        occurred_at=NOW + timedelta(seconds=4),
        reason="Execution coordination started.",
    )
    event = ExecutionCoordinationEvent(
        event_id="event-step-selected",
        plan_id=plan.plan_id,
        kind=CoordinationEventKind.STEP_SELECTED,
        occurred_at=NOW + timedelta(seconds=5),
        reason="Current step selected.",
        step_id=step.step_id,
    )
    evidence_disposition = VerificationEvidenceDisposition.MATCHED
    actual_value: object = True
    if verification_status in {VerificationStatus.PENDING, VerificationStatus.PARTIAL}:
        evidence_disposition = VerificationEvidenceDisposition.MISSING
        actual_value = None
    elif verification_status is VerificationStatus.FAILED:
        evidence_disposition = VerificationEvidenceDisposition.MISMATCHED
        actual_value = False
    verification = ExecutionVerificationResult(
        verification_id="verification-1",
        plan_id=plan.plan_id,
        step_id=step.step_id,
        status=verification_status,
        evaluated_at=NOW + timedelta(seconds=6),
        deadline=NOW + timedelta(seconds=30),
        reason="Verification evaluated.",
        evidence=(
            ExecutionVerificationEvidence(
                observation_id="pump.main-pump.running",
                expected_value=True,
                actual_value=actual_value,
                disposition=evidence_disposition,
                reason="Evidence evaluated.",
            ),
        ),
    )
    failure_reason = None
    if outcome_status not in {
        ExecutionLifecycleStatus.VERIFIED,
        ExecutionLifecycleStatus.COMPLETED,
    }:
        failure_reason = "Execution did not complete successfully."
    outcome = ExecutionOutcome(
        outcome_id="outcome-1",
        plan_id=plan.plan_id,
        proposal_id=plan.proposal_id,
        decision_id=plan.decision_id,
        context_id=plan.context_id,
        status=outcome_status,
        started_at=NOW + timedelta(seconds=2),
        completed_at=NOW + timedelta(seconds=7),
        failure_reason=failure_reason,
    )
    return (
        proposal,
        authorization,
        plan,
        planned,
        executing,
        event,
        verification,
        outcome,
    )


def request_for(recorder: InMemoryExecutionFlightRecorder) -> ExecutionRecoveryRequest:
    return ExecutionRecoveryRequest(
        records=recorder.records,
        recovered_at=RECOVERED_AT,
    )


def test_no_history_requires_no_execution_action() -> None:
    result = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(records=(), recovered_at=RECOVERED_AT)
    )

    assert result.classification is ExecutionRecoveryClassification.NO_HISTORY
    assert result.recommendations == (
        ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,
    )
    assert result.resume_permitted is False


def test_proposal_without_authorization_is_interrupted_and_reevaluated() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_BEFORE_AUTHORIZATION
    )
    assert result.requires_reevaluation
    assert ExecutionRecoveryRecommendation.MARK_SUPERSEDED in result.recommendations


def test_deferred_and_rejected_authorizations_are_distinguished() -> None:
    deferred_proposal, deferred_authorization, *_ = artifacts(
        authorization_disposition=AuthorizationDisposition.DEFERRED
    )
    deferred = InMemoryExecutionFlightRecorder()
    deferred.record_proposal(deferred_proposal)
    deferred.record_authorization(deferred_authorization)

    rejected_proposal, rejected_authorization, *_ = artifacts(
        authorization_disposition=AuthorizationDisposition.REJECTED
    )
    rejected = InMemoryExecutionFlightRecorder()
    rejected.record_proposal(rejected_proposal)
    rejected.record_authorization(rejected_authorization)

    deferred_result = ExecutionRestartRecoveryEngine().recover(request_for(deferred))
    rejected_result = ExecutionRestartRecoveryEngine().recover(request_for(rejected))

    assert deferred_result.classification is (
        ExecutionRecoveryClassification.AUTHORIZATION_DEFERRED
    )
    assert deferred_result.requires_reevaluation
    assert rejected_result.classification is (
        ExecutionRecoveryClassification.AUTHORIZATION_REJECTED
    )
    assert rejected_result.recommendations == (
        ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,
    )


def test_authorized_proposal_without_plan_is_interrupted_before_plan() -> None:
    proposal, authorization, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_BEFORE_PLAN
    )
    assert result.plan_id is None
    assert result.requires_reevaluation


def test_plan_without_execution_activity_is_interrupted_before_execution() -> None:
    proposal, authorization, plan, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_BEFORE_EXECUTION
    )
    assert result.plan_id == plan.plan_id
    assert result.session_id == "execution-session-plan-1"


def test_execution_activity_is_never_resumed() -> None:
    proposal, authorization, plan, planned, executing, event, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(planned)
    recorder.record_transition(executing)
    recorder.record_coordination_event(event)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_DURING_EXECUTION
    )
    assert result.latest_lifecycle_status is ExecutionLifecycleStatus.EXECUTING
    assert result.resume_permitted is False
    assert result.requires_reevaluation


def test_pending_verification_is_interrupted_during_verification() -> None:
    proposal, authorization, plan, planned, executing, event, verification, _ = (
        artifacts(verification_status=VerificationStatus.PENDING)
    )
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(planned)
    recorder.record_transition(executing)
    recorder.record_coordination_event(event)
    recorder.record_verification(verification)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_DURING_VERIFICATION
    )
    assert result.latest_verification_status is VerificationStatus.PENDING


def test_terminal_verification_without_outcome_is_incomplete() -> None:
    proposal, authorization, plan, planned, executing, event, verification, _ = (
        artifacts()
    )
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(planned)
    recorder.record_transition(executing)
    recorder.record_coordination_event(event)
    recorder.record_verification(verification)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is (
        ExecutionRecoveryClassification.INCOMPLETE_AFTER_VERIFICATION
    )
    assert result.latest_verification_status is VerificationStatus.VERIFIED
    assert result.requires_reevaluation


def test_completed_outcome_requires_no_action() -> None:
    proposal, authorization, plan, planned, executing, event, verification, outcome = (
        artifacts()
    )
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(planned)
    recorder.record_transition(executing)
    recorder.record_coordination_event(event)
    recorder.record_verification(verification)
    recorder.record_outcome(outcome)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is ExecutionRecoveryClassification.COMPLETED
    assert result.recommendations == (
        ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,
    )
    assert result.resume_permitted is False


def test_terminal_failure_recommends_fresh_reevaluation() -> None:
    proposal, authorization, plan, planned, executing, event, verification, outcome = (
        artifacts(
            verification_status=VerificationStatus.FAILED,
            outcome_status=ExecutionLifecycleStatus.FAILED,
        )
    )
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(planned)
    recorder.record_transition(executing)
    recorder.record_coordination_event(event)
    recorder.record_verification(verification)
    recorder.record_outcome(outcome)

    result = ExecutionRestartRecoveryEngine().recover(request_for(recorder))

    assert result.classification is ExecutionRecoveryClassification.TERMINAL_FAILURE
    assert result.requires_reevaluation
    assert result.resume_permitted is False


def test_corrupt_sequence_is_reported_and_requires_operator() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    corrupt_record = replace(recorder.records[0], sequence=2)

    result = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(
            records=(corrupt_record,),
            recovered_at=RECOVERED_AT,
        )
    )

    assert result.disposition is ExecutionRecoveryDisposition.CORRUPT
    assert result.classification is ExecutionRecoveryClassification.CORRUPT_HISTORY
    assert result.recommendations == (
        ExecutionRecoveryRecommendation.RECORD_CORRUPTION,
        ExecutionRecoveryRecommendation.AWAIT_OPERATOR,
    )


def test_future_history_is_corrupt() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)

    result = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(
            records=recorder.records,
            recovered_at=NOW - timedelta(seconds=1),
        )
    )

    assert result.classification is ExecutionRecoveryClassification.CORRUPT_HISTORY
    assert result.reason == "history_contains_future_record"


def test_requested_proposal_must_exist() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)

    result = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(
            records=recorder.records,
            recovered_at=RECOVERED_AT,
            proposal_id="missing-proposal",
        )
    )

    assert result.classification is ExecutionRecoveryClassification.CORRUPT_HISTORY
    assert "requested_proposal_not_found" in result.reason


def test_assessments_are_deterministic_and_immutable() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    request = request_for(recorder)

    first = ExecutionRestartRecoveryEngine().recover(request)
    second = ExecutionRestartRecoveryEngine().recover(request)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.reason = "changed"  # type: ignore[misc]


def test_recovery_engine_has_no_execution_or_external_collaborator() -> None:
    engine = ExecutionRestartRecoveryEngine()

    assert not hasattr(engine, "coordinator")
    assert not hasattr(engine, "gateway")
    assert not hasattr(engine, "endpoint")
    assert not hasattr(engine, "transport")
    assert not hasattr(engine, "home_assistant")
    assert not hasattr(engine, "pentair")
