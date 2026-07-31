"""Contract tests for Epic 10.13H execution flight recording."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_coordinator import CoordinationEventKind, ExecutionCoordinationEvent
from poolos.execution_flight_recorder import (
    ExecutionRecordType,
    InMemoryExecutionFlightRecorder,
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
from poolos.execution_state_machine import ExecutionStateTransition
from poolos.execution_verification import (
    ExecutionVerificationEvidence,
    ExecutionVerificationResult,
    VerificationEvidenceDisposition,
)
from poolos.integration import StartPump


NOW = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)


def artifacts():
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
    authorization = ExecutionAuthorization(
        authorization_id="authorization-1",
        proposal_id=proposal.proposal_id,
        evaluated_at=NOW + timedelta(seconds=1),
        disposition=AuthorizationDisposition.AUTHORIZED,
        reason="Simulation-only proposal is authorized.",
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
    transition = ExecutionStateTransition(
        transition_id="transition-1",
        plan_id=plan.plan_id,
        from_status=ExecutionLifecycleStatus.AUTHORIZED,
        to_status=ExecutionLifecycleStatus.PLANNED,
        occurred_at=NOW + timedelta(seconds=3),
        reason="Plan admitted.",
    )
    event = ExecutionCoordinationEvent(
        event_id="event-1",
        plan_id=plan.plan_id,
        kind=CoordinationEventKind.PLAN_ADMITTED,
        occurred_at=NOW + timedelta(seconds=4),
        reason="Plan admitted by coordinator.",
        lifecycle_transition_id=transition.transition_id,
    )
    verification = ExecutionVerificationResult(
        verification_id="verification-1",
        plan_id=plan.plan_id,
        step_id=step.step_id,
        status=VerificationStatus.VERIFIED,
        evaluated_at=NOW + timedelta(seconds=5),
        deadline=NOW + timedelta(seconds=10),
        reason="All expected observations verified.",
        evidence=(
            ExecutionVerificationEvidence(
                observation_id="pump.main-pump.running",
                expected_value=True,
                actual_value=True,
                disposition=VerificationEvidenceDisposition.MATCHED,
                reason="Observation matched.",
            ),
        ),
    )
    outcome = ExecutionOutcome(
        outcome_id="outcome-1",
        plan_id=plan.plan_id,
        proposal_id=plan.proposal_id,
        decision_id=plan.decision_id,
        context_id=plan.context_id,
        status=ExecutionLifecycleStatus.VERIFIED,
        started_at=NOW + timedelta(seconds=2),
        completed_at=NOW + timedelta(seconds=6),
    )
    return proposal, authorization, plan, transition, event, verification, outcome


def populated_recorder() -> InMemoryExecutionFlightRecorder:
    recorder = InMemoryExecutionFlightRecorder()
    for artifact in artifacts():
        if isinstance(artifact, ExecutionProposal):
            recorder.record_proposal(artifact)
        elif isinstance(artifact, ExecutionAuthorization):
            recorder.record_authorization(artifact)
        elif isinstance(artifact, ExecutionPlan):
            recorder.record_plan(artifact)
        elif isinstance(artifact, ExecutionStateTransition):
            recorder.record_transition(artifact)
        elif isinstance(artifact, ExecutionCoordinationEvent):
            recorder.record_coordination_event(artifact)
        elif isinstance(artifact, ExecutionVerificationResult):
            recorder.record_verification(artifact)
        else:
            recorder.record_outcome(artifact)
    return recorder


def test_complete_execution_history_is_append_only_and_traceable() -> None:
    recorder = populated_recorder()

    assert tuple(record.sequence for record in recorder.records) == tuple(range(1, 8))
    assert tuple(record.record_type for record in recorder.records) == (
        ExecutionRecordType.PROPOSAL,
        ExecutionRecordType.AUTHORIZATION,
        ExecutionRecordType.PLAN,
        ExecutionRecordType.LIFECYCLE_TRANSITION,
        ExecutionRecordType.COORDINATION_EVENT,
        ExecutionRecordType.VERIFICATION,
        ExecutionRecordType.OUTCOME,
    )
    assert all(record.decision_id == "decision-1" for record in recorder.records)
    assert all(record.context_id == "context-1" for record in recorder.records)
    assert all(record.proposal_id == "proposal-1" for record in recorder.records)
    assert recorder.records[2].session_id == "execution-session-plan-1"
    assert all(
        record.session_id == "execution-session-plan-1"
        for record in recorder.records[2:]
    )


def test_recorded_artifacts_can_be_recovered_without_reconstruction() -> None:
    proposal, authorization, plan, transition, event, verification, outcome = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    recorder.record_transition(transition)
    recorder.record_coordination_event(event)
    recorder.record_verification(verification)
    recorder.record_outcome(outcome)

    assert recorder.records[0].artifact is proposal
    assert recorder.records[-1].artifact is outcome
    assert recorder.timeline.latest is recorder.latest


def test_export_is_stable_json_and_contains_full_artifact_snapshots() -> None:
    first = populated_recorder().export_json()
    second = populated_recorder().export_json()

    assert first == second
    payload = json.loads(first)
    assert payload[0]["artifact"]["proposal_id"] == "proposal-1"
    assert payload[2]["artifact"]["steps"][0]["operation"]["operation_id"] == (
        "operation-1"
    )
    assert payload[-1]["artifact"]["outcome_id"] == "outcome-1"


def test_record_ids_are_deterministic_for_identical_append_order() -> None:
    first = populated_recorder()
    second = populated_recorder()

    assert tuple(record.record_id for record in first.records) == tuple(
        record.record_id for record in second.records
    )


def test_duplicate_artifact_is_rejected_without_mutating_history() -> None:
    proposal = artifacts()[0]
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)

    with pytest.raises(ValueError, match="already been recorded"):
        recorder.record_proposal(proposal)

    assert len(recorder.records) == 1


def test_authorization_requires_recorded_proposal() -> None:
    authorization = artifacts()[1]

    with pytest.raises(ValueError, match="proposal must be recorded first"):
        InMemoryExecutionFlightRecorder().record_authorization(authorization)


def test_plan_requires_matching_recorded_authorization() -> None:
    proposal, authorization, plan, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)

    with pytest.raises(ValueError, match="authorization must be recorded first"):
        recorder.record_plan(plan)

    recorder.record_authorization(authorization)
    mismatched = ExecutionPlan(
        plan_id="plan-2",
        proposal_id=plan.proposal_id,
        authorization_id=plan.authorization_id,
        decision_id="different-decision",
        context_id=plan.context_id,
        created_at=plan.created_at,
        steps=plan.steps,
    )
    with pytest.raises(ValueError, match="decision_id must match"):
        recorder.record_plan(mismatched)


def test_plan_scoped_artifacts_require_recorded_plan() -> None:
    transition = artifacts()[3]

    with pytest.raises(ValueError, match="plan must be recorded first"):
        InMemoryExecutionFlightRecorder().record_transition(transition)


def test_unknown_step_references_are_rejected() -> None:
    proposal, authorization, plan, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    recorder.record_plan(plan)
    event = ExecutionCoordinationEvent(
        event_id="event-unknown-step",
        plan_id=plan.plan_id,
        kind=CoordinationEventKind.STEP_SELECTED,
        occurred_at=NOW + timedelta(seconds=4),
        reason="Select unknown step.",
        step_id="step-999",
    )

    with pytest.raises(ValueError, match="not part of the plan"):
        recorder.record_coordination_event(event)


def test_backdated_append_is_rejected() -> None:
    proposal, authorization, *_ = artifacts()
    recorder = InMemoryExecutionFlightRecorder()
    recorder.record_proposal(proposal)
    recorder.record_authorization(authorization)
    old_proposal = ExecutionProposal(
        proposal_id="proposal-old",
        decision_id="decision-old",
        context_id="context-old",
        objective_id="objective-old",
        created_at=NOW - timedelta(seconds=1),
        runtime_mode=RuntimeMode.SIMULATION,
        operations=(
            StartPump(
                equipment_id="backup-pump",
                operation_id="operation-old",
            ),
        ),
        reason="Backdated proposal.",
    )

    with pytest.raises(ValueError, match="appended chronologically"):
        recorder.record_proposal(old_proposal)


def test_completed_history_is_closed_to_later_records() -> None:
    recorder = populated_recorder()
    transition = ExecutionStateTransition(
        transition_id="transition-late",
        plan_id="plan-1",
        from_status=ExecutionLifecycleStatus.VERIFIED,
        to_status=ExecutionLifecycleStatus.COMPLETED,
        occurred_at=NOW + timedelta(seconds=7),
        reason="Late transition.",
    )

    with pytest.raises(ValueError, match="append-closed"):
        recorder.record_transition(transition)


def test_history_queries_preserve_append_order() -> None:
    recorder = populated_recorder()

    assert recorder.history_for_plan("plan-1") == recorder.records[2:]
    assert recorder.history_for_decision("decision-1") == recorder.records
    assert recorder.history_for_session("execution-session-plan-1") == (
        recorder.records[2:]
    )
    assert recorder.timeline.of_type(ExecutionRecordType.VERIFICATION) == (
        recorder.records[5],
    )


def test_record_and_timeline_models_are_immutable() -> None:
    recorder = populated_recorder()

    with pytest.raises(FrozenInstanceError):
        recorder.records[0].sequence = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        recorder.timeline.records = ()  # type: ignore[misc]


def test_recorder_has_no_delivery_or_external_system_collaborator() -> None:
    recorder = InMemoryExecutionFlightRecorder()

    assert not hasattr(recorder, "gateway")
    assert not hasattr(recorder, "endpoint")
    assert not hasattr(recorder, "transport")
    assert not hasattr(recorder, "home_assistant")
    assert not hasattr(recorder, "pentair")
