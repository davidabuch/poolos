# ADR-019: Deterministic Energy and Cost Optimization

## Status

Accepted for PoolOS milestone 10.9.

## Context

The goal planner can determine when a body must begin heating, but it does not distinguish between multiple energy strategies. PoolOS needs a deterministic way to compare grid, solar, battery, and hybrid candidates without allowing pricing logic to bypass the canonical planner or execution path.

## Decision

Add an `EnergyCostOptimizer` facade between goal assessment and goal-plan creation. It receives explicit, immutable tariff windows and energy strategies. Each candidate is evaluated for timing feasibility, required duration, tariff coverage, and estimated cost. Selection is deterministic: lowest estimated cost, then earliest completion, then stable strategy identifier.

The selected strategy is recorded in goal metadata and the optimized goal is passed back through the existing `GoalPlanner`. The optimizer does not issue commands, contact Home Assistant, infer live tariffs, or operate equipment.

## Consequences

- Energy decisions are testable and reproducible.
- Solar opportunity cost and battery degradation can be represented explicitly.
- Missing or infeasible candidates remain traceable through best-effort outcomes.
- Forecast ingestion, utility-provider adapters, and continuous replanning remain separate future milestones.
