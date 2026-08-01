"""Deterministic, command-free operational-action exchange for PoolOS.

The exchange is the final immutable boundary between operational reasoning and
future downstream adapters.  It accepts one pipeline result, verifies that the
canonical action was accepted and that registry evidence remains consistent,
and returns one destination decision.  It never invokes the destination,
schedules work, creates proposals, mutates plans, authorizes execution,
delivers commands, or actuates equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from .operational_action_registry import (
    OperationalActionRegistry,
    OperationalActionRegistryStatus,
)
from .operational_disposition_orchestrator import OperationalTarget


class OperationalActionExchangeStatus(str, Enum):
    """Outcome of one command-free exchange evaluation."""

    READY = "ready"
    REJECTED = "rejected"


class OperationalActionExchangeReason(str, Enum):
    """Stable machine-readable exchange outcome reasons."""

    DESTINATION_READY = "destination_ready"
    PIPELINE_NOT_ACCEPTED = "pipeline_not_accepted"
    ACTION_ID_NOT_ACCEPTED = "action_id_not_accepted"
    UNSUPPORTED_ROUTE = "unsupported_route"
    ROUTE_TARGET_MISMATCH = "route_target_mismatch"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class OperationalActionExchangeRequest:
    """Immutable request to resolve one accepted operational action."""

    pipeline_result: OperationalActionPipelineResult
    correlation_id: str | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def action(self) -> CanonicalOperationalAction:
        """Return the canonical action carried by the pipeline result."""

        return self.pipeline_result.action


@dataclass(frozen=True, slots=True)
class OperationalActionExchangeResult:
    """Immutable destination decision produced by the exchange."""

    exchange_id: str
    status: OperationalActionExchangeStatus
    reason: OperationalActionExchangeReason
    action: CanonicalOperationalAction
    destination: OperationalTarget
    boundary_name: str | None
    correlation_id: str | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.exchange_id.strip():
            raise ValueError("exchange_id must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        if self.status is OperationalActionExchangeStatus.READY:
            if self.destination is OperationalTarget.NONE:
                if self.action.target is not OperationalTarget.NONE:
                    raise ValueError("ready actionable result must identify a destination")
            elif self.destination is not self.action.target:
                raise ValueError("ready result must preserve the canonical action target")
            if self.boundary_name is None or not self.boundary_name.strip():
                raise ValueError("ready result requires a boundary name")
        else:
            if self.destination is not OperationalTarget.NONE:
                raise ValueError("rejected result must not identify a destination")
            if self.boundary_name is not None:
                raise ValueError("rejected result must not identify a boundary name")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class OperationalActionExchange:
    """Resolve one accepted action to one logical destination without invoking it."""

    registry: OperationalActionRegistry = field(
        default_factory=OperationalActionRegistry.default
    )

    def exchange(
        self,
        request: OperationalActionExchangeRequest,
    ) -> OperationalActionExchangeResult:
        """Return one immutable destination decision with no external side effects."""

        pipeline_result = request.pipeline_result
        action = request.action

        if pipeline_result.status is not OperationalActionPipelineStatus.ACCEPTED:
            return self._result(
                request=request,
                status=OperationalActionExchangeStatus.REJECTED,
                reason=OperationalActionExchangeReason.PIPELINE_NOT_ACCEPTED,
                destination=OperationalTarget.NONE,
                boundary_name=None,
            )

        if action.action_id not in pipeline_result.accepted_action_ids:
            return self._result(
                request=request,
                status=OperationalActionExchangeStatus.REJECTED,
                reason=OperationalActionExchangeReason.ACTION_ID_NOT_ACCEPTED,
                destination=OperationalTarget.NONE,
                boundary_name=None,
            )

        registry_result = self.registry.lookup(action.action)
        if registry_result.status is OperationalActionRegistryStatus.UNSUPPORTED:
            return self._result(
                request=request,
                status=OperationalActionExchangeStatus.REJECTED,
                reason=OperationalActionExchangeReason.UNSUPPORTED_ROUTE,
                destination=OperationalTarget.NONE,
                boundary_name=None,
                registry_diagnostics=registry_result.diagnostics,
            )

        registration = registry_result.registration
        if registration is None:
            raise RuntimeError("found registry result must contain a registration")
        if (
            registration.target is not action.target
            or registration.target is not pipeline_result.routed_target
        ):
            return self._result(
                request=request,
                status=OperationalActionExchangeStatus.REJECTED,
                reason=OperationalActionExchangeReason.ROUTE_TARGET_MISMATCH,
                destination=OperationalTarget.NONE,
                boundary_name=None,
                registry_diagnostics=registry_result.diagnostics,
            )

        return self._result(
            request=request,
            status=OperationalActionExchangeStatus.READY,
            reason=OperationalActionExchangeReason.DESTINATION_READY,
            destination=registration.target,
            boundary_name=registration.boundary_name,
            registry_diagnostics=registry_result.diagnostics,
        )

    @staticmethod
    def _result(
        *,
        request: OperationalActionExchangeRequest,
        status: OperationalActionExchangeStatus,
        reason: OperationalActionExchangeReason,
        destination: OperationalTarget,
        boundary_name: str | None,
        registry_diagnostics: Mapping[str, str] | None = None,
    ) -> OperationalActionExchangeResult:
        action = request.action
        identity_payload = {
            "action_id": action.action_id,
            "boundary_name": boundary_name,
            "correlation_id": request.correlation_id,
            "destination": destination.value,
            "reason": reason.value,
            "status": status.value,
        }
        exchange_id = "operational-exchange-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        diagnostics = {
            **dict(action.diagnostics),
            **dict(request.pipeline_result.diagnostics),
            **dict(request.diagnostics),
            **dict(registry_diagnostics or {}),
            "operational_exchange_id": exchange_id,
            "exchange_status": status.value,
            "exchange_reason": reason.value,
            "exchange_destination": destination.value,
            "exchange_boundary_name": boundary_name or "none",
        }
        return OperationalActionExchangeResult(
            exchange_id=exchange_id,
            status=status,
            reason=reason,
            action=action,
            destination=destination,
            boundary_name=boundary_name,
            correlation_id=request.correlation_id,
            diagnostics=diagnostics,
        )
