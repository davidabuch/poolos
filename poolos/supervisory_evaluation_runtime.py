"""Composition of one complete command-free supervisory evaluation cycle.

Epic 10.15Q composes the existing input-assembly, invocation, operational
 disposition, and operational-routing boundaries. It introduces no new decision
logic, persistence, retries, queueing, execution, networking, vendor calls, or
physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .decision_orchestrator import DecisionOrchestrator
from .kernel import PoolKernel
from .operational_disposition import (
    OperationalDecisionSnapshot,
    OperationalDispositionEngine,
    OperationalEvaluationRequest,
    OperationalEvaluationResult,
    OperationalPlanSummary,
)
from .operational_disposition_orchestrator import (
    OperationalDispositionOrchestrator,
    OperationalOrchestrationInstruction,
)
from .supervisory_evaluation_assembly import (
    SupervisoryEvaluationAssemblyRequest,
    SupervisoryEvaluationAssemblyResult,
    SupervisoryEvaluationInputAssembler,
)
from .supervisory_evaluation_invocation import (
    SupervisoryEvaluationInvocationRequest,
    SupervisoryEvaluationInvocationResult,
    SupervisoryEvaluationInvoker,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _derived_id(prefix: str, payload: Mapping[str, str]) -> str:
    canonical = json.dumps(
        dict(sorted(payload.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationRuntimeRequest:
    """Inputs required to compose one complete supervisory evaluation cycle."""

    assembly_request: SupervisoryEvaluationAssemblyRequest
    invoked_at: datetime
    current_plan: OperationalPlanSummary | None = None

    def __post_init__(self) -> None:
        _require_aware(self.invoked_at, "invoked_at")
        if self.invoked_at < self.assembly_request.evaluated_at:
            raise ValueError("invoked_at cannot precede evaluated_at")


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationRuntimeResult:
    """Immutable evidence from one composed supervisory evaluation cycle."""

    runtime_id: str
    completed_at: datetime
    assembly: SupervisoryEvaluationAssemblyResult
    invocation: SupervisoryEvaluationInvocationResult
    operational_evaluation: OperationalEvaluationResult
    operational_instruction: OperationalOrchestrationInstruction
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.runtime_id.strip():
            raise ValueError("runtime_id must not be empty")
        _require_aware(self.completed_at, "completed_at")
        context_id = self.assembly.context.context_id
        if self.invocation.assembly_id != self.assembly.assembly_id:
            raise ValueError("invocation must match the runtime assembly")
        if self.invocation.context_id != context_id:
            raise ValueError("invocation must match the assembled context")
        if self.operational_evaluation.context_id != context_id:
            raise ValueError("operational evaluation must match the assembled context")
        if self.operational_instruction.context_id != context_id:
            raise ValueError("operational instruction must match the assembled context")
        if (
            self.operational_instruction.disposition
            is not self.operational_evaluation.disposition
        ):
            raise ValueError("operational instruction must match the disposition result")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationRuntime:
    """Compose existing deterministic supervisory boundaries exactly once."""

    assembler: SupervisoryEvaluationInputAssembler = field(
        default_factory=SupervisoryEvaluationInputAssembler
    )
    invoker: SupervisoryEvaluationInvoker = field(
        default_factory=SupervisoryEvaluationInvoker
    )
    disposition_engine: OperationalDispositionEngine = field(
        default_factory=OperationalDispositionEngine
    )
    disposition_orchestrator: OperationalDispositionOrchestrator = field(
        default_factory=OperationalDispositionOrchestrator
    )
    boundary_name: str = "poolos.supervisory_evaluation_runtime"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def run(
        self,
        request: SupervisoryEvaluationRuntimeRequest,
        orchestrator: DecisionOrchestrator,
        kernel: PoolKernel,
    ) -> SupervisoryEvaluationRuntimeResult:
        """Run one simulator-only supervisory cycle without downstream execution."""

        assembly = self.assembler.assemble(request.assembly_request)
        invocation = self.invoker.invoke(
            SupervisoryEvaluationInvocationRequest(
                assembly=assembly,
                invoked_at=request.invoked_at,
            ),
            orchestrator,
            kernel,
        )
        decision = OperationalDecisionSnapshot.from_orchestration(
            invocation.orchestration
        )
        operational_evaluation = self.disposition_engine.evaluate(
            OperationalEvaluationRequest(
                decision=decision,
                current_plan=request.current_plan,
            )
        )
        operational_instruction = self.disposition_orchestrator.orchestrate(
            operational_evaluation
        )

        context_id = assembly.context.context_id
        if invocation.context_id != context_id:
            raise ValueError("invocation context is inconsistent with assembly")
        if operational_evaluation.context_id != context_id:
            raise ValueError("operational disposition context is inconsistent")
        if operational_instruction.context_id != context_id:
            raise ValueError("operational instruction context is inconsistent")

        runtime_id = _derived_id(
            "supervisory-evaluation-runtime-",
            {
                "assembly_id": assembly.assembly_id,
                "boundary_name": self.boundary_name,
                "context_id": context_id,
                "invocation_id": invocation.invocation_id,
                "operational_action": operational_instruction.action.value,
                "operational_disposition": operational_evaluation.disposition.value,
                "operational_reason_code": operational_evaluation.reason_code.value,
                "operational_target": operational_instruction.target.value,
                "plan_id": operational_evaluation.plan_id or "none",
            },
        )
        return SupervisoryEvaluationRuntimeResult(
            runtime_id=runtime_id,
            completed_at=request.invoked_at,
            assembly=assembly,
            invocation=invocation,
            operational_evaluation=operational_evaluation,
            operational_instruction=operational_instruction,
            provenance={
                **dict(invocation.provenance),
                "supervisory_evaluation_runtime_id": runtime_id,
                "supervisory_evaluation_runtime_boundary": self.boundary_name,
                "operational_disposition": operational_evaluation.disposition.value,
                "operational_reason_code": operational_evaluation.reason_code.value,
                "operational_action": operational_instruction.action.value,
                "operational_target": operational_instruction.target.value,
            },
        )
