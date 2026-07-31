"""Execution authorization and safety preflight for PoolOS.

This module evaluates immutable :class:`ExecutionProposal` objects against the
current recorded decision, frozen evaluation context, runtime environment, and
active safety blockers. It does not build plans, translate operations, or
deliver commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Optional

from .clock import Clock, SystemClock
from .decision_flight_recorder import DecisionFlightRecord
from .delivery import DeliveryEndpointKind
from .environment import PoolRuntimeEnvironment, RuntimeMode
from .evaluation_context import DecisionEvaluationContext
from .execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionProposal,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationRequest:
    """Current factual inputs for one proposal authorization evaluation."""

    proposal: ExecutionProposal
    active_record: Optional[DecisionFlightRecord]
    context: DecisionEvaluationContext
    environment: PoolRuntimeEnvironment
    current_context_id: str
    context_valid_until: Optional[datetime] = None
    safety_blockers: tuple[str, ...] = ()
    superseded_decision_ids: frozenset[str] = frozenset()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        current_context_id = self.current_context_id.strip()
        if not current_context_id:
            raise ValueError("current_context_id must not be empty")
        object.__setattr__(self, "current_context_id", current_context_id)

        if self.context_valid_until is not None:
            if self.context_valid_until.tzinfo is None:
                raise ValueError("context_valid_until must be timezone-aware")
            if self.context_valid_until < self.context.evaluated_at:
                raise ValueError(
                    "context_valid_until must not precede context evaluated_at"
                )

        blockers = tuple(self.safety_blockers)
        if any(not blocker.strip() for blocker in blockers):
            raise ValueError("safety blockers must not be empty")
        object.__setattr__(self, "safety_blockers", blockers)

        superseded = frozenset(self.superseded_decision_ids)
        if any(not decision_id.strip() for decision_id in superseded):
            raise ValueError("superseded decision IDs must not be empty")
        object.__setattr__(self, "superseded_decision_ids", superseded)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationEngine:
    """Authorize simulator-only proposals without performing execution."""

    clock: Clock = field(default_factory=SystemClock)
    authorization_id_prefix: str = "execution-authorization"

    def __post_init__(self) -> None:
        if not self.authorization_id_prefix.strip():
            raise ValueError("authorization_id_prefix must not be empty")

    def authorize(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorization:
        """Return an immutable authorization result for one proposal.

        Rejection takes precedence over deferral. Rejections represent broken
        identity, runtime, or physical-delivery safety invariants. Deferrals
        represent temporary conditions that may become eligible after a fresh
        evaluation, such as an active safety blocker or stale context.
        """

        evaluated_at = self.clock.now()
        if evaluated_at.tzinfo is None:
            raise ValueError("authorization clock must return timezone-aware values")

        proposal = request.proposal
        context = request.context
        environment = request.environment
        rejected: list[str] = []
        deferred: list[str] = []

        if proposal.created_at > evaluated_at:
            rejected.append("proposal_created_in_future")

        active_record = request.active_record
        if active_record is None:
            rejected.append("decision_not_recorded")
        else:
            if active_record.recorded_at > evaluated_at:
                rejected.append("decision_recorded_in_future")
            if active_record.decision.decision_id != proposal.decision_id:
                rejected.append("decision_not_current")
            if active_record.objective_id != proposal.objective_id:
                rejected.append("objective_mismatch")
            recorded_context_id = active_record.decision.metadata.get(
                "evaluation_context_id"
            )
            if recorded_context_id != proposal.context_id:
                rejected.append("recorded_context_mismatch")

        if proposal.decision_id in request.superseded_decision_ids:
            rejected.append("decision_superseded")

        if context.context_id != proposal.context_id:
            rejected.append("proposal_context_mismatch")
        if request.current_context_id != proposal.context_id:
            deferred.append("context_not_current")
        if context.previous_decision_id == proposal.decision_id:
            rejected.append("decision_superseded_by_context")
        if context.blockers:
            deferred.extend(f"context_blocker:{blocker}" for blocker in context.blockers)
        if (
            request.context_valid_until is not None
            and evaluated_at > request.context_valid_until
        ):
            deferred.append("context_expired")

        try:
            context_mode = RuntimeMode(context.runtime_mode.value)
        except ValueError:
            rejected.append("unsupported_context_runtime_mode")
        else:
            if context_mode is not proposal.runtime_mode:
                rejected.append("proposal_context_runtime_mismatch")

        if environment.mode is not proposal.runtime_mode:
            rejected.append("proposal_environment_runtime_mismatch")

        if proposal.runtime_mode is RuntimeMode.LIVE:
            rejected.append("live_runtime_prohibited")
        elif proposal.runtime_mode is RuntimeMode.SHADOW:
            deferred.append("shadow_runtime_not_executable")

        if environment.physical_delivery_allowed:
            rejected.append("physical_delivery_prohibited")

        for endpoint in environment.endpoints:
            if endpoint.delivery_kind is not DeliveryEndpointKind.SIMULATOR:
                rejected.append(
                    f"non_simulator_endpoint:{endpoint.endpoint_id}"
                )

        deferred.extend(
            f"safety_blocker:{blocker}" for blocker in request.safety_blockers
        )

        rejected_reasons = tuple(dict.fromkeys(rejected))
        deferred_reasons = tuple(dict.fromkeys(deferred))
        if rejected_reasons:
            disposition = AuthorizationDisposition.REJECTED
            blocking_reasons = rejected_reasons + deferred_reasons
            reason = "Execution proposal failed authorization safety preflight"
        elif deferred_reasons:
            disposition = AuthorizationDisposition.DEFERRED
            blocking_reasons = deferred_reasons
            reason = "Execution proposal authorization is temporarily deferred"
        else:
            disposition = AuthorizationDisposition.AUTHORIZED
            blocking_reasons = ()
            reason = "Simulation proposal passed execution authorization preflight"

        authorization_id = self._authorization_id(
            proposal_id=proposal.proposal_id,
            evaluated_at=evaluated_at,
            disposition=disposition,
            blocking_reasons=blocking_reasons,
        )
        metadata = {
            **dict(request.metadata),
            "runtime_mode": proposal.runtime_mode.value,
            "environment_installation_id": environment.installation_id,
            "context_trigger": context.trigger.value,
            "active_record_sequence": (
                str(active_record.sequence) if active_record is not None else "none"
            ),
            "endpoint_count": str(len(environment.endpoints)),
            "simulator_only": "true",
        }
        return ExecutionAuthorization(
            authorization_id=authorization_id,
            proposal_id=proposal.proposal_id,
            evaluated_at=evaluated_at,
            disposition=disposition,
            reason=reason,
            blocking_reasons=blocking_reasons,
            metadata=metadata,
        )

    def _authorization_id(
        self,
        *,
        proposal_id: str,
        evaluated_at: datetime,
        disposition: AuthorizationDisposition,
        blocking_reasons: tuple[str, ...],
    ) -> str:
        payload = "|".join(
            (
                proposal_id,
                evaluated_at.isoformat(),
                disposition.value,
                *blocking_reasons,
            )
        )
        digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"{self.authorization_id_prefix}:{proposal_id}:{digest}"
