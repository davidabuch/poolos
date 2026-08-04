"""Deterministic invocation of one assembled supervisory evaluation.

This boundary consumes immutable assembly evidence from Epic 10.15O and invokes
the existing :class:`DecisionOrchestrator` exactly once. It adds immutable
invocation identity and provenance without introducing another orchestrator,
queue, retry loop, persistence layer, execution path, or hardware operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .decision_orchestrator import (
    DecisionOrchestrationResult,
    DecisionOrchestrator,
    OrchestrationStatus,
)
from .evaluation_context import EvaluationRuntimeMode
from .kernel import PoolKernel
from .supervisory_evaluation_assembly import SupervisoryEvaluationAssemblyResult


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
class SupervisoryEvaluationInvocationRequest:
    """Immutable evidence required to invoke one assembled evaluation."""

    assembly: SupervisoryEvaluationAssemblyResult
    invoked_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.invoked_at, "invoked_at")
        if self.invoked_at < self.assembly.assembled_at:
            raise ValueError("invoked_at cannot precede assembled_at")
        if self.assembly.context.runtime_mode is not EvaluationRuntimeMode.SIMULATION:
            raise ValueError("supervisory evaluation invocation must remain simulation-only")
        orchestration_request = self.assembly.orchestration_request
        if orchestration_request.context is not self.assembly.context:
            raise ValueError("assembly orchestration request must use the assembled context")
        if self.assembly.coalescing_batch_id != self.assembly.provenance.get(
            "runtime_trigger_coalescing_batch_id"
        ):
            raise ValueError("assembly coalescing identity is inconsistent")
        if self.assembly.assembly_id != self.assembly.provenance.get(
            "supervisory_evaluation_assembly_id"
        ):
            raise ValueError("assembly identity is inconsistent")
        if self.assembly.context.context_id != self.assembly.provenance.get(
            "supervisory_evaluation_context_id"
        ):
            raise ValueError("assembly context identity is inconsistent")


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationInvocationResult:
    """Immutable evidence from one completed orchestrator invocation."""

    invocation_id: str
    invoked_at: datetime
    assembly_id: str
    coalescing_batch_id: str
    context_id: str
    orchestration: DecisionOrchestrationResult
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.invocation_id.strip():
            raise ValueError("invocation_id must not be empty")
        _require_aware(self.invoked_at, "invoked_at")
        if not self.assembly_id.strip():
            raise ValueError("assembly_id must not be empty")
        if not self.coalescing_batch_id.strip():
            raise ValueError("coalescing_batch_id must not be empty")
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        if self.orchestration.context_id != self.context_id:
            raise ValueError("orchestration result must match the assembled context")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def status(self) -> OrchestrationStatus:
        """Return the existing orchestration status without defining a parallel enum."""

        return self.orchestration.status


@dataclass(frozen=True, slots=True)
class SupervisoryEvaluationInvoker:
    """Invoke the existing Decision Orchestrator exactly once."""

    boundary_name: str = "poolos.supervisory_evaluation_invoker"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def invoke(
        self,
        request: SupervisoryEvaluationInvocationRequest,
        orchestrator: DecisionOrchestrator,
        kernel: PoolKernel,
    ) -> SupervisoryEvaluationInvocationResult:
        """Run one deterministic, simulator-only supervisory evaluation."""

        assembly = request.assembly
        invocation_id = _derived_id(
            "supervisory-evaluation-invocation-",
            {
                "boundary_name": self.boundary_name,
                "assembly_id": assembly.assembly_id,
                "coalescing_batch_id": assembly.coalescing_batch_id,
                "context_id": assembly.context.context_id,
            },
        )
        orchestration = orchestrator.evaluate(assembly.orchestration_request, kernel)
        if orchestration.context_id != assembly.context.context_id:
            raise ValueError("orchestrator returned a result for a different context")

        return SupervisoryEvaluationInvocationResult(
            invocation_id=invocation_id,
            invoked_at=request.invoked_at,
            assembly_id=assembly.assembly_id,
            coalescing_batch_id=assembly.coalescing_batch_id,
            context_id=assembly.context.context_id,
            orchestration=orchestration,
            provenance={
                **dict(assembly.provenance),
                "supervisory_evaluation_invocation_id": invocation_id,
                "supervisory_evaluation_invocation_boundary": self.boundary_name,
                "supervisory_evaluation_orchestration_status": orchestration.status.value,
            },
        )
