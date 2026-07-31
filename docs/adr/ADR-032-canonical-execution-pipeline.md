# ADR-032: Canonical Supervisory Execution Pipeline

- Status: Accepted
- Date: 2026-07-31
- Supersedes: None

## Context

PoolOS contains two historical execution-related paths:

1. a generic `Command -> ExecutionEngine -> CommandExecutor` path used by the
   older runtime; and
2. a canonical `PoolOperation -> translation -> VendorCommand -> endpoint`
   path that preserves vendor and transport independence.

Adding supervisory execution directly to either path without clarifying their
roles would create overlapping execution authorities and make future live
actuation difficult to audit safely.

The command-free decision orchestrator, immutable evaluation contexts,
runtime-mode safety boundary, deterministic replay, restart recovery, and
Flight Recorder must remain intact.

## Decision

PoolOS will use `PoolOperation` as the canonical future actuation unit.

The supervisory execution flow will be:

```text
Decision
  -> ExecutionProposal
  -> ExecutionAuthorization
  -> ExecutionPlan
  -> ordered ExecutionStep objects
  -> PoolOperation translation and delivery
  -> independent verification
  -> ExecutionOutcome
```

The decision orchestrator will remain command-free.

The generic `Command` and `ExecutionEngine` path will remain temporarily for
backward compatibility but will not be expanded as the supervisory execution
architecture. Its eventual migration or retirement will be considered only
after the new execution pipeline is mature.

All execution during Epic 10.13 will be simulator-only. Physical Home
Assistant or Pentair delivery is explicitly prohibited and deferred to a later
epic.

Incomplete execution will not be resumed blindly after restart. PoolOS will
reconcile observations and reevaluate before creating new executable intent.

## Consequences

### Positive

- One canonical vendor-independent execution intent exists.
- Decision intelligence remains independent from delivery infrastructure.
- Authorization, delivery, and verification become separately auditable.
- Simulation can exercise the complete execution lifecycle before live control.
- Restart behavior remains conservative and deterministic.

### Costs

- The legacy generic command engine remains temporarily alongside the new
  architecture.
- A later migration is required for `PoolRuntime`.
- Additional domain artifacts must be recorded and projected.

## Epic 10.13A implementation

The first milestone defines immutable models only:

- `ExecutionProposal`
- `ExecutionAuthorization`
- `ExecutionPlan`
- `ExecutionStep`
- `StepOutcome`
- `ExecutionOutcome`
- authorization, lifecycle, and verification enums

No delivery behavior changes in this milestone.
