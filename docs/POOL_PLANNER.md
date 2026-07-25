# PoolOS Planner

## Purpose

The Planner turns typed objectives into immutable, time-aware plans. It never
executes hardware commands and never bypasses the Policy or Execution engines.

## Initial objective

The first built-in strategy is `PREPARE_BODY_BY_DEADLINE`. It:

1. Reads normalized body state from the Kernel.
2. Selects circulation and heating equipment by capability.
3. Estimates a start time from the configured heating rate.
4. Proposes circulation, heating, and stop-heating steps.
5. Encodes serializable preconditions and completion conditions.
6. Produces a completed zero-command plan when the objective is already met.

## Revision model

Plans are immutable snapshots. Replanning creates a new revision and marks the
stored prior revision as superseded. The Planner retains objective history and a
human-readable reason for each replacement.

## Boundaries

- The Scheduler will decide when a step is eligible.
- The Policy Engine will evaluate whether proposed commands are allowable.
- The Execution Engine remains the only dispatch path.
- Vendor adapters remain outside PoolOS planning logic.
