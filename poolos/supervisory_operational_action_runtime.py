"""Compose supervisory evaluation with safe downstream operational adaptation.

Epic 10.16A connects the existing command-free supervisory evaluation runtime
to the canonical operational-action pipeline and the existing non-hardware
adapter boundary. It preserves deterministic identity and provenance while
performing no scheduling, execution-plan mutation, command delivery, network
operation, vendor call, Home Assistant call, or physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .decision_orchestrator import DecisionOrchestrator
from .downstream_operational_action_adapter import (
    DownstreamOperationalActionReceipt,
    NonHardwareOperationalActionAdapter,
)
from .kernel import PoolKernel
from .operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineResult,
)
from .supervisory_evaluation_runtime import (
    SupervisoryEvaluationRuntime,
    SupervisoryEvaluationRuntimeRequest,
    SupervisoryEvaluationRuntimeResult,
)


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = json.dumps(
        dict(sorted(payload.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class SupervisoryOperationalActionResult:
    """Immutable evidence from one supervisory-to-adapter composition cycle."""

    composition_id: str
    supervisory_runtime: SupervisoryEvaluationRuntimeResult
    action: CanonicalOperationalAction
    pipeline: OperationalActionPipelineResult
    receipt: DownstreamOperationalActionReceipt
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.composition_id.strip():
            raise ValueError("composition_id must not be empty")
        instruction = self.supervisory_runtime.operational_instruction
        if self.action.context_id != instruction.context_id:
            raise ValueError("canonical action must preserve the supervisory context")
        if self.action.action is not instruction.action:
            raise ValueError("canonical action must preserve the supervisory action")
        if self.action.target is not instruction.target:
            raise ValueError("canonical action must preserve the supervisory target")
        if self.pipeline.action is not self.action:
            raise ValueError("pipeline result must preserve the canonical action")
        if self.receipt.pipeline_result is not self.pipeline:
            raise ValueError("receipt must preserve the pipeline result")
        if self.receipt.context_id != instruction.context_id:
            raise ValueError("receipt must preserve the supervisory context")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class SupervisoryOperationalActionRuntime:
    """Compose existing supervisory, pipeline, and non-hardware boundaries."""

    supervisory_runtime: SupervisoryEvaluationRuntime = field(
        default_factory=SupervisoryEvaluationRuntime
    )
    action_pipeline: OperationalActionPipeline = field(
        default_factory=OperationalActionPipeline
    )
    downstream_adapter: NonHardwareOperationalActionAdapter = field(
        default_factory=NonHardwareOperationalActionAdapter
    )
    boundary_name: str = "poolos.supervisory_operational_action_runtime"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def run(
        self,
        request: SupervisoryEvaluationRuntimeRequest,
        orchestrator: DecisionOrchestrator,
        kernel: PoolKernel,
        *,
        accepted_action_ids: tuple[str, ...] = (),
        correlation_id: str | None = None,
    ) -> SupervisoryOperationalActionResult:
        """Run one deterministic non-actuating downstream composition cycle."""

        supervisory = self.supervisory_runtime.run(request, orchestrator, kernel)
        action = CanonicalOperationalAction.from_instruction(
            supervisory.operational_instruction,
            correlation_id=correlation_id,
        )
        pipeline = self.action_pipeline.process(
            action,
            accepted_action_ids=accepted_action_ids,
        )
        receipt = self.downstream_adapter.adapt(pipeline)

        composition_id = _derived_id(
            "supervisory-operational-action-runtime-",
            {
                "action_id": action.action_id,
                "boundary_name": self.boundary_name,
                "pipeline_boundary": pipeline.boundary_name or "none",
                "pipeline_reason": pipeline.reason.value,
                "pipeline_status": pipeline.status.value,
                "receipt_id": receipt.receipt_id,
                "receipt_outcome": receipt.outcome.value,
                "receipt_reason": receipt.reason.value,
                "supervisory_runtime_id": supervisory.runtime_id,
            },
        )
        provenance = {
            **dict(supervisory.provenance),
            **dict(pipeline.diagnostics),
            **dict(receipt.provenance),
            "supervisory_operational_action_runtime_id": composition_id,
            "supervisory_operational_action_runtime_boundary": self.boundary_name,
            "canonical_operational_action_id": action.action_id,
            "downstream_operational_receipt_id": receipt.receipt_id,
        }
        return SupervisoryOperationalActionResult(
            composition_id=composition_id,
            supervisory_runtime=supervisory,
            action=action,
            pipeline=pipeline,
            receipt=receipt,
            provenance=provenance,
        )
