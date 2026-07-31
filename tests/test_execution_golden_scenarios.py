"""Golden end-to-end scenarios for the supervisory execution pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_coordinator import ExecutionCoordinator
from poolos.execution_flight_recorder import InMemoryExecutionFlightRecorder
from poolos.execution_golden_scenarios import (
    EXECUTION_GOLDEN_SCENARIOS,
    ExecutionGoldenScenarioId,
    validate_execution_golden_catalog,
)
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
    ExecutionRecoveryRecommendation,
    ExecutionRecoveryRequest,
    ExecutionRestartRecoveryEngine,
)
from poolos.execution_verification import (
    ExecutionVerificationEngine,
    ExecutionVerificationRequest,
)
from poolos.integration import StartPump
from poolos.observations import (
    FreshnessPolicy,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
)

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


def artifacts(
    *,
    disposition: AuthorizationDisposition = AuthorizationDisposition.AUTHORIZED,
    verification_required: bool = True,
) -> tuple[ExecutionProposal, ExecutionAuthorization, ExecutionPlan]:
    operation = StartPump(equipment_id="main-pump", operation_id="operation-1")
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
    authorization = ExecutionAuthorization(
        authorization_id="authorization-1",
        proposal_id=proposal.proposal_id,
        evaluated_at=NOW + timedelta(seconds=1),
        disposition=disposition,
        reason="Authorization evaluated.",
        blocking_reasons=(
            ("blocked",)
            if disposition is not AuthorizationDisposition.AUTHORIZED
            else ()
        ),
    )
    step = ExecutionStep(
        step_id="step-1",
        sequence=1,
        operation=operation,
        expected_observations=(
            {"pump.main-pump.running": True} if verification_required else {}
        ),
        verification_required=verification_required,
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
    return proposal, authorization, plan


def store_with(value: object) -> ObservationStore:
    store = ObservationStore()
    store.put(
        PoolObservation(
            observation_id="pump.main-pump.running",
            value=value,
            observed_at=NOW + timedelta(seconds=8),
            source_kind=ObservationSourceKind.SIMULATED,
            source_id="simulator-1",
            quality=ObservationQuality.GOOD,
        )
    )
    return store


def verify(plan: ExecutionPlan, store: ObservationStore, *, at: datetime) -> object:
    return ExecutionVerificationEngine().verify(
        ExecutionVerificationRequest(
            plan_id=plan.plan_id,
            step=plan.steps[0],
            observations=store,
            verification_started_at=NOW + timedelta(seconds=7),
            evaluated_at=at,
            timeout=timedelta(seconds=20),
            freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=30)),
            source_id="simulator-1",
        )
    )


def populated_execution(*, verification_status: VerificationStatus = VerificationStatus.VERIFIED):
    proposal, authorization, plan = artifacts()
    coordinator = ExecutionCoordinator()
    admitted = coordinator.admit(plan, occurred_at=NOW + timedelta(seconds=3))
    started = coordinator.start(plan, admitted.session, occurred_at=NOW + timedelta(seconds=4))
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    assert admitted.lifecycle_transition is not None
    assert started.lifecycle_transition is not None
    assert started.event is not None
    recorder.record_transition(admitted.lifecycle_transition)
    recorder.record_transition(started.lifecycle_transition)
    recorder.record_coordination_event(started.event)
    if verification_status is VerificationStatus.VERIFIED:
        result = verify(plan, store_with(True), at=NOW + timedelta(seconds=9))
    elif verification_status is VerificationStatus.FAILED:
        result = verify(plan, store_with(False), at=NOW + timedelta(seconds=9))
    else:
        result = verify(plan, ObservationStore(), at=NOW + timedelta(seconds=28))
    recorder.record_verification(result)
    return proposal, authorization, plan, recorder, result


def test_catalog_is_complete_and_stable() -> None:
    validate_execution_golden_catalog()
    assert len(EXECUTION_GOLDEN_SCENARIOS) == 10
    assert {item.scenario_id for item in EXECUTION_GOLDEN_SCENARIOS} == set(
        ExecutionGoldenScenarioId
    )


def test_verified_execution_records_completed_outcome_and_recovers_cleanly() -> None:
    proposal, _, plan, recorder, verification = populated_execution()
    assert verification.status is VerificationStatus.VERIFIED
    outcome = ExecutionOutcome(
        outcome_id="outcome-1",
        plan_id=plan.plan_id,
        proposal_id=proposal.proposal_id,
        decision_id=proposal.decision_id,
        context_id=proposal.context_id,
        status=ExecutionLifecycleStatus.VERIFIED,
        started_at=plan.created_at,
        completed_at=NOW + timedelta(seconds=10),
    )
    recorder.record_outcome(outcome)
    assessment = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(records=recorder.records, recovered_at=NOW + timedelta(minutes=1))
    )
    assert assessment.classification is ExecutionRecoveryClassification.COMPLETED
    assert assessment.recommendations == (ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,)
    assert assessment.resume_permitted is False


def test_verification_not_required_is_terminal_without_evidence() -> None:
    _, _, plan = artifacts(verification_required=False)
    result = verify(plan, ObservationStore(), at=NOW + timedelta(seconds=9))
    assert result.status is VerificationStatus.NOT_REQUIRED
    assert result.evidence == ()


@pytest.mark.parametrize(
    ("disposition", "classification"),
    [
        (AuthorizationDisposition.REJECTED, ExecutionRecoveryClassification.AUTHORIZATION_REJECTED),
        (AuthorizationDisposition.DEFERRED, ExecutionRecoveryClassification.AUTHORIZATION_DEFERRED),
    ],
)
def test_non_authorized_histories_are_classified_without_planning(
    disposition: AuthorizationDisposition,
    classification: ExecutionRecoveryClassification,
) -> None:
    proposal, authorization, _ = artifacts(disposition=disposition)
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    assessment = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(records=recorder.records, recovered_at=NOW + timedelta(minutes=1))
    )
    assert assessment.classification is classification
    assert assessment.resume_permitted is False


def test_fresh_contradictory_evidence_fails_verification() -> None:
    *_, result = populated_execution(verification_status=VerificationStatus.FAILED)
    assert result.status is VerificationStatus.FAILED


def test_missing_evidence_at_deadline_times_out() -> None:
    *_, result = populated_execution(verification_status=VerificationStatus.TIMED_OUT)
    assert result.status is VerificationStatus.TIMED_OUT


def test_restart_during_execution_never_resumes() -> None:
    _, _, _, recorder, _ = populated_execution()
    records = recorder.records[:-1]
    assessment = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(records=records, recovered_at=NOW + timedelta(minutes=1))
    )
    assert assessment.classification is ExecutionRecoveryClassification.INTERRUPTED_DURING_EXECUTION
    assert assessment.resume_permitted is False
    assert ExecutionRecoveryRecommendation.REEVALUATE in assessment.recommendations


def test_restart_during_verification_never_resumes() -> None:
    _, _, _, recorder, result = populated_execution(
        verification_status=VerificationStatus.TIMED_OUT
    )
    pending = replace(
        result,
        status=VerificationStatus.PENDING,
        evaluated_at=NOW + timedelta(seconds=9),
    )
    pending_record = replace(
        recorder.records[-1],
        artifact_id=pending.verification_id,
        occurred_at=pending.evaluated_at,
        artifact=pending,
    )
    assessment = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(
            records=(*recorder.records[:-1], pending_record),
            recovered_at=NOW + timedelta(minutes=1),
        )
    )
    assert assessment.classification is (
        ExecutionRecoveryClassification.INTERRUPTED_DURING_VERIFICATION
    )
    assert assessment.resume_permitted is False


def test_corrupt_history_is_surfaced_for_operator_attention() -> None:
    proposal, _, _ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    corrupt = replace(recorder.records[0], sequence=2)
    assessment = ExecutionRestartRecoveryEngine().recover(
        ExecutionRecoveryRequest(records=(corrupt,), recovered_at=NOW + timedelta(minutes=1))
    )
    assert assessment.classification is ExecutionRecoveryClassification.CORRUPT_HISTORY
    assert ExecutionRecoveryRecommendation.RECORD_CORRUPTION in assessment.recommendations
    assert ExecutionRecoveryRecommendation.AWAIT_OPERATOR in assessment.recommendations
