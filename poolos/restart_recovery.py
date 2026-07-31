"""Restart recovery and deterministic replay for the PoolOS supervisory runtime."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Protocol

from .decision_flight_recorder import DecisionFlightRecord
from .decision_orchestrator import (
    DecisionOrchestrationRequest,
    DecisionOrchestrationResult,
    DecisionOrchestrator,
    OrchestrationStatus,
)
from .decision_planning import DecisionPlanningRequest
from .evaluation_context import DecisionEvaluationContext, EvaluationTrigger
from .kernel import PoolKernel


class DecisionHistory(Protocol):
    """Read-only history required during restart recovery."""

    @property
    def latest(self) -> Optional[DecisionFlightRecord]:
        ...


class RestartRecoveryStatus(str, Enum):
    """Outcome of one restart recovery evaluation."""

    INITIALIZED = "initialized"
    RETAINED = "retained"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RestartRecoveryRequest:
    """Current facts and planning inputs used after process restart."""

    context: DecisionEvaluationContext
    planning: DecisionPlanningRequest

    def __post_init__(self) -> None:
        if self.context.trigger is not EvaluationTrigger.RESTART_RECOVERY:
            raise ValueError("restart recovery context must use restart_recovery trigger")


@dataclass(frozen=True, slots=True)
class RestartRecoveryResult:
    """Command-free result of reconstructing supervisory decision state."""

    status: RestartRecoveryStatus
    orchestration: DecisionOrchestrationResult
    previous_record: Optional[DecisionFlightRecord]

    @property
    def active_record(self) -> Optional[DecisionFlightRecord]:
        """Return the decision record active after recovery."""

        return self.orchestration.active_record


@dataclass(frozen=True, slots=True)
class RestartRecoveryEngine:
    """Reevaluate current facts and retain or supersede prior history."""

    orchestrator: DecisionOrchestrator
    history: DecisionHistory

    def recover(
        self,
        request: RestartRecoveryRequest,
        kernel: PoolKernel,
    ) -> RestartRecoveryResult:
        """Recover supervisory state without restoring stale equipment intent."""

        previous = self.history.latest
        expected_previous = request.context.previous_decision_id
        if previous is None:
            if expected_previous is not None:
                raise ValueError("context references a previous decision but history is empty")
        elif expected_previous != previous.decision.decision_id:
            raise ValueError("restart context must reference the latest recorded decision")

        orchestration = self.orchestrator.evaluate(
            DecisionOrchestrationRequest(
                context=request.context,
                planning=request.planning,
                active_record=previous,
            ),
            kernel,
        )
        if orchestration.status is OrchestrationStatus.BLOCKED_CONTEXT:
            status = RestartRecoveryStatus.BLOCKED
        elif previous is None:
            status = RestartRecoveryStatus.INITIALIZED
        elif orchestration.status is OrchestrationStatus.RETAINED:
            status = RestartRecoveryStatus.RETAINED
        else:
            status = RestartRecoveryStatus.SUPERSEDED
        return RestartRecoveryResult(status, orchestration, previous)


@dataclass(frozen=True, slots=True)
class DecisionReplayExpectation:
    """Stable decision signature expected from one replay step."""

    outcome: str
    selected_alternative_id: Optional[str]
    stability_disposition: str
    orchestration_status: str

    @classmethod
    def from_result(
        cls,
        result: DecisionOrchestrationResult,
    ) -> "DecisionReplayExpectation":
        """Capture the deterministic signature of an orchestration result."""

        if result.decision is None or result.stability is None:
            raise ValueError("replay expectations require an evaluated decision")
        return cls(
            outcome=result.decision.explanation.outcome.value,
            selected_alternative_id=(
                result.decision.explanation.selected_alternative_id
            ),
            stability_disposition=result.stability.disposition.value,
            orchestration_status=result.status.value,
        )


@dataclass(frozen=True, slots=True)
class DecisionReplayStep:
    """One context and planning request in a deterministic replay scenario."""

    context: DecisionEvaluationContext
    planning: DecisionPlanningRequest
    expected: Optional[DecisionReplayExpectation] = None


@dataclass(frozen=True, slots=True)
class DecisionReplayResult:
    """Ordered command-free results from replaying recorded factual contexts."""

    results: tuple[DecisionOrchestrationResult, ...]
    verified: bool


@dataclass(frozen=True, slots=True)
class DecisionReplayEngine:
    """Replay contexts through the normal orchestrator without actuation."""

    orchestrator: DecisionOrchestrator

    def replay(
        self,
        steps: tuple[DecisionReplayStep, ...],
        kernels: tuple[PoolKernel, ...],
    ) -> DecisionReplayResult:
        """Replay ordered contexts and verify supplied deterministic signatures."""

        if len(steps) != len(kernels):
            raise ValueError("replay steps and kernels must have equal length")
        active_record: Optional[DecisionFlightRecord] = None
        results: list[DecisionOrchestrationResult] = []
        verified = True
        for step, kernel in zip(steps, kernels, strict=True):
            context = step.context
            if active_record is not None:
                if context.previous_decision_id is None:
                    raise ValueError(
                        "replay context must reference the prior active decision"
                    )
                context = replace(
                    context,
                    previous_decision_id=active_record.decision.decision_id,
                )
            elif context.previous_decision_id is not None:
                raise ValueError("first replay context cannot reference missing history")
            result = self.orchestrator.evaluate(
                DecisionOrchestrationRequest(
                    context=context,
                    planning=step.planning,
                    active_record=active_record,
                ),
                kernel,
            )
            if result.status is not OrchestrationStatus.BLOCKED_CONTEXT:
                active_record = result.active_record
            if step.expected is not None:
                verified = verified and (
                    DecisionReplayExpectation.from_result(result) == step.expected
                )
            results.append(result)
        return DecisionReplayResult(tuple(results), verified)
