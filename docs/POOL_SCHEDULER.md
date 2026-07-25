# PoolOS Scheduler

The Scheduler is the time and lifecycle coordinator for immutable Planner output. It does not create commands, evaluate policy, or touch hardware.

## Responsibilities

- Activate immutable plans.
- Determine which steps are eligible at the current kernel time.
- Enforce dependencies and eligibility windows.
- Evaluate preconditions, completion conditions, and cancellation conditions.
- Track submission, completion, failure, expiry, and cancellation.
- Apply each step's declared failure behavior.
- Produce restart-safe snapshots and restore them after a process restart.

## Command path

1. The Scheduler determines readiness.
2. The Policy Engine evaluates commands from newly ready steps.
3. The Execution Engine remains the only dispatch path.
4. The host reports progress back to the Scheduler.

The Scheduler never bypasses policy evaluation or execution.
