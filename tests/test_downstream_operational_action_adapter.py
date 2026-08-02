from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.downstream_operational_action_adapter import (
    DownstreamOperationalActionOutcome,
    DownstreamOperationalActionReason,
    NonHardwareOperationalActionAdapter,
)
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from poolos.operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
    OperationalReasonCode,
)
from poolos.operational_disposition_orchestrator import (
    OperationalDispositionOrchestrator,
    OperationalTarget,
)


def _evaluation(disposition: OperationalDisposition) -> OperationalEvaluationResult:
    reason_by_disposition = {
        OperationalDisposition.WAIT: OperationalReasonCode.NO_ACTION_REQUIRED,
        OperationalDisposition.SCHEDULE_REEVALUATION: (
            OperationalReasonCode.REEVALUATION_HINT_AVAILABLE
        ),
        OperationalDisposition.SUBMIT_NEW_PLAN: OperationalReasonCode.SELECTED_WITHOUT_PLAN,
        OperationalDisposition.BLOCK: OperationalReasonCode.DECISION_BLOCKED,
    }
    return OperationalEvaluationResult(
        disposition=disposition,
        reason_code=reason_by_disposition[disposition],
        reason=f"Test {disposition.value}",
        context_id="context-15h",
        decision_id="decision-15h",
        reevaluation_hint=(
            "forecast-window-2026-08-02T08:00:00Z"
            if disposition is OperationalDisposition.SCHEDULE_REEVALUATION
            else None
        ),
        diagnostics={"evaluation_source": "epic-10.15h-test"},
    )


def _pipeline_result(
    disposition: OperationalDisposition,
) -> OperationalActionPipelineResult:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        _evaluation(disposition)
    )
    action = CanonicalOperationalAction.from_instruction(
        instruction,
        correlation_id="cycle-15h",
    )
    return OperationalActionPipeline().process(action)


def test_operator_review_route_is_accepted() -> None:
    pipeline_result = _pipeline_result(OperationalDisposition.BLOCK)

    receipt = NonHardwareOperationalActionAdapter().adapt(pipeline_result)

    assert receipt.outcome is DownstreamOperationalActionOutcome.ACCEPTED
    assert receipt.reason is DownstreamOperationalActionReason.OPERATOR_REVIEW_ACCEPTED
    assert receipt.pipeline_result is pipeline_result
    assert receipt.pipeline_result.routed_target is OperationalTarget.OPERATOR_REVIEW
    assert receipt.pipeline_result.boundary_name == "operator_review"


def test_rejected_pipeline_result_is_rejected_without_downstream_routing() -> None:
    valid_action = _pipeline_result(OperationalDisposition.SUBMIT_NEW_PLAN).action
    invalid_action = CanonicalOperationalAction(
        action_id=valid_action.action_id,
        action=valid_action.action,
        target=OperationalTarget.OPERATOR_REVIEW,
        context_id=valid_action.context_id,
        disposition=valid_action.disposition,
        reason_code=valid_action.reason_code,
        reason=valid_action.reason,
        decision_id=valid_action.decision_id,
        correlation_id=valid_action.correlation_id,
        diagnostics=valid_action.diagnostics,
    )
    rejected_pipeline_result = OperationalActionPipeline().process(invalid_action)

    receipt = NonHardwareOperationalActionAdapter().adapt(rejected_pipeline_result)

    assert rejected_pipeline_result.status is OperationalActionPipelineStatus.REJECTED
    assert receipt.outcome is DownstreamOperationalActionOutcome.REJECTED
    assert receipt.reason is DownstreamOperationalActionReason.PIPELINE_NOT_ACCEPTED


def test_inconsistent_accepted_pipeline_evidence_is_rejected() -> None:
    valid = _pipeline_result(OperationalDisposition.BLOCK)
    inconsistent = OperationalActionPipelineResult(
        status=OperationalActionPipelineStatus.ACCEPTED,
        reason=OperationalActionPipelineReason.UNSUPPORTED_ACTION,
        action=valid.action,
        routed_target=valid.routed_target,
        boundary_name=valid.boundary_name,
        accepted_action_ids=valid.accepted_action_ids,
        diagnostics=valid.diagnostics,
    )

    receipt = NonHardwareOperationalActionAdapter().adapt(inconsistent)

    assert receipt.outcome is DownstreamOperationalActionOutcome.REJECTED
    assert receipt.reason is DownstreamOperationalActionReason.PIPELINE_EVIDENCE_INVALID


def test_no_action_produces_deterministic_no_op_receipt() -> None:
    pipeline_result = _pipeline_result(OperationalDisposition.WAIT)
    adapter = NonHardwareOperationalActionAdapter()

    first = adapter.adapt(pipeline_result)
    second = adapter.adapt(pipeline_result)

    assert first == second
    assert first.outcome is DownstreamOperationalActionOutcome.NO_OP
    assert first.reason is DownstreamOperationalActionReason.NO_ACTION_REQUIRED
    assert first.receipt_id.startswith("downstream-operational-receipt-")
    assert first.pipeline_result.routed_target is OperationalTarget.NONE


def test_reevaluation_route_is_deferred_with_hint_preserved() -> None:
    pipeline_result = _pipeline_result(
        OperationalDisposition.SCHEDULE_REEVALUATION
    )

    receipt = NonHardwareOperationalActionAdapter().adapt(pipeline_result)

    assert receipt.outcome is DownstreamOperationalActionOutcome.DEFERRED
    assert receipt.reason is DownstreamOperationalActionReason.REEVALUATION_DEFERRED
    assert receipt.pipeline_result.routed_target is OperationalTarget.REEVALUATION_SCHEDULER
    assert (
        receipt.pipeline_result.action.reevaluation_hint
        == "forecast-window-2026-08-02T08:00:00Z"
    )


def test_receipt_is_immutable_and_preserves_identity_and_provenance() -> None:
    pipeline_result = _pipeline_result(OperationalDisposition.BLOCK)

    receipt = NonHardwareOperationalActionAdapter().adapt(pipeline_result)

    assert receipt.action_id == pipeline_result.action.action_id
    assert receipt.context_id == "context-15h"
    assert receipt.decision_id == "decision-15h"
    assert receipt.plan_id is None
    assert receipt.correlation_id == "cycle-15h"
    assert receipt.provenance["source_action_id"] == receipt.action_id
    assert receipt.provenance["source_context_id"] == receipt.context_id
    assert receipt.provenance["source_decision_id"] == receipt.decision_id
    assert receipt.provenance["source_correlation_id"] == receipt.correlation_id
    assert receipt.provenance["evaluation_source"] == "epic-10.15h-test"
    with pytest.raises(FrozenInstanceError):
        receipt.receipt_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        receipt.provenance["source_action_id"] = "changed"  # type: ignore[index]


def test_first_adapter_has_no_execution_or_hardware_target() -> None:
    adapter = NonHardwareOperationalActionAdapter()
    execution_pipeline_result = _pipeline_result(
        OperationalDisposition.SUBMIT_NEW_PLAN
    )

    receipt = adapter.adapt(execution_pipeline_result)

    assert adapter.supported_targets == (
        OperationalTarget.NONE,
        OperationalTarget.REEVALUATION_SCHEDULER,
        OperationalTarget.OPERATOR_REVIEW,
    )
    assert OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY not in adapter.supported_targets
    assert OperationalTarget.EXECUTION_PLAN_BOUNDARY not in adapter.supported_targets
    assert receipt.outcome is DownstreamOperationalActionOutcome.REJECTED
    assert receipt.reason is DownstreamOperationalActionReason.UNSUPPORTED_TARGET
