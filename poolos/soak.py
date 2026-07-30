"""Accelerated multi-day simulation soak sessions and health summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .simulation import Simulation, SimulationResult, SimulationScenario


class SoakSessionStatus(str, Enum):
    """Lifecycle state for one deterministic simulation soak session."""

    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SoakHealth(str, Enum):
    """High-level health result derived from a completed soak run."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SoakTestPlan:
    """Validated repeatable plan for an accelerated simulation run."""

    name: str
    duration: timedelta
    step: timedelta = timedelta(minutes=5)
    maximum_unavailable_snapshots: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("soak plan name must not be empty")
        if self.duration.total_seconds() <= 0:
            raise ValueError("soak duration must be positive")
        if self.step.total_seconds() <= 0:
            raise ValueError("soak step must be positive")
        if self.maximum_unavailable_snapshots < 0:
            raise ValueError("maximum_unavailable_snapshots must not be negative")

    def scenario(self) -> SimulationScenario:
        return SimulationScenario(self.name, self.duration, step=self.step)


@dataclass(frozen=True, slots=True)
class SoakTestReport:
    """Immutable summary suitable for diagnostics and Home Assistant display."""

    plan_name: str
    started_at: datetime
    ended_at: datetime
    simulated_duration: timedelta
    snapshot_count: int
    applied_event_count: int
    unavailable_snapshot_count: int
    health: SoakHealth
    details: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(slots=True)
class SimulationSoakSession:
    """Run one simulation soak plan exactly once and retain its result."""

    simulation: Simulation
    plan: SoakTestPlan
    status: SoakSessionStatus = field(default=SoakSessionStatus.READY, init=False)
    result: SimulationResult | None = field(default=None, init=False)
    report: SoakTestReport | None = field(default=None, init=False)
    failure: str | None = field(default=None, init=False)

    def run(self) -> SoakTestReport:
        if self.status is not SoakSessionStatus.READY:
            raise RuntimeError("soak session may only be run once")
        self.status = SoakSessionStatus.RUNNING
        try:
            result = self.simulation.run_scenario(self.plan.scenario())
            report = self._build_report(result)
        except Exception as exc:
            self.status = SoakSessionStatus.FAILED
            self.failure = f"{type(exc).__name__}: {exc}"
            raise
        self.result = result
        self.report = report
        self.status = SoakSessionStatus.COMPLETED
        return report

    def _build_report(self, result: SimulationResult) -> SoakTestReport:
        unavailable = sum(
            1
            for snapshot in result.snapshots
            if not snapshot.grid_available
            or any(not state.available for state in snapshot.equipment.values())
        )
        health = (
            SoakHealth.HEALTHY
            if unavailable <= self.plan.maximum_unavailable_snapshots
            else SoakHealth.DEGRADED
        )
        return SoakTestReport(
            plan_name=self.plan.name,
            started_at=result.started_at,
            ended_at=result.ended_at,
            simulated_duration=result.ended_at - result.started_at,
            snapshot_count=len(result.snapshots),
            applied_event_count=len(result.applied_events),
            unavailable_snapshot_count=unavailable,
            health=health,
            details={
                "body_count": len(result.final.bodies),
                "equipment_count": len(result.final.equipment),
            },
        )


__all__ = [
    "SimulationSoakSession",
    "SoakHealth",
    "SoakSessionStatus",
    "SoakTestPlan",
    "SoakTestReport",
]
