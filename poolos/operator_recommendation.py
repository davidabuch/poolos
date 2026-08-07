"""Canonical read-only operator recommendations for PoolOS.

Recommendations translate already-selected operational intents and a completed
pump optimization result into explainable operator-facing evidence. They are not
commands, execution requests, or authority to actuate equipment.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from .operational_intent import OperationalIntent
from .pump_optimization import PumpOptimizationDisposition, PumpOptimizationResult


class OperatorRecommendationStatus(str, Enum):
    RECOMMENDED = "recommended"
    NO_ACTION = "no_action"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class OperatorRecommendation:
    recommendation_id: str
    status: OperatorRecommendationStatus
    summary: str
    recommended_pump_rpm: int | None
    selected_intent_ids: tuple[str, ...]
    rationale: tuple[str, ...]
    constraints: tuple[str, ...]
    expected_effect: str
    confidence: str = "deterministic"

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "status": self.status.value,
            "summary": self.summary,
            "recommended_pump_rpm": self.recommended_pump_rpm,
            "selected_intent_ids": list(self.selected_intent_ids),
            "rationale": list(self.rationale),
            "constraints": list(self.constraints),
            "expected_effect": self.expected_effect,
            "confidence": self.confidence,
            "authority": "none",
            "command_delivery_enabled": False,
        }


class OperatorRecommendationBuilder:
    """Build deterministic operator-facing evidence from optimization output."""

    @staticmethod
    def _identity(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "rec_" + sha256(canonical.encode()).hexdigest()[:20]

    def build(
        self,
        selected_intents: tuple[OperationalIntent, ...],
        optimization: PumpOptimizationResult,
    ) -> OperatorRecommendation:
        ids = tuple(intent.intent_id for intent in selected_intents)
        if ids != optimization.selected_intent_ids:
            raise ValueError("optimization provenance does not match selected intents")

        constraints: list[str] = []
        if optimization.required_minimum_rpm is not None:
            constraints.append(f"Minimum required pump speed: {optimization.required_minimum_rpm} RPM.")
        if optimization.permitted_maximum_rpm is not None:
            constraints.append(f"Maximum permitted pump speed: {optimization.permitted_maximum_rpm} RPM.")

        if optimization.disposition is PumpOptimizationDisposition.RECOMMENDED:
            status = OperatorRecommendationStatus.RECOMMENDED
            rpm = optimization.recommended_rpm
            summary = f"Recommend pump operation at {rpm} RPM."
            effect = "Satisfy the selected pump-related operational intents at the lowest feasible configured RPM."
        elif optimization.disposition is PumpOptimizationDisposition.NO_OPERATION_REQUIRED:
            status = OperatorRecommendationStatus.NO_ACTION
            rpm = None
            summary = "No pump-operation change is recommended."
            effect = "Preserve current pump operation because the selected intents impose no pump-speed requirement."
        else:
            status = OperatorRecommendationStatus.BLOCKED
            rpm = None
            summary = "No safe pump recommendation is available."
            effect = "Avoid proposing a pump speed because the selected requirements are infeasible."

        rationale = tuple(optimization.explain())
        identity_payload: dict[str, object] = {
            "status": status.value,
            "summary": summary,
            "recommended_pump_rpm": rpm,
            "selected_intent_ids": ids,
            "rationale": rationale,
            "constraints": tuple(constraints),
            "expected_effect": effect,
        }
        return OperatorRecommendation(
            recommendation_id=self._identity(identity_payload),
            status=status,
            summary=summary,
            recommended_pump_rpm=rpm,
            selected_intent_ids=ids,
            rationale=rationale,
            constraints=tuple(constraints),
            expected_effect=effect,
        )
