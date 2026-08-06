"""Read-only shadow evaluation composition for operational commissioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from .alternative_ranking import AlternativeCandidate, AlternativeRankingEngine, RankingCriterion
from .bodies import Body
from .capabilities import Capability
from .clock import FixedClock
from .decision_flight_recorder import DecisionFlightRecord, InMemoryDecisionFlightRecorder
from .decision_orchestrator import (
    DecisionOrchestrationRequest,
    DecisionOrchestrationResult,
    DecisionOrchestrator,
)
from .decision_planning import DecisionPlanningRequest, ExplainablePlanner
from .enums import BodyType, EquipmentType
from .equipment import Equipment
from .evaluation_context import DecisionEvaluationContext, EvaluationRuntimeMode, EvaluationTrigger
from .kernel import PoolKernel
from .models import BodyState, TemperatureState
from .planning import ObjectiveType, PlanObjective
from .planning_strategies import build_default_planner


@dataclass(frozen=True, slots=True)
class ShadowRuntimeInput:
    """Minimal canonical facts used by the commissioning shadow runtime."""

    evaluated_at: datetime
    pool_temperature: float
    pool_active: bool
    pump_rpm: int
    observation_healthy: bool
    observation_fingerprint: str

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not 40.0 <= self.pool_temperature <= 110.0:
            raise ValueError("pool_temperature must be between 40 and 110")
        if self.pump_rpm < 0:
            raise ValueError("pump_rpm must not be negative")
        if not self.observation_fingerprint.strip():
            raise ValueError("observation_fingerprint must not be empty")


@dataclass(frozen=True, slots=True)
class ShadowRuntimeResult:
    """Immutable evidence from one non-actuating shadow evaluation."""

    evaluation_id: str
    evaluated_at: datetime
    status: str
    observation_fingerprint: str
    context_id: str
    plan_id: str | None
    objective_id: str
    proposed_step_count: int
    proposed_command_count: int
    summary: str
    human_explanation: str | None
    technical_explanation: str | None
    blocked_reasons: tuple[str, ...]

    @property
    def command_delivery_enabled(self) -> bool:
        return False

    def diagnostics(self) -> dict[str, Any]:
        """Return stable diagnostics without raw observed values."""

        return {
            "evaluation_id": self.evaluation_id,
            "evaluated_at": self.evaluated_at.isoformat(),
            "status": self.status,
            "observation_fingerprint": self.observation_fingerprint,
            "context_id": self.context_id,
            "plan_id": self.plan_id,
            "objective_id": self.objective_id,
            "proposed_step_count": self.proposed_step_count,
            "proposed_command_count": self.proposed_command_count,
            "summary": self.summary,
            "blocked_reasons": list(self.blocked_reasons),
            "command_delivery_enabled": False,
        }


class ShadowRuntime:
    """Compose the existing Decision Orchestrator for read-only commissioning."""

    def __init__(self) -> None:
        self._recorder = InMemoryDecisionFlightRecorder()
        self._orchestrator = DecisionOrchestrator(
            ExplainablePlanner(
                planner=build_default_planner(),
                ranking_engine=AlternativeRankingEngine(
                    (RankingCriterion("readiness", "Readiness", 1.0),)
                ),
                recorder=self._recorder,
            )
        )
        self._latest: ShadowRuntimeResult | None = None

    @property
    def latest(self) -> ShadowRuntimeResult | None:
        return self._latest

    @property
    def flight_records(self) -> tuple[DecisionFlightRecord, ...]:
        return self._recorder.records

    def evaluate(self, value: ShadowRuntimeInput) -> ShadowRuntimeResult:
        """Run one shadow-only evaluation; no execution boundary is invoked."""

        objective_id = f"shadow-baseline-{value.observation_fingerprint[:16]}"
        context_id = f"shadow-context-{value.observation_fingerprint[:16]}"
        objective = PlanObjective(
            objective_type=ObjectiveType.PREPARE_BODY_BY_DEADLINE,
            body_id="pool",
            target_temperature=value.pool_temperature,
            earliest_start=value.evaluated_at,
            deadline=value.evaluated_at + timedelta(minutes=30),
            requested_by="poolos-shadow-runtime",
            correlation_id=value.observation_fingerprint,
            objective_id=objective_id,
            metadata={"commissioning": "true", "authority": "none"},
        )
        blockers = () if value.observation_healthy else ("observation_unhealthy",)
        context = DecisionEvaluationContext(
            context_id=context_id,
            evaluated_at=value.evaluated_at,
            trigger=EvaluationTrigger.OBSERVATION_CHANGED,
            runtime_mode=EvaluationRuntimeMode.SHADOW,
            goals=(objective,),
            observation={
                "pool_active": value.pool_active,
                "pump_rpm": value.pump_rpm,
                "pool_temperature": value.pool_temperature,
                "observation_fingerprint": value.observation_fingerprint,
            },
            active_policy_ids=("commissioning_read_only",),
            freshness={
                "observation_snapshot": (
                    "fresh" if value.observation_healthy else "unhealthy"
                )
            },
            blockers=blockers,
            metadata={"source": "home_assistant_observation_bridge"},
        )
        planning = DecisionPlanningRequest(
            objective=objective,
            candidates=(
                AlternativeCandidate(
                    "maintain_observed_state",
                    "Maintain observed state",
                    {"readiness": 1.0},
                    reasons=("Commissioning baseline does not request a state change.",),
                ),
            ),
            summary="Shadow commissioning baseline evaluated without authority",
            next_change="Reevaluate when the observation snapshot changes.",
            confidence=1.0 if value.observation_healthy else 0.0,
            metadata={"authority": "none", "delivery": "disabled"},
        )
        orchestration = self._orchestrator.evaluate(
            DecisionOrchestrationRequest(context=context, planning=planning),
            _kernel(value),
        )
        result = _result(value, orchestration, objective_id)
        self._latest = result
        return result


def observation_fingerprint(*, generated_at: datetime, facts: dict[str, Any]) -> str:
    """Return a deterministic identity for one normalized observation snapshot."""

    payload = {"generated_at": generated_at.isoformat(), "facts": facts}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _kernel(value: ShadowRuntimeInput) -> PoolKernel:
    kernel = PoolKernel(clock=FixedClock(value.evaluated_at))
    kernel.bodies.register(Body("pool", "Pool", BodyType.POOL))
    kernel.equipment.register(
        Equipment(
            "pool_pump",
            "Pool Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            body=BodyType.POOL,
        )
    )
    kernel.equipment.register(
        Equipment(
            "pool_heater",
            "Pool Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            body=BodyType.POOL,
        )
    )
    kernel.update_body_state(
        "pool",
        BodyState(
            BodyType.POOL,
            TemperatureState(value.pool_temperature, value.pool_temperature, False),
            value.pool_active,
            False,
        ),
    )
    return kernel


def _result(
    value: ShadowRuntimeInput,
    orchestration: DecisionOrchestrationResult,
    objective_id: str,
) -> ShadowRuntimeResult:
    decision = orchestration.decision
    plan = None if decision is None else decision.plan
    step_count = 0 if plan is None else len(plan.steps)
    command_count = 0 if plan is None else sum(len(step.commands) for step in plan.steps)
    stable = {
        "observation_fingerprint": value.observation_fingerprint,
        "context_id": orchestration.context_id,
        "status": orchestration.status.value,
        "objective_id": objective_id,
        "step_count": step_count,
        "command_count": command_count,
    }
    evaluation_id = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ShadowRuntimeResult(
        evaluation_id=evaluation_id,
        evaluated_at=value.evaluated_at,
        status=orchestration.status.value,
        observation_fingerprint=value.observation_fingerprint,
        context_id=orchestration.context_id,
        plan_id=None if plan is None else plan.plan_id,
        objective_id=objective_id,
        proposed_step_count=step_count,
        proposed_command_count=command_count,
        summary=(
            "Shadow evaluation blocked by observation health."
            if decision is None
            else decision.explanation.summary
        ),
        human_explanation=None if decision is None else decision.human.text,
        technical_explanation=None if decision is None else decision.technical.text,
        blocked_reasons=tuple(orchestration.blockers),
    )
