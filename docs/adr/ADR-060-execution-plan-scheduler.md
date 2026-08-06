# ADR-060: Execution Plan Scheduler

## Status

Accepted for Epic 10.16F.

## Context

Epics 10.16A through 10.16E connect supervisory evaluation to deterministic execution-plan construction and explicit plan authorization. PoolOS still requires a boundary that records when an authorized plan is eligible to proceed, without dispatching the plan or introducing a background scheduler.

Scheduling must remain explicit and replayable. Reading wall-clock time, starting timers, persisting queues, or invoking execution would combine timing policy with runtime side effects and weaken deterministic evidence.

## Decision

Introduce one `ExecutionPlanScheduler` boundary.

The scheduler consumes:

- one existing `ExecutionPlanAuthorizationResult`;
- an explicit timezone-aware evaluation time;
- an optional explicit execution time;
- optional explicit deferral reasons;
- a scheduling policy version, correlation identity, and metadata.

It emits immutable evidence with one of four dispositions:

- `IMMEDIATE` when execution eligibility begins at the explicit evaluation time;
- `SCHEDULED` when eligibility begins at a later explicit time;
- `DEFERRED` when explicit scheduling policy evidence prevents time assignment;
- `REJECTED` when authorization or timing evidence is invalid.

Immediate and scheduled results contain one immutable `ScheduledExecutionPlan`. Identity is derived from stable authorization, plan, timing, policy, and correlation evidence.

## Boundaries

Epic 10.16F does not:

- read the system clock;
- start timers or background tasks;
- persist, recover, poll, or dequeue schedules;
- dispatch or mutate execution plans;
- translate or deliver operations;
- invoke Home Assistant, Pentair, vendors, transports, or networks;
- actuate physical equipment.

## Consequences

PoolOS gains deterministic timing evidence after plan authorization while preserving a hard boundary before dispatch. A later milestone may consume due scheduled-plan evidence, but that consumer must remain separate from timing policy and must receive its time explicitly.
