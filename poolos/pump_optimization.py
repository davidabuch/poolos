"""Deterministic pump-operation optimization for selected operational intents.

This module recommends a pump RPM from explicit installation policy and selected
operational intents. It does not create commands, call Home Assistant, or actuate
equipment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .operational_intent import OperationalIntent, OperationalIntentType


class PumpOptimizationDisposition(str, Enum):
    RECOMMENDED = "recommended"
    NO_OPERATION_REQUIRED = "no_operation_required"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True, slots=True)
class PumpOptimizationPolicy:
    """Installation-specific RPM envelope and minimums for operational purposes."""

    minimum_rpm: int
    maximum_rpm: int
    rpm_step: int
    intent_minimum_rpm: Mapping[OperationalIntentType, int]

    def __post_init__(self) -> None:
        if self.minimum_rpm <= 0:
            raise ValueError("minimum_rpm must be positive")
        if self.maximum_rpm < self.minimum_rpm:
            raise ValueError("maximum_rpm must be at least minimum_rpm")
        if self.rpm_step <= 0:
            raise ValueError("rpm_step must be positive")
        normalized = dict(self.intent_minimum_rpm)
        for intent_type, rpm in normalized.items():
            if rpm <= 0:
                raise ValueError(f"minimum RPM for {intent_type.value} must be positive")
        object.__setattr__(self, "intent_minimum_rpm", MappingProxyType(normalized))

    def candidates(self) -> tuple[int, ...]:
        values = list(range(self.minimum_rpm, self.maximum_rpm + 1, self.rpm_step))
        if not values or values[-1] != self.maximum_rpm:
            values.append(self.maximum_rpm)
        return tuple(values)


@dataclass(frozen=True, slots=True)
class PumpCandidateEvaluation:
    rpm: int
    feasible: bool
    energy_index: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PumpOptimizationResult:
    disposition: PumpOptimizationDisposition
    recommended_rpm: int | None
    required_minimum_rpm: int | None
    permitted_maximum_rpm: int | None
    selected_intent_ids: tuple[str, ...]
    candidates: tuple[PumpCandidateEvaluation, ...]
    rationale: tuple[str, ...]

    def explain(self) -> tuple[str, ...]:
        return self.rationale


class PumpOperationOptimizer:
    """Choose the lowest-energy feasible RPM for already-arbitrated intents."""

    def __init__(self, policy: PumpOptimizationPolicy) -> None:
        self._policy = policy

    @staticmethod
    def _criterion_rpm(intent: OperationalIntent, code: str) -> tuple[int, ...]:
        values: list[int] = []
        for criterion in intent.constraints:
            if criterion.code != code:
                continue
            raw = criterion.parameters.get("rpm")
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError(f"{code} criterion requires integer rpm")
            if raw <= 0:
                raise ValueError(f"{code} criterion rpm must be positive")
            values.append(raw)
        return tuple(values)

    def optimize(self, selected_intents: tuple[OperationalIntent, ...]) -> PumpOptimizationResult:
        if len({intent.intent_id for intent in selected_intents}) != len(selected_intents):
            raise ValueError("duplicate selected intent identities are not allowed")

        selected_ids = tuple(intent.intent_id for intent in selected_intents)
        policy_requirements = tuple(
            self._policy.intent_minimum_rpm[intent.intent_type]
            for intent in selected_intents
            if intent.intent_type in self._policy.intent_minimum_rpm
        )
        explicit_minima = tuple(
            rpm
            for intent in selected_intents
            for rpm in self._criterion_rpm(intent, "minimum_pump_rpm")
        )
        explicit_maxima = tuple(
            rpm
            for intent in selected_intents
            for rpm in self._criterion_rpm(intent, "maximum_pump_rpm")
        )

        if not policy_requirements and not explicit_minima:
            return PumpOptimizationResult(
                disposition=PumpOptimizationDisposition.NO_OPERATION_REQUIRED,
                recommended_rpm=None,
                required_minimum_rpm=None,
                permitted_maximum_rpm=None,
                selected_intent_ids=selected_ids,
                candidates=(),
                rationale=("Selected intents impose no pump-operation requirement.",),
            )

        required_minimum = max(
            (self._policy.minimum_rpm, *policy_requirements, *explicit_minima)
        )
        permitted_maximum = min((self._policy.maximum_rpm, *explicit_maxima))
        candidates = tuple(
            PumpCandidateEvaluation(
                rpm=rpm,
                feasible=required_minimum <= rpm <= permitted_maximum,
                energy_index=rpm**3,
                reasons=(
                    "RPM satisfies the effective pump operating envelope."
                    if required_minimum <= rpm <= permitted_maximum
                    else "RPM is outside the effective pump operating envelope."
                ,),
            )
            for rpm in self._policy.candidates()
        )
        feasible = tuple(candidate for candidate in candidates if candidate.feasible)
        if not feasible:
            return PumpOptimizationResult(
                disposition=PumpOptimizationDisposition.INFEASIBLE,
                recommended_rpm=None,
                required_minimum_rpm=required_minimum,
                permitted_maximum_rpm=permitted_maximum,
                selected_intent_ids=selected_ids,
                candidates=candidates,
                rationale=(
                    f"No configured pump RPM satisfies {required_minimum}-{permitted_maximum} RPM.",
                    "No command or fallback RPM was produced.",
                ),
            )

        winner = min(feasible, key=lambda candidate: (candidate.energy_index, candidate.rpm))
        return PumpOptimizationResult(
            disposition=PumpOptimizationDisposition.RECOMMENDED,
            recommended_rpm=winner.rpm,
            required_minimum_rpm=required_minimum,
            permitted_maximum_rpm=permitted_maximum,
            selected_intent_ids=selected_ids,
            candidates=candidates,
            rationale=(
                f"Effective pump envelope is {required_minimum}-{permitted_maximum} RPM.",
                f"Selected {winner.rpm} RPM as the lowest-energy feasible configured candidate.",
            ),
        )
