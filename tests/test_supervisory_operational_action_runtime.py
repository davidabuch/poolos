from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import Mapping, cast

import pytest

from poolos.decision_orchestrator import DecisionOrchestrator
from poolos.downstream_operational_action_adapter import (
    DownstreamOperationalActionOutcome,
    DownstreamOperationalActionReason,
)
from poolos.kernel import PoolKernel
from poolos.operational_action_pipeline import (
    OperationalActionPipelineReason,
    OperationalActionPipelineStatus,
)
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalOrchestrationInstruction,
    OperationalTarget,
)
from poolos.supervisory_evaluation_runtime import (
    SupervisoryEvaluationRuntime,
    SupervisoryEvaluationRuntimeRequest,
)
from poolos.supervisory_operational_action_runtime import (
    SupervisoryOperationalActionRuntime,
)


@dataclass(frozen=True)
class _RuntimeResult:
    runtime_id: str
    operational_instruction: OperationalOrchestrationInstruction
    provenance: Mapping[str, str]


class _Runtime:
    def __init__(self, result: _RuntimeResult) -> None:
        self.result = result
        self.calls = 0

    def run(self, request, orchestrator, kernel):
        self.calls += 1
        return self.result


def _instruction(
    action: OperationalAction,
    target: OperationalTarget,
    disposition: OperationalDisposition,
    *,
    decision_id: str | None = None,
    plan_id: str | None = None,
    reevaluation_hint: str | None = None,
) -> OperationalOrchestrationInstruction:
    return OperationalOrchestrationInstruction(
        action=action,
        target=target,
        context_id="context-a",
        disposition=disposition,
        reason_code="test_reason",
        reason="Deterministic test instruction.",
        decision_id=decision_id,
        plan_id=plan_id,
        reevaluation_hint=reevaluation_hint,
        diagnostics={"source": "test"},
    )


def _compose(instruction: OperationalOrchestrationInstruction, **kwargs):
    upstream = _RuntimeResult(
        runtime_id="supervisory-runtime-a",
        operational_instruction=instruction,
        provenance={"supervisory_evaluation_runtime_id": "supervisory-runtime-a"},
    )
    runtime = _Runtime(upstream)
    composition = SupervisoryOperationalActionRuntime(
        supervisory_runtime=cast(SupervisoryEvaluationRuntime, runtime),
    )
    result = composition.run(
        cast(SupervisoryEvaluationRuntimeRequest, object()),
        cast(DecisionOrchestrator, object()),
        cast(PoolKernel, object()),
        **kwargs,
    )
    return result, runtime


def test_operator_review_route_completes_without_hardware() -> None:
    result, runtime = _compose(
        _instruction(
            OperationalAction.HALT,
            OperationalTarget.OPERATOR_REVIEW,
            OperationalDisposition.BLOCK,
        )
    )

    assert runtime.calls == 1
    assert result.pipeline.status is OperationalActionPipelineStatus.ACCEPTED
    assert result.receipt.outcome is DownstreamOperationalActionOutcome.ACCEPTED
    assert (
        result.receipt.reason
        is DownstreamOperationalActionReason.OPERATOR_REVIEW_ACCEPTED
    )


def test_no_action_route_returns_no_op_receipt() -> None:
    result, _ = _compose(
        _instruction(
            OperationalAction.NO_ACTION,
            OperationalTarget.NONE,
            OperationalDisposition.WAIT,
        )
    )

    assert result.receipt.outcome is DownstreamOperationalActionOutcome.NO_OP
    assert result.receipt.reason is DownstreamOperationalActionReason.NO_ACTION_REQUIRED


def test_reevaluation_route_is_deferred_not_scheduled() -> None:
    result, _ = _compose(
        _instruction(
            OperationalAction.REQUEST_REEVALUATION,
            OperationalTarget.REEVALUATION_SCHEDULER,
            OperationalDisposition.SCHEDULE_REEVALUATION,
            reevaluation_hint="after expected temperature change",
        )
    )

    assert result.receipt.outcome is DownstreamOperationalActionOutcome.DEFERRED
    assert (
        result.receipt.reason
        is DownstreamOperationalActionReason.REEVALUATION_DEFERRED
    )


def test_execution_proposal_route_is_rejected_by_non_hardware_adapter() -> None:
    result, _ = _compose(
        _instruction(
            OperationalAction.REQUEST_PROPOSAL,
            OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
            OperationalDisposition.SUBMIT_NEW_PLAN,
            decision_id="decision-a",
        )
    )

    assert result.pipeline.status is OperationalActionPipelineStatus.ACCEPTED
    assert result.receipt.outcome is DownstreamOperationalActionOutcome.REJECTED
    assert result.receipt.reason is DownstreamOperationalActionReason.UNSUPPORTED_TARGET


def test_duplicate_action_is_rejected_before_downstream_adaptation() -> None:
    instruction = _instruction(
        OperationalAction.HALT,
        OperationalTarget.OPERATOR_REVIEW,
        OperationalDisposition.BLOCK,
    )
    first, _ = _compose(instruction)
    second, _ = _compose(
        instruction,
        accepted_action_ids=(first.action.action_id,),
    )

    assert second.pipeline.status is OperationalActionPipelineStatus.REJECTED
    assert second.pipeline.reason is OperationalActionPipelineReason.DUPLICATE_ACTION_ID
    assert second.receipt.reason is DownstreamOperationalActionReason.PIPELINE_NOT_ACCEPTED


def test_identity_is_deterministic_for_same_evidence() -> None:
    instruction = _instruction(
        OperationalAction.HALT,
        OperationalTarget.OPERATOR_REVIEW,
        OperationalDisposition.BLOCK,
    )
    first, _ = _compose(instruction, correlation_id="correlation-a")
    second, _ = _compose(instruction, correlation_id="correlation-a")

    assert first.composition_id == second.composition_id
    assert first.action.action_id == second.action.action_id
    assert first.receipt.receipt_id == second.receipt.receipt_id


def test_provenance_preserves_every_boundary_identity() -> None:
    result, _ = _compose(
        _instruction(
            OperationalAction.HALT,
            OperationalTarget.OPERATOR_REVIEW,
            OperationalDisposition.BLOCK,
        )
    )

    assert result.provenance["supervisory_evaluation_runtime_id"] == (
        result.supervisory_runtime.runtime_id
    )
    assert result.provenance["canonical_operational_action_id"] == result.action.action_id
    assert result.provenance["downstream_operational_receipt_id"] == (
        result.receipt.receipt_id
    )


def test_result_and_provenance_are_immutable() -> None:
    result, _ = _compose(
        _instruction(
            OperationalAction.NO_ACTION,
            OperationalTarget.NONE,
            OperationalDisposition.WAIT,
        )
    )

    with pytest.raises(FrozenInstanceError):
        result.composition_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        SupervisoryOperationalActionRuntime(boundary_name="")
