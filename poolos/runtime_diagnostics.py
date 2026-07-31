"""Command-free supervisory runtime diagnostics for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from .decision_orchestrator import DecisionOrchestrationResult, OrchestrationStatus
from .restart_recovery import RestartRecoveryResult


class SupervisoryRuntimeHealth(str, Enum):
    """High-level health derived from the latest supervisory evaluation."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class SupervisoryRuntimeSnapshot:
    """Immutable diagnostics snapshot for the command-free runtime."""

    evaluation_count: int
    last_evaluated_at: datetime
    last_trigger: str
    last_status: str
    runtime_mode: str
    context_id: str
    context_valid: bool
    decision_changed: bool
    active_decision_id: Optional[str]
    previous_decision_id: Optional[str]
    stability_disposition: Optional[str]
    restart_recovery_status: Optional[str]
    replay_status: Optional[str]
    next_reevaluation: Optional[datetime]
    health: SupervisoryRuntimeHealth
    blockers: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evaluation_count < 1:
            raise ValueError("evaluation_count must be positive")
        if self.last_evaluated_at.tzinfo is None:
            raise ValueError("last_evaluated_at must be timezone-aware")
        if self.next_reevaluation is not None and self.next_reevaluation.tzinfo is None:
            raise ValueError("next_reevaluation must be timezone-aware")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(slots=True)
class SupervisoryRuntimeMonitor:
    """Accumulate immutable diagnostics snapshots after evaluations."""

    _evaluation_count: int = field(default=0, init=False, repr=False)
    _latest: Optional[SupervisoryRuntimeSnapshot] = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def latest(self) -> Optional[SupervisoryRuntimeSnapshot]:
        return self._latest

    def observe(
        self,
        result: DecisionOrchestrationResult,
        *,
        evaluated_at: datetime,
        next_reevaluation: Optional[datetime] = None,
        restart_recovery: Optional[RestartRecoveryResult] = None,
        replay_status: Optional[str] = None,
    ) -> SupervisoryRuntimeSnapshot:
        """Create and retain diagnostics for one completed orchestrator invocation."""

        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        self._evaluation_count += 1
        previous_decision_id = result.diagnostics.get("previous_decision_id")
        if previous_decision_id == "none":
            previous_decision_id = None
        active_decision_id = (
            result.active_record.decision.decision_id
            if result.active_record is not None
            else None
        )
        decision_changed = bool(
            result.stability is not None and result.stability.decision_changed
        )
        stability_disposition = (
            result.stability.disposition.value if result.stability is not None else None
        )
        context_valid = result.status is not OrchestrationStatus.BLOCKED_CONTEXT
        if not context_valid:
            health = SupervisoryRuntimeHealth.BLOCKED
        elif result.active_record is None:
            health = SupervisoryRuntimeHealth.DEGRADED
        else:
            health = SupervisoryRuntimeHealth.HEALTHY
        snapshot = SupervisoryRuntimeSnapshot(
            evaluation_count=self._evaluation_count,
            last_evaluated_at=evaluated_at,
            last_trigger=result.trigger,
            last_status=result.status.value,
            runtime_mode=result.runtime_mode,
            context_id=result.context_id,
            context_valid=context_valid,
            decision_changed=decision_changed,
            active_decision_id=active_decision_id,
            previous_decision_id=previous_decision_id,
            stability_disposition=stability_disposition,
            restart_recovery_status=(
                restart_recovery.status.value if restart_recovery is not None else None
            ),
            replay_status=replay_status,
            next_reevaluation=next_reevaluation,
            health=health,
            blockers=result.blockers,
            diagnostics=result.diagnostics,
        )
        self._latest = snapshot
        return snapshot
