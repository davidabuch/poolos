from dataclasses import replace

import pytest

from poolos.execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionLifecycleStatus,
    ExecutionPlan,
    ExecutionStep,
)
from poolos.execution_plans import (
    DeterministicExecutionPlanBuilder,
    ExecutionPlanBuildRequest,
    ExecutionStepSpecification,
    PlanBuildDisposition,
)
from poolos.integration import SetPumpSpeed, StartPump
from tests.test_execution_authorization import AUTHORIZATION_TIME, generated


def proposal_and_authorization():
    orchestration, proposal = generated()
    authorization = ExecutionAuthorization(
        authorization_id="authorization-10-13d",
        proposal_id=proposal.proposal_id,
        evaluated_at=AUTHORIZATION_TIME,
        disposition=AuthorizationDisposition.AUTHORIZED,
        reason="Simulation proposal passed authorization.",
    )
    return orchestration, proposal, authorization


def two_operation_proposal():
    orchestration, proposal, authorization = proposal_and_authorization()
    operations = (
        StartPump(equipment_id="pump", operation_id="operation-start"),
        SetPumpSpeed(
            equipment_id="pump",
            operation_id="operation-speed",
            rpm=1800,
        ),
    )
    return orchestration, replace(proposal, operations=operations), authorization


def specifications():
    return (
        ExecutionStepSpecification(
            operation_id="operation-speed",
            preconditions={"pump.running": True},
            expected_observations={"pump.rpm": 1800},
            metadata={"purpose": "set filtration speed"},
        ),
        ExecutionStepSpecification(
            operation_id="operation-start",
            preconditions={"hydraulics.route": "pool"},
            expected_observations={"pump.running": True},
        ),
    )


def test_builds_steps_in_proposal_order_not_specification_order() -> None:
    _, proposal, authorization = two_operation_proposal()

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=proposal,
            authorization=authorization,
            step_specifications=specifications(),
            metadata={"source": "test"},
        )
    )

    assert result.built
    assert result.disposition is PlanBuildDisposition.BUILT
    assert result.plan is not None
    assert [step.sequence for step in result.plan.steps] == [1, 2]
    assert [step.operation.operation_id for step in result.plan.steps] == [
        "operation-start",
        "operation-speed",
    ]
    assert result.plan.steps[0].preconditions["hydraulics.route"] == "pool"
    assert result.plan.steps[1].expected_observations["pump.rpm"] == 1800
    assert result.plan.metadata["source"] == "test"
    assert result.plan.expected_final_state == proposal.expected_final_state


def test_plan_generation_is_deterministic_for_same_request() -> None:
    _, proposal, authorization = two_operation_proposal()
    request = ExecutionPlanBuildRequest(
        proposal=proposal,
        authorization=authorization,
        step_specifications=specifications(),
    )
    builder = DeterministicExecutionPlanBuilder()

    first = builder.build(request)
    second = builder.build(request)

    assert first == second
    assert first.plan is not None
    assert first.plan.plan_id == second.plan.plan_id
    assert [step.step_id for step in first.plan.steps] == [
        f"{first.plan.plan_id}:step:1",
        f"{first.plan.plan_id}:step:2",
    ]


def test_rejects_non_authorized_disposition() -> None:
    _, proposal, authorization = two_operation_proposal()
    deferred = replace(
        authorization,
        disposition=AuthorizationDisposition.DEFERRED,
        reason="Deferred.",
        blocking_reasons=("safety_blocker:test",),
    )

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=proposal,
            authorization=deferred,
            step_specifications=specifications(),
        )
    )

    assert result.disposition is PlanBuildDisposition.REJECTED
    assert result.plan is None
    assert "authorization_not_authorized" in result.reasons


def test_rejects_authorization_for_different_proposal() -> None:
    _, proposal, authorization = two_operation_proposal()
    mismatched = replace(authorization, proposal_id="different-proposal")

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=proposal,
            authorization=mismatched,
            step_specifications=specifications(),
        )
    )

    assert "authorization_proposal_mismatch" in result.reasons


def test_rejects_missing_unknown_and_duplicate_specifications() -> None:
    _, proposal, authorization = two_operation_proposal()
    duplicate = ExecutionStepSpecification(
        operation_id="operation-start",
        expected_observations={"pump.running": True},
    )
    unknown = ExecutionStepSpecification(
        operation_id="operation-unknown",
        expected_observations={"unknown": True},
    )

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=proposal,
            authorization=authorization,
            step_specifications=(duplicate, duplicate, unknown),
        )
    )

    assert "duplicate_step_specification:operation-start" in result.reasons
    assert "missing_step_specification:operation-speed" in result.reasons
    assert "unknown_step_specification:operation-unknown" in result.reasons


def test_rejects_authorization_that_precedes_proposal() -> None:
    _, proposal, authorization = two_operation_proposal()
    invalid = replace(authorization, evaluated_at=proposal.created_at)
    future_proposal = replace(
        proposal,
        created_at=proposal.created_at.replace(microsecond=1),
    )

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=future_proposal,
            authorization=invalid,
            step_specifications=specifications(),
        )
    )

    assert "authorization_precedes_proposal" in result.reasons


def test_step_specification_requires_observations_when_verification_is_required() -> None:
    with pytest.raises(ValueError, match="expected observations"):
        ExecutionStepSpecification(operation_id="operation")

    specification = ExecutionStepSpecification(
        operation_id="operation",
        verification_required=False,
    )
    assert not specification.verification_required


def test_step_specification_is_immutable_and_requires_serializable_values() -> None:
    source = {"pump.running": False}
    specification = ExecutionStepSpecification(
        operation_id="operation",
        preconditions=source,
        expected_observations={"pump.running": True},
    )
    source["pump.running"] = True

    assert specification.preconditions["pump.running"] is False
    with pytest.raises(TypeError):
        specification.preconditions["new"] = True
    with pytest.raises(TypeError, match="JSON-serializable"):
        ExecutionStepSpecification(
            operation_id="operation",
            expected_observations={"unsupported": object()},
        )


def test_execution_step_freezes_preconditions() -> None:
    operation = StartPump(equipment_id="pump", operation_id="operation")
    source = {"route": "pool"}
    step = ExecutionStep(
        step_id="step",
        sequence=1,
        operation=operation,
        preconditions=source,
        expected_observations={"pump.running": True},
    )
    source["route"] = "spa"

    assert step.preconditions["route"] == "pool"
    with pytest.raises(TypeError):
        step.preconditions["route"] = "spa"


def test_execution_plan_rejects_invalid_step_ordering() -> None:
    operation = StartPump(equipment_id="pump", operation_id="operation")
    step = ExecutionStep(
        step_id="step",
        sequence=2,
        operation=operation,
        expected_observations={"pump.running": True},
    )

    with pytest.raises(ValueError, match="contiguous and ordered"):
        ExecutionPlan(
            plan_id="plan",
            proposal_id="proposal",
            authorization_id="authorization",
            decision_id="decision",
            context_id="context",
            created_at=AUTHORIZATION_TIME,
            steps=(step,),
            status=ExecutionLifecycleStatus.AUTHORIZED,
        )


def test_plan_builder_does_not_translate_or_deliver_operations() -> None:
    _, proposal, authorization = two_operation_proposal()

    result = DeterministicExecutionPlanBuilder().build(
        ExecutionPlanBuildRequest(
            proposal=proposal,
            authorization=authorization,
            step_specifications=specifications(),
        )
    )

    assert result.plan is not None
    assert result.plan.steps[0].operation is proposal.operations[0]
    assert result.plan.steps[1].operation is proposal.operations[1]
