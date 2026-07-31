"""Contract tests for the Epic 10.13 supervisory execution domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from poolos.environment import RuntimeMode
from poolos.execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionLifecycleStatus,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionProposal,
    ExecutionStep,
    StepOutcome,
    VerificationStatus,
)
from poolos.integration import SetPumpSpeed, StartPump


NOW = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)


def operation(*, operation_id: str = "op-1") -> StartPump:
    return StartPump(equipment_id="main-pump", operation_id=operation_id)


def step(*, step_id: str = "step-1", sequence: int = 1) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        sequence=sequence,
        operation=operation(operation_id=f"op-{sequence}"),
        expected_observations={"pump.main-pump.running": True},
    )


def test_execution_proposal_is_immutable_and_freezes_collections() -> None:
    expected = {"pump.main-pump.running": True}
    metadata = {"source": "decision-orchestrator"}
    operations = [operation()]

    proposal = ExecutionProposal(
        proposal_id="proposal-1",
        decision_id="decision-1",
        context_id="context-1",
        objective_id="objective-1",
        created_at=NOW,
        runtime_mode=RuntimeMode.SIMULATION,
        operations=operations,
        reason="Start required circulation.",
        expected_final_state=expected,
        metadata=metadata,
    )

    operations.append(operation(operation_id="op-2"))
    expected["changed"] = True
    metadata["changed"] = "yes"

    assert len(proposal.operations) == 1
    assert dict(proposal.expected_final_state) == {"pump.main-pump.running": True}
    assert dict(proposal.metadata) == {"source": "decision-orchestrator"}
    with pytest.raises(TypeError):
        proposal.expected_final_state["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        proposal.reason = "changed"  # type: ignore[misc]


def test_execution_proposal_requires_canonical_unique_operations() -> None:
    duplicate = operation(operation_id="duplicate")
    with pytest.raises(ValueError, match="operation IDs must be unique"):
        ExecutionProposal(
            proposal_id="proposal-1",
            decision_id="decision-1",
            context_id="context-1",
            objective_id="objective-1",
            created_at=NOW,
            runtime_mode=RuntimeMode.SIMULATION,
            operations=(duplicate, duplicate),
            reason="Duplicate test.",
        )

    with pytest.raises(TypeError, match="PoolOperation"):
        ExecutionProposal(
            proposal_id="proposal-1",
            decision_id="decision-1",
            context_id="context-1",
            objective_id="objective-1",
            created_at=NOW,
            runtime_mode=RuntimeMode.SIMULATION,
            operations=("not-an-operation",),  # type: ignore[arg-type]
            reason="Type test.",
        )


def test_authorization_enforces_disposition_invariants() -> None:
    approved = ExecutionAuthorization(
        authorization_id="authorization-1",
        proposal_id="proposal-1",
        evaluated_at=NOW,
        disposition=AuthorizationDisposition.AUTHORIZED,
        reason="Simulation proposal passed preflight.",
    )
    assert approved.authorized

    rejected = ExecutionAuthorization(
        authorization_id="authorization-2",
        proposal_id="proposal-2",
        evaluated_at=NOW,
        disposition=AuthorizationDisposition.REJECTED,
        reason="Physical delivery is prohibited.",
        blocking_reasons=("physical_endpoint_prohibited",),
    )
    assert not rejected.authorized

    with pytest.raises(ValueError, match="requires a blocking reason"):
        ExecutionAuthorization(
            authorization_id="authorization-3",
            proposal_id="proposal-3",
            evaluated_at=NOW,
            disposition=AuthorizationDisposition.REJECTED,
            reason="Rejected.",
        )


def test_execution_step_requires_verification_expectations() -> None:
    with pytest.raises(ValueError, match="expected observations"):
        ExecutionStep(
            step_id="step-1",
            sequence=1,
            operation=operation(),
        )

    no_verification = ExecutionStep(
        step_id="step-1",
        sequence=1,
        operation=operation(),
        verification_required=False,
    )
    assert not no_verification.verification_required


def test_execution_plan_requires_ordered_contiguous_unique_steps() -> None:
    first = step(step_id="step-1", sequence=1)
    second = ExecutionStep(
        step_id="step-2",
        sequence=2,
        operation=SetPumpSpeed(
            equipment_id="main-pump",
            rpm=1800,
            operation_id="op-2",
        ),
        expected_observations={"pump.main-pump.rpm": 1800},
    )
    plan = ExecutionPlan(
        plan_id="plan-1",
        proposal_id="proposal-1",
        authorization_id="authorization-1",
        decision_id="decision-1",
        context_id="context-1",
        created_at=NOW,
        steps=(first, second),
        expected_final_state={"pump.main-pump.rpm": 1800},
    )
    assert tuple(item.sequence for item in plan.steps) == (1, 2)

    with pytest.raises(ValueError, match="contiguous"):
        ExecutionPlan(
            plan_id="plan-2",
            proposal_id="proposal-1",
            authorization_id="authorization-1",
            decision_id="decision-1",
            context_id="context-1",
            created_at=NOW,
            steps=(first, step(step_id="step-3", sequence=3)),
        )


def test_step_outcome_separates_delivery_and_verification() -> None:
    delivered = StepOutcome(
        step_id="step-1",
        status=ExecutionLifecycleStatus.DELIVERED,
        verification_status=VerificationStatus.PENDING,
        started_at=NOW,
        receipt_ids=("receipt-1",),
    )
    assert delivered.status is ExecutionLifecycleStatus.DELIVERED
    assert delivered.verification_status is VerificationStatus.PENDING

    verified = StepOutcome(
        step_id="step-1",
        status=ExecutionLifecycleStatus.VERIFIED,
        verification_status=VerificationStatus.VERIFIED,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        receipt_ids=("receipt-1",),
    )
    assert verified.verification_status is VerificationStatus.VERIFIED


def test_execution_outcome_enforces_terminal_timestamps_and_failures() -> None:
    verified_step = StepOutcome(
        step_id="step-1",
        status=ExecutionLifecycleStatus.VERIFIED,
        verification_status=VerificationStatus.VERIFIED,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    outcome = ExecutionOutcome(
        outcome_id="outcome-1",
        plan_id="plan-1",
        proposal_id="proposal-1",
        decision_id="decision-1",
        context_id="context-1",
        status=ExecutionLifecycleStatus.VERIFIED,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        step_outcomes=(verified_step,),
    )
    assert outcome.status is ExecutionLifecycleStatus.VERIFIED

    with pytest.raises(ValueError, match="terminal outcomes require completed_at"):
        ExecutionOutcome(
            outcome_id="outcome-2",
            plan_id="plan-1",
            proposal_id="proposal-1",
            decision_id="decision-1",
            context_id="context-1",
            status=ExecutionLifecycleStatus.FAILED,
            started_at=NOW,
            failure_reason="Delivery failed.",
        )

    with pytest.raises(ValueError, match="failure outcomes require failure_reason"):
        ExecutionOutcome(
            outcome_id="outcome-3",
            plan_id="plan-1",
            proposal_id="proposal-1",
            decision_id="decision-1",
            context_id="context-1",
            status=ExecutionLifecycleStatus.ABORTED,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
        )


def test_all_execution_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionProposal(
            proposal_id="proposal-1",
            decision_id="decision-1",
            context_id="context-1",
            objective_id="objective-1",
            created_at=datetime(2026, 7, 31, 18, 0),
            runtime_mode=RuntimeMode.SIMULATION,
            operations=(operation(),),
            reason="Naive timestamp test.",
        )
