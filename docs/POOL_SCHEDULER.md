# PoolOS Execution-Plan Scheduler

The `Scheduler` is the time and lifecycle coordinator for immutable Planner output. It does not create commands, evaluate policy, or touch hardware.

It is separate from `DeterministicReevaluationScheduler`, the ADR-045 supervisory reevaluation
boundary. The reevaluation scheduler stores immutable deferred reevaluation records only; it does
not activate plans or use plan-step lifecycle state.

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

## Reevaluation scheduling boundary

The deterministic reevaluation scheduler:

- consumes a validated deferred downstream receipt;
- requires explicit timezone-aware request, schedule, and processing times;
- records immutable scheduled, rejected, duplicate, or cancelled results;
- uses deterministic request and result identities;
- performs no due-time polling or decision evaluation in Epic 10.15I;
- remains in-memory and is not yet restart-safe.

It never forwards work to the execution-plan `Scheduler` and never invokes hardware.

## Due reevaluation trigger boundary

ADR-046 adds a pure consumer of immutable reevaluation scheduling records. At an explicit `as_of`
time, `DueReevaluationTriggerBoundary` sorts the records deterministically and converts each valid
due record into an `EXPECTED_CHANGE_REACHED` `EvaluationTriggerRequest`.

The boundary returns explicit completion identities so replay and duplicate suppression do not
depend on hidden mutable state. It does not modify either scheduler, poll time, submit the trigger
to a runtime, construct an evaluation context, or invoke the Decision Orchestrator.
