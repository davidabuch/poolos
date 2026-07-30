# ADR-018: Goal-Oriented Planning Facade

## Status

Accepted — Milestone 10.8

## Context

PoolOS already contains a deterministic planner that accepts normalized `PlanObjective` values. External callers should not need to calculate heating windows or construct planner-native objectives directly. PoolOS also requires a traceable feasibility assessment before future-state intent reaches planning.

## Decision

Add a hardware-independent `GoalPlanner` facade above the existing `Planner`.

The first supported goal is `BodyReadyGoal`: reach a body temperature by a deadline, optionally maintain it until a later time. The facade:

1. reads canonical body state from `PoolKernel`;
2. calculates temperature delta, required duration, available duration, recommended start, and estimated completion;
3. classifies the goal as achieved, feasible, at risk, or infeasible;
4. normalizes the goal into the existing `PlanObjective` contract; and
5. delegates plan creation to the existing `Planner`.

The goal planner does not execute commands, access Home Assistant, or introduce new equipment identifiers.

## Consequences

- User-facing intent can be expressed as a future state instead of low-level commands.
- Feasibility is explicit and testable before execution.
- Existing planning, policy, constraint, and execution boundaries remain authoritative.
- Infeasible goals still produce a traceable best-effort plan, with feasibility embedded in objective metadata.
- Future forecasting and cost models can replace the initial fixed heating-rate estimate without changing downstream contracts.
