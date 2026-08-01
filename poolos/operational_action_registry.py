"""Declarative operational-action route registry for PoolOS.

The registry is the single command-free authority for mapping an
:class:`OperationalAction` to its logical downstream boundary.  It performs
immutable registration validation and deterministic lookup only.  It never
invokes a boundary, schedules work, mutates plans, authorizes execution,
delivers commands, or actuates equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .operational_disposition_orchestrator import OperationalAction, OperationalTarget


class OperationalActionRegistryStatus(str, Enum):
    """Outcome of one deterministic route lookup."""

    FOUND = "found"
    UNSUPPORTED = "unsupported"


class OperationalActionRegistryReason(str, Enum):
    """Stable machine-readable registry lookup reasons."""

    ROUTE_FOUND = "route_found"
    UNSUPPORTED_ACTION = "unsupported_action"


@dataclass(frozen=True, slots=True)
class OperationalActionRegistration:
    """Immutable declaration of one action-to-boundary route."""

    action: OperationalAction
    target: OperationalTarget
    boundary_name: str
    description: str

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if self.action is OperationalAction.NO_ACTION:
            if self.target is not OperationalTarget.NONE:
                raise ValueError("no-action registration must target none")
        elif self.target is OperationalTarget.NONE:
            raise ValueError("actionable registration must identify a target")


@dataclass(frozen=True, slots=True)
class OperationalActionRegistryResult:
    """Immutable result of one registry lookup."""

    status: OperationalActionRegistryStatus
    reason: OperationalActionRegistryReason
    action: OperationalAction
    registration: OperationalActionRegistration | None
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status is OperationalActionRegistryStatus.FOUND:
            if self.registration is None:
                raise ValueError("found result requires a registration")
            if self.registration.action is not self.action:
                raise ValueError("found registration must match the requested action")
        elif self.registration is not None:
            raise ValueError("unsupported result cannot contain a registration")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


_DEFAULT_REGISTRATIONS = (
    OperationalActionRegistration(
        action=OperationalAction.NO_ACTION,
        target=OperationalTarget.NONE,
        boundary_name="none",
        description="No downstream boundary is invoked.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.REQUEST_REEVALUATION,
        target=OperationalTarget.REEVALUATION_SCHEDULER,
        boundary_name="reevaluation_scheduler",
        description="Requests future decision reevaluation scheduling.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        boundary_name="execution_proposal_boundary",
        description="Requests construction of a new execution proposal.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.RETAIN_PLAN,
        target=OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        boundary_name="execution_plan_boundary",
        description="Retains the currently active execution plan.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.REQUEST_PLAN_CANCELLATION,
        target=OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        boundary_name="execution_plan_boundary",
        description="Requests cancellation of the identified execution plan.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.REQUEST_PLAN_REPLACEMENT,
        target=OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        boundary_name="execution_plan_boundary",
        description="Requests replacement of the identified execution plan.",
    ),
    OperationalActionRegistration(
        action=OperationalAction.HALT,
        target=OperationalTarget.OPERATOR_REVIEW,
        boundary_name="operator_review",
        description="Routes the blocked condition for operator review.",
    ),
)


@dataclass(frozen=True, slots=True)
class OperationalActionRegistry:
    """Immutable declarative registry of supported operational-action routes."""

    registrations: tuple[OperationalActionRegistration, ...] = _DEFAULT_REGISTRATIONS
    _by_action: Mapping[OperationalAction, OperationalActionRegistration] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        registrations = tuple(self.registrations)
        by_action: dict[OperationalAction, OperationalActionRegistration] = {}
        for registration in registrations:
            existing = by_action.get(registration.action)
            if existing is not None:
                if existing == registration:
                    raise ValueError(
                        f"duplicate registration for action {registration.action.value}"
                    )
                raise ValueError(
                    f"conflicting registration for action {registration.action.value}"
                )
            by_action[registration.action] = registration
        object.__setattr__(self, "registrations", registrations)
        object.__setattr__(self, "_by_action", MappingProxyType(by_action))

    @classmethod
    def default(cls) -> OperationalActionRegistry:
        """Return the canonical built-in registry."""

        return cls()

    def lookup(self, action: OperationalAction) -> OperationalActionRegistryResult:
        """Resolve one action without invoking the registered boundary."""

        registration = self._by_action.get(action)
        if registration is None:
            return OperationalActionRegistryResult(
                status=OperationalActionRegistryStatus.UNSUPPORTED,
                reason=OperationalActionRegistryReason.UNSUPPORTED_ACTION,
                action=action,
                registration=None,
                diagnostics={
                    "registry_status": OperationalActionRegistryStatus.UNSUPPORTED.value,
                    "registry_reason": OperationalActionRegistryReason.UNSUPPORTED_ACTION.value,
                    "operational_action": action.value,
                },
            )
        return OperationalActionRegistryResult(
            status=OperationalActionRegistryStatus.FOUND,
            reason=OperationalActionRegistryReason.ROUTE_FOUND,
            action=action,
            registration=registration,
            diagnostics={
                "registry_status": OperationalActionRegistryStatus.FOUND.value,
                "registry_reason": OperationalActionRegistryReason.ROUTE_FOUND.value,
                "operational_action": action.value,
                "operational_target": registration.target.value,
                "boundary_name": registration.boundary_name,
            },
        )
