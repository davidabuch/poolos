"""Deterministic operating-profile library layered above the PoolOS policy engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol

from .enums import PolicyPriority
from .exceptions import DuplicatePolicyError, UnknownPolicyError
from .kernel import PoolKernel
from .policies import Policy, PolicyContext, PolicyEngine, PolicyEvaluation


@dataclass(frozen=True, slots=True)
class ActivationDecision:
    """Result of evaluating whether an operating profile is applicable."""

    active: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("activation reason must not be empty")


class ActivationRule(Protocol):
    """Read-only condition used to activate an operating profile."""

    def evaluate(self, context: PolicyContext) -> ActivationDecision:
        ...


@dataclass(frozen=True, slots=True)
class AlwaysActive:
    reason: str = "profile is always active"

    def evaluate(self, context: PolicyContext) -> ActivationDecision:
        return ActivationDecision(True, self.reason)


@dataclass(frozen=True, slots=True)
class EquipmentAttributeEquals:
    """Activate when normalized equipment telemetry contains an exact value."""

    equipment_id: str
    attribute: str
    expected: object

    def __post_init__(self) -> None:
        if not self.equipment_id.strip() or not self.attribute.strip():
            raise ValueError("equipment_id and attribute must not be empty")

    def evaluate(self, context: PolicyContext) -> ActivationDecision:
        state = context.kernel.state.get_equipment(self.equipment_id)
        if state is None:
            return ActivationDecision(False, f"equipment {self.equipment_id!r} has no state")
        actual = state.attributes.get(self.attribute)
        active = actual == self.expected
        return ActivationDecision(
            active,
            f"{self.equipment_id}.{self.attribute} is {actual!r}; expected {self.expected!r}",
        )


@dataclass(frozen=True, slots=True)
class OperatingProfile:
    """Named reusable bundle of policies and its activation rule."""

    profile_id: str
    priority: PolicyPriority
    policies: tuple[Policy, ...]
    activation: ActivationRule = field(default_factory=AlwaysActive)
    description: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id must not be empty")
        if not self.policies:
            raise ValueError("operating profile requires at least one policy")
        ids = [policy.policy_id for policy in self.policies]
        if len(ids) != len(set(ids)):
            raise ValueError("policy ids must be unique within an operating profile")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ProfileActivation:
    profile_id: str
    priority: PolicyPriority
    decision: ActivationDecision


@dataclass(frozen=True, slots=True)
class PolicyLibraryEvaluation:
    """Selected profile, complete activation trace, and policy-engine result."""

    selected_profile_id: str | None
    activations: tuple[ProfileActivation, ...]
    policy_evaluation: PolicyEvaluation | None


@dataclass(slots=True)
class PolicyLibrary:
    """Register, select, and evaluate deterministic operating profiles.

    The highest-priority active profile wins. Registration order breaks ties.
    The selected profile is evaluated by a fresh ``PolicyEngine`` and no command
    is executed by this layer.
    """

    _profiles: dict[str, OperatingProfile] = field(default_factory=dict)

    def register(self, profile: OperatingProfile) -> None:
        if profile.profile_id in self._profiles:
            raise DuplicatePolicyError(f"profile already registered: {profile.profile_id}")
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> OperatingProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise UnknownPolicyError(profile_id) from exc

    def all(self) -> tuple[OperatingProfile, ...]:
        return tuple(self._profiles.values())

    def evaluate(self, kernel: PoolKernel) -> PolicyLibraryEvaluation:
        evaluated_at = kernel.clock.now()
        if evaluated_at.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")
        context = PolicyContext(kernel, evaluated_at)
        activations: list[ProfileActivation] = []
        selected: tuple[PolicyPriority, int, OperatingProfile] | None = None
        for order, profile in enumerate(self._profiles.values()):
            decision = profile.activation.evaluate(context)
            activations.append(ProfileActivation(profile.profile_id, profile.priority, decision))
            if not decision.active:
                continue
            candidate = (profile.priority, order, profile)
            if selected is None or candidate[0] > selected[0]:
                selected = candidate
        if selected is None:
            return PolicyLibraryEvaluation(None, tuple(activations), None)
        profile = selected[2]
        engine = PolicyEngine()
        for policy in profile.policies:
            engine.register(policy)
        return PolicyLibraryEvaluation(
            profile.profile_id,
            tuple(activations),
            engine.evaluate(kernel),
        )
