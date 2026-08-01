from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.operational_action_exchange import (
    OperationalActionExchange,
    OperationalActionExchangeReason,
    OperationalActionExchangeRequest,
    OperationalActionExchangeResult,
    OperationalActionExchangeStatus,
)
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from poolos.operational_action_registry import (
    OperationalActionRegistration,
    OperationalActionRegistry,
)
from poolos.operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
    OperationalReasonCode,
)
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalDispositionOrchestrator,
    OperationalTarget,
)


def _accepted_pipeline_result() -> OperationalActionPipelineResult:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        OperationalEvaluationResult(
            disposition=OperationalDisposition.SUBMIT_NEW_PLAN,
            reason_code=OperationalReasonCode.SELECTED_WITHOUT_PLAN,
            reason="Proposal required",
            context_id="context-1",
            decision_id="decision-1",
            diagnostics={"source": "test"},
        )
    )
    action = CanonicalOperationalAction.from_instruction(instruction)
    return OperationalActionPipeline().process(action)


def test_exchange_resolves_one_accepted_action_without_invocation() -> None:
    request = OperationalActionExchangeRequest(
        pipeline_result=_accepted_pipeline_result(),
        correlation_id="cycle-1",
    )

    result = OperationalActionExchange().exchange(request)

    assert result.status is OperationalActionExchangeStatus.READY
    assert result.reason is OperationalActionExchangeReason.DESTINATION_READY
    assert result.destination is OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY
    assert result.boundary_name == "execution_proposal_boundary"
    assert result.correlation_id == "cycle-1"
    assert result.action is request.pipeline_result.action


def test_exchange_id_is_deterministic() -> None:
    request = OperationalActionExchangeRequest(
        pipeline_result=_accepted_pipeline_result(),
        correlation_id="cycle-1",
    )
    exchange = OperationalActionExchange()

    first = exchange.exchange(request)
    second = exchange.exchange(request)

    assert first == second
    assert first.exchange_id.startswith("operational-exchange-")


def test_exchange_id_changes_with_correlation_identity() -> None:
    result = _accepted_pipeline_result()
    exchange = OperationalActionExchange()

    first = exchange.exchange(
        OperationalActionExchangeRequest(result, correlation_id="cycle-1")
    )
    second = exchange.exchange(
        OperationalActionExchangeRequest(result, correlation_id="cycle-2")
    )

    assert first.exchange_id != second.exchange_id


def test_exchange_rejects_pipeline_rejection() -> None:
    accepted = _accepted_pipeline_result()
    rejected = OperationalActionPipelineResult(
        status=OperationalActionPipelineStatus.REJECTED,
        reason=OperationalActionPipelineReason.UNSUPPORTED_ACTION,
        action=accepted.action,
        routed_target=OperationalTarget.NONE,
        accepted_action_ids=(),
    )

    result = OperationalActionExchange().exchange(
        OperationalActionExchangeRequest(rejected)
    )

    assert result.status is OperationalActionExchangeStatus.REJECTED
    assert result.reason is OperationalActionExchangeReason.PIPELINE_NOT_ACCEPTED
    assert result.destination is OperationalTarget.NONE
    assert result.boundary_name is None


def test_pipeline_invariant_rejects_missing_acceptance_evidence() -> None:
    accepted = _accepted_pipeline_result()

    with pytest.raises(ValueError, match="must record its action ID"):
        OperationalActionPipelineResult(
            status=OperationalActionPipelineStatus.ACCEPTED,
            reason=OperationalActionPipelineReason.ROUTE_ACCEPTED,
            action=accepted.action,
            routed_target=accepted.routed_target,
            accepted_action_ids=(),
        )


def test_exchange_rejects_action_missing_from_exchange_registry() -> None:
    exchange = OperationalActionExchange(
        registry=OperationalActionRegistry(registrations=())
    )

    result = exchange.exchange(
        OperationalActionExchangeRequest(_accepted_pipeline_result())
    )

    assert result.status is OperationalActionExchangeStatus.REJECTED
    assert result.reason is OperationalActionExchangeReason.UNSUPPORTED_ROUTE


def test_exchange_rejects_registry_target_conflict() -> None:
    accepted = _accepted_pipeline_result()
    conflicting_registry = OperationalActionRegistry(
        registrations=(
            OperationalActionRegistration(
                action=OperationalAction.REQUEST_PROPOSAL,
                target=OperationalTarget.OPERATOR_REVIEW,
                boundary_name="operator_review",
                description="Conflicting test route",
            ),
        )
    )

    result = OperationalActionExchange(conflicting_registry).exchange(
        OperationalActionExchangeRequest(accepted)
    )

    assert result.status is OperationalActionExchangeStatus.REJECTED
    assert result.reason is OperationalActionExchangeReason.ROUTE_TARGET_MISMATCH
    assert result.destination is OperationalTarget.NONE


def test_exchange_preserves_diagnostics() -> None:
    request = OperationalActionExchangeRequest(
        pipeline_result=_accepted_pipeline_result(),
        diagnostics={"exchange_source": "test"},
    )

    result = OperationalActionExchange().exchange(request)

    assert result.diagnostics["source"] == "test"
    assert result.diagnostics["exchange_source"] == "test"
    assert result.diagnostics["exchange_status"] == "ready"
    assert result.diagnostics["boundary_name"] == "execution_proposal_boundary"


def test_exchange_request_and_result_are_immutable() -> None:
    request = OperationalActionExchangeRequest(
        pipeline_result=_accepted_pipeline_result(),
        diagnostics={"source": "test"},
    )
    result = OperationalActionExchange().exchange(request)

    with pytest.raises(FrozenInstanceError):
        request.correlation_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.diagnostics["source"] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.status = OperationalActionExchangeStatus.REJECTED  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.diagnostics["exchange_status"] = "changed"  # type: ignore[index]


def test_ready_result_requires_boundary_name() -> None:
    action = _accepted_pipeline_result().action

    with pytest.raises(ValueError, match="requires a boundary name"):
        OperationalActionExchangeResult(
            exchange_id="exchange-1",
            status=OperationalActionExchangeStatus.READY,
            reason=OperationalActionExchangeReason.DESTINATION_READY,
            action=action,
            destination=action.target,
            boundary_name=None,
        )


def test_rejected_result_cannot_identify_destination() -> None:
    action = _accepted_pipeline_result().action

    with pytest.raises(ValueError, match="must not identify a destination"):
        OperationalActionExchangeResult(
            exchange_id="exchange-1",
            status=OperationalActionExchangeStatus.REJECTED,
            reason=OperationalActionExchangeReason.UNSUPPORTED_ROUTE,
            action=action,
            destination=OperationalTarget.OPERATOR_REVIEW,
            boundary_name=None,
        )
