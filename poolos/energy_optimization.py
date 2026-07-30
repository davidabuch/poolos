"""Deterministic energy and cost optimization for PoolOS goals."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from .goal_planner import BodyReadyGoal, GoalPlanResult, GoalPlanner
from .kernel import PoolKernel


class EnergySource(str, Enum):
    """Energy sources represented by optimization candidates."""

    GRID = "grid"
    SOLAR = "solar"
    BATTERY = "battery"
    HYBRID = "hybrid"


class OptimizationStatus(str, Enum):
    """Outcome of deterministic candidate selection."""

    OPTIMIZED = "optimized"
    BEST_EFFORT = "best_effort"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True, slots=True)
class TariffWindow:
    """A time-bounded electricity price window."""

    start: datetime
    end: datetime
    price_per_kwh: float
    label: str = "grid"

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("tariff window times must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("tariff window end must be after start")
        if self.price_per_kwh < 0:
            raise ValueError("price_per_kwh must not be negative")


@dataclass(frozen=True, slots=True)
class EnergyStrategy:
    """One deterministic way to satisfy a heating goal."""

    strategy_id: str
    source: EnergySource
    power_kw: float
    start: datetime
    end: datetime
    grid_fraction: float = 1.0
    solar_fraction: float = 0.0
    battery_fraction: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("strategy times must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("strategy end must be after start")
        if self.power_kw <= 0:
            raise ValueError("power_kw must be positive")
        fractions = (self.grid_fraction, self.solar_fraction, self.battery_fraction)
        if any(value < 0 or value > 1 for value in fractions):
            raise ValueError("energy fractions must be between 0 and 1")
        if abs(sum(fractions) - 1.0) > 1e-9:
            raise ValueError("energy fractions must sum to 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def energy_kwh(self) -> float:
        return self.power_kw * self.duration.total_seconds() / 3600.0


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Cost and feasibility calculation for one strategy."""

    strategy: EnergyStrategy
    feasible: bool
    estimated_cost: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Traceable selection from all energy strategy candidates."""

    status: OptimizationStatus
    selected: Optional[CandidateEvaluation]
    candidates: tuple[CandidateEvaluation, ...]
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OptimizedGoalPlanResult:
    """Link an energy optimization result to the canonical goal plan."""

    original_goal: BodyReadyGoal
    optimized_goal: BodyReadyGoal
    optimization: OptimizationResult
    goal_plan: GoalPlanResult


@dataclass(frozen=True, slots=True)
class EnergyCostOptimizer:
    """Select the least-cost feasible strategy using explicit energy facts."""

    tariffs: tuple[TariffWindow, ...]
    solar_value_per_kwh: float = 0.0
    battery_degradation_per_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.solar_value_per_kwh < 0:
            raise ValueError("solar_value_per_kwh must not be negative")
        if self.battery_degradation_per_kwh < 0:
            raise ValueError("battery_degradation_per_kwh must not be negative")

    def _grid_cost(self, strategy: EnergyStrategy) -> tuple[float, bool]:
        grid_energy = strategy.energy_kwh * strategy.grid_fraction
        if grid_energy == 0:
            return 0.0, True
        for window in self.tariffs:
            if window.start <= strategy.start and strategy.end <= window.end:
                return grid_energy * window.price_per_kwh, True
        return 0.0, False

    def evaluate(
        self,
        strategy: EnergyStrategy,
        *,
        earliest_start: datetime,
        deadline: datetime,
        required_duration: timedelta,
    ) -> CandidateEvaluation:
        if earliest_start.tzinfo is None or deadline.tzinfo is None:
            raise ValueError("optimization times must be timezone-aware")
        reasons: list[str] = []
        feasible = True
        if strategy.start < earliest_start:
            feasible = False
            reasons.append("Strategy starts before the permitted planning window.")
        if strategy.end > deadline:
            feasible = False
            reasons.append("Strategy completes after the goal deadline.")
        if strategy.duration < required_duration:
            feasible = False
            reasons.append("Strategy duration is shorter than the estimated requirement.")

        grid_cost, covered = self._grid_cost(strategy)
        if not covered:
            feasible = False
            reasons.append("No tariff covers the strategy's full grid-use window.")
        solar_cost = (
            strategy.energy_kwh
            * strategy.solar_fraction
            * self.solar_value_per_kwh
        )
        battery_cost = (
            strategy.energy_kwh
            * strategy.battery_fraction
            * self.battery_degradation_per_kwh
        )
        estimated_cost = grid_cost + solar_cost + battery_cost
        if feasible:
            reasons.append("Strategy satisfies the timing and energy-input constraints.")
        return CandidateEvaluation(strategy, feasible, estimated_cost, tuple(reasons))

    def optimize(
        self,
        strategies: tuple[EnergyStrategy, ...],
        *,
        earliest_start: datetime,
        deadline: datetime,
        required_duration: timedelta,
    ) -> OptimizationResult:
        evaluations = tuple(
            self.evaluate(
                strategy,
                earliest_start=earliest_start,
                deadline=deadline,
                required_duration=required_duration,
            )
            for strategy in strategies
        )
        feasible = tuple(candidate for candidate in evaluations if candidate.feasible)
        if feasible:
            selected = min(
                feasible,
                key=lambda item: (
                    item.estimated_cost,
                    item.strategy.end,
                    item.strategy.strategy_id,
                ),
            )
            return OptimizationResult(
                OptimizationStatus.OPTIMIZED,
                selected,
                evaluations,
                ("Selected the least-cost feasible energy strategy.",),
            )
        if evaluations:
            selected = min(
                evaluations,
                key=lambda item: (
                    max(timedelta(0), item.strategy.end - deadline),
                    item.estimated_cost,
                    item.strategy.strategy_id,
                ),
            )
            return OptimizationResult(
                OptimizationStatus.BEST_EFFORT,
                selected,
                evaluations,
                ("No candidate was fully feasible; selected the closest best-effort strategy.",),
            )
        return OptimizationResult(
            OptimizationStatus.NO_CANDIDATE,
            None,
            (),
            ("No energy strategies were supplied.",),
        )

    def create_optimized_plan(
        self,
        goal: BodyReadyGoal,
        kernel: PoolKernel,
        goal_planner: GoalPlanner,
        strategies: tuple[EnergyStrategy, ...],
    ) -> OptimizedGoalPlanResult:
        assessment = goal_planner.assess(goal, kernel)
        earliest = max(kernel.clock.now(), goal.earliest_start or kernel.clock.now())
        optimization = self.optimize(
            strategies,
            earliest_start=earliest,
            deadline=goal.deadline,
            required_duration=assessment.required_duration,
        )
        if optimization.selected is None:
            optimized_goal = goal
        else:
            selected = optimization.selected.strategy
            optimized_goal = replace(
                goal,
                earliest_start=selected.start,
                metadata={
                    **dict(goal.metadata),
                    "energy_strategy_id": selected.strategy_id,
                    "energy_source": selected.source.value,
                    "estimated_energy_cost": optimization.selected.estimated_cost,
                    "optimization_status": optimization.status.value,
                },
            )
        goal_plan = goal_planner.create_plan(optimized_goal, kernel)
        return OptimizedGoalPlanResult(goal, optimized_goal, optimization, goal_plan)
