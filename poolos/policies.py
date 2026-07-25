"""Hardware-independent policy framework for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .commands import Command
from .enums import PolicyPriority
from .exceptions import DuplicatePolicyError, UnknownPolicyError
from .kernel import PoolKernel


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Read-only inputs supplied to a policy evaluation."""

    kernel: PoolKernel
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Commands and rationale proposed by one policy."""

    policy_id: str
    priority: PolicyPriority
    commands: tuple[Command, ...] = ()
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("policy_id must not be empty")


@dataclass(frozen=True, slots=True)
class PolicySuppression:
    """A command omitted because a higher-priority policy won the target."""

    command: Command
    winning_command: Command
    policy_id: str
    winning_policy_id: str


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """Complete result of one policy-engine pass."""

    evaluated_at: datetime
    outcomes: tuple[PolicyOutcome, ...]
    commands: tuple[Command, ...]
    suppressions: tuple[PolicySuppression, ...]


class Policy(Protocol):
    """Contract implemented by all PoolOS policies."""

    policy_id: str
    priority: PolicyPriority

    def evaluate(self, context: PolicyContext) -> PolicyOutcome:
        ...


@dataclass(slots=True)
class PolicyEngine:
    """Evaluate registered policies without executing their commands.

    Policies are evaluated in registration order. Conflicting commands for the
    same target are resolved by policy priority; an earlier registration wins a
    tie. The engine deliberately does not submit commands to the execution
    engine, preserving PoolOS's single execution path.
    """

    _policies: dict[str, Policy] = field(default_factory=dict)
    _disabled: set[str] = field(default_factory=set)

    def register(self, policy: Policy) -> None:
        if not policy.policy_id.strip():
            raise ValueError("policy_id must not be empty")
        if policy.policy_id in self._policies:
            raise DuplicatePolicyError(f"policy already registered: {policy.policy_id}")
        self._policies[policy.policy_id] = policy

    def get(self, policy_id: str) -> Policy:
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise UnknownPolicyError(policy_id) from exc

    def all(self) -> tuple[Policy, ...]:
        return tuple(self._policies.values())

    def enable(self, policy_id: str) -> None:
        self.get(policy_id)
        self._disabled.discard(policy_id)

    def disable(self, policy_id: str) -> None:
        self.get(policy_id)
        self._disabled.add(policy_id)

    def is_enabled(self, policy_id: str) -> bool:
        self.get(policy_id)
        return policy_id not in self._disabled

    def evaluate(self, kernel: PoolKernel) -> PolicyEvaluation:
        evaluated_at = kernel.clock.now()
        if evaluated_at.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")
        context = PolicyContext(kernel=kernel, evaluated_at=evaluated_at)
        outcomes: list[PolicyOutcome] = []
        winners: dict[str, tuple[PolicyPriority, int, str, Command]] = {}
        suppressions: list[PolicySuppression] = []

        for order, policy in enumerate(self._policies.values()):
            if policy.policy_id in self._disabled:
                continue
            outcome = policy.evaluate(context)
            if outcome.policy_id != policy.policy_id:
                raise ValueError(
                    f"policy outcome id {outcome.policy_id!r} does not match "
                    f"registered id {policy.policy_id!r}"
                )
            if outcome.priority != policy.priority:
                raise ValueError(
                    f"policy outcome priority for {policy.policy_id!r} does not "
                    "match the registered policy"
                )
            outcomes.append(outcome)

            seen_targets: set[str] = set()
            for command in outcome.commands:
                if command.target in seen_targets:
                    raise ValueError(
                        f"policy {policy.policy_id!r} produced multiple commands "
                        f"for target {command.target!r}"
                    )
                seen_targets.add(command.target)

                current = winners.get(command.target)
                candidate = (policy.priority, order, policy.policy_id, command)
                if current is None:
                    winners[command.target] = candidate
                    continue

                current_priority, current_order, current_policy_id, current_command = current
                candidate_wins = (
                    policy.priority > current_priority
                    or (
                        policy.priority == current_priority
                        and order < current_order
                    )
                )
                if candidate_wins:
                    suppressions.append(
                        PolicySuppression(
                            command=current_command,
                            winning_command=command,
                            policy_id=current_policy_id,
                            winning_policy_id=policy.policy_id,
                        )
                    )
                    winners[command.target] = candidate
                else:
                    suppressions.append(
                        PolicySuppression(
                            command=command,
                            winning_command=current_command,
                            policy_id=policy.policy_id,
                            winning_policy_id=current_policy_id,
                        )
                    )

        selected = tuple(item[3] for item in sorted(winners.values(), key=lambda item: item[1]))
        return PolicyEvaluation(
            evaluated_at=evaluated_at,
            outcomes=tuple(outcomes),
            commands=selected,
            suppressions=tuple(suppressions),
        )
