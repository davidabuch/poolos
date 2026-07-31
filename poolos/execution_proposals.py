"""Command-free generation of execution proposals from accepted decisions.

The generator in this module is deliberately narrow. It consumes a completed
and recorded :class:`DecisionOrchestrationResult`, pairs it with canonical
:class:`PoolOperation` objects supplied by domain logic, and returns an
immutable :class:`ExecutionProposal`.

It does not authorize, plan, translate, deliver, or verify operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .decision_intelligence import DecisionOutcome
from .decision_orchestrator import (
    DecisionOrchestrationResult,
    OrchestrationStatus,
)
from .environment import RuntimeMode
from .execution_models import ExecutionProposal
from .integration import PoolOperation


class ProposalGenerationDisposition(str, Enum):
    """Result of evaluating whether an orchestration may create a proposal."""

    GENERATED = "generated"
    BLOCKED_CONTEXT = "blocked_context"
    RETAINED_DECISION = "retained_decision"
    NOT_ACTIONABLE = "not_actionable"
    UNRECORDED_DECISION = "unrecorded_decision"
    STALE_DECISION = "stale_decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionProposalRequest:
    """Inputs used to derive one proposal from one orchestration result.

    Operations are supplied explicitly because decision ranking remains
    policy-neutral and command-free. They must be canonical ``PoolOperation``
    objects; vendor commands and transport payloads are not accepted.
    """

    orchestration: DecisionOrchestrationResult
    operations: tuple[PoolOperation, ...] = ()
    reason: Optional[str] = None
    expected_final_state: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be empty when supplied")
        operations = tuple(self.operations)
        if any(not isinstance(operation, PoolOperation) for operation in operations):
            raise TypeError("operations must contain only PoolOperation instances")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(
            self,
            "expected_final_state",
            MappingProxyType(dict(self.expected_final_state)),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposalGenerationResult:
    """Immutable proposal-generation result, including non-actionable outcomes."""

    disposition: ProposalGenerationDisposition
    context_id: str
    decision_id: Optional[str] = None
    proposal: Optional[ExecutionProposal] = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.context_id.strip():
            raise ValueError("context_id must not be empty")
        if self.decision_id is not None and not self.decision_id.strip():
            raise ValueError("decision_id must not be empty when supplied")
        reasons = tuple(self.reasons)
        if any(not reason.strip() for reason in reasons):
            raise ValueError("reasons must not contain empty values")
        if self.disposition is ProposalGenerationDisposition.GENERATED:
            if self.proposal is None:
                raise ValueError("generated result requires a proposal")
            if reasons:
                raise ValueError("generated result cannot contain blocking reasons")
            if self.decision_id != self.proposal.decision_id:
                raise ValueError("result decision_id must match proposal decision_id")
            if self.context_id != self.proposal.context_id:
                raise ValueError("result context_id must match proposal context_id")
        else:
            if self.proposal is not None:
                raise ValueError("non-generated result cannot contain a proposal")
            if not reasons:
                raise ValueError("non-generated result requires at least one reason")
        object.__setattr__(self, "reasons", reasons)

    @property
    def generated(self) -> bool:
        """Return whether proposal generation succeeded."""

        return self.disposition is ProposalGenerationDisposition.GENERATED


@dataclass(frozen=True, slots=True)
class ExecutionProposalGenerator:
    """Generate deterministic execution proposals without performing execution."""

    proposal_id_prefix: str = "execution-proposal"

    def __post_init__(self) -> None:
        if not self.proposal_id_prefix.strip():
            raise ValueError("proposal_id_prefix must not be empty")

    @staticmethod
    def _result(
        *,
        disposition: ProposalGenerationDisposition,
        orchestration: DecisionOrchestrationResult,
        decision_id: Optional[str],
        reason: str,
    ) -> ProposalGenerationResult:
        return ProposalGenerationResult(
            disposition=disposition,
            context_id=orchestration.context_id,
            decision_id=decision_id,
            reasons=(reason,),
        )

    def generate(self, request: ExecutionProposalRequest) -> ProposalGenerationResult:
        """Return a proposal only for a current, changed, recorded selection."""

        orchestration = request.orchestration
        decision_result = orchestration.decision
        decision_id = (
            decision_result.explanation.decision_id
            if decision_result is not None
            else None
        )

        if orchestration.status is OrchestrationStatus.BLOCKED_CONTEXT:
            return self._result(
                disposition=ProposalGenerationDisposition.BLOCKED_CONTEXT,
                orchestration=orchestration,
                decision_id=decision_id,
                reason="Evaluation context blocked decision orchestration",
            )

        if orchestration.status is OrchestrationStatus.RETAINED:
            return self._result(
                disposition=ProposalGenerationDisposition.RETAINED_DECISION,
                orchestration=orchestration,
                decision_id=decision_id,
                reason="Retained decisions do not create duplicate proposals",
            )

        if decision_result is None or orchestration.stability is None:
            raise ValueError(
                "completed orchestration must include decision and stability"
            )

        decision = decision_result.explanation
        stability = orchestration.stability
        decision_id = decision.decision_id

        if not stability.decision_changed:
            return self._result(
                disposition=ProposalGenerationDisposition.RETAINED_DECISION,
                orchestration=orchestration,
                decision_id=decision_id,
                reason="Unchanged decisions do not create duplicate proposals",
            )

        if decision.outcome is not DecisionOutcome.SELECTED:
            return self._result(
                disposition=ProposalGenerationDisposition.NOT_ACTIONABLE,
                orchestration=orchestration,
                decision_id=decision_id,
                reason=f"Decision outcome {decision.outcome.value!r} is not executable",
            )

        active_record = orchestration.active_record
        flight_record = decision_result.flight_record
        if active_record is None or flight_record is None:
            return self._result(
                disposition=ProposalGenerationDisposition.UNRECORDED_DECISION,
                orchestration=orchestration,
                decision_id=decision_id,
                reason=(
                    "Executable decisions must be recorded before proposal generation"
                ),
            )

        current_ids = {
            active_record.decision.decision_id,
            flight_record.decision.decision_id,
            stability.active_decision_id,
        }
        recorded_context_id = decision.metadata.get("evaluation_context_id")
        if (
            current_ids != {decision_id}
            or active_record != flight_record
            or recorded_context_id != orchestration.context_id
        ):
            return self._result(
                disposition=ProposalGenerationDisposition.STALE_DECISION,
                orchestration=orchestration,
                decision_id=decision_id,
                reason="Decision is not the current accepted recorded decision",
            )

        if not request.operations:
            raise ValueError("actionable decisions require at least one PoolOperation")

        try:
            runtime_mode = RuntimeMode(orchestration.runtime_mode)
        except ValueError as exc:
            raise ValueError(
                "unsupported orchestration runtime mode: "
                f"{orchestration.runtime_mode!r}"
            ) from exc

        selected = decision.selected_alternative
        if selected is None:
            raise ValueError("selected decision must expose its selected alternative")

        proposal = ExecutionProposal(
            proposal_id=f"{self.proposal_id_prefix}:{decision_id}",
            decision_id=decision_id,
            context_id=orchestration.context_id,
            objective_id=active_record.objective_id,
            created_at=active_record.recorded_at,
            runtime_mode=runtime_mode,
            operations=request.operations,
            reason=request.reason or decision.summary,
            expected_final_state=request.expected_final_state,
            metadata={
                **dict(request.metadata),
                "selected_alternative_id": selected.alternative_id,
                "orchestration_status": orchestration.status.value,
                "stability_disposition": stability.disposition.value,
                "evaluation_trigger": orchestration.trigger,
            },
        )
        return ProposalGenerationResult(
            disposition=ProposalGenerationDisposition.GENERATED,
            context_id=orchestration.context_id,
            decision_id=decision_id,
            proposal=proposal,
        )
