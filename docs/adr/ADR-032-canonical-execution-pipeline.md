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

## Epic 10.13B implementation

Proposal generation is implemented as a command-free boundary above decision orchestration. Only a current, changed, selected, recorded decision may produce an `ExecutionProposal`. Blocked contexts, retained decisions, non-selected outcomes, unrecorded decisions, and stale or superseded decisions produce explicit non-generation results.

Canonical operations are supplied explicitly to proposal generation by domain logic. Decision ranking does not contain vendor commands or transport payloads. Proposal IDs are deterministic for an accepted decision, preventing repeated evaluation of the same result from creating distinct executable intent.

This milestone does not authorize, plan, translate, deliver, verify, or resume execution.

## Epic 10.13C implementation

Authorization is implemented as a pure, command-free safety-preflight boundary.
`ExecutionAuthorizationEngine` consumes an `ExecutionProposal` plus the current
Flight Recorder decision, frozen evaluation context, runtime environment, and
active safety blockers. It returns an immutable `ExecutionAuthorization` and
performs no planning, translation, or delivery.

Three authorization dispositions are supported:

- `AUTHORIZED` for a current, recorded simulation proposal that passes every
  preflight check;
- `DEFERRED` for temporary conditions requiring fresh evaluation; and
- `REJECTED` for identity, supersession, runtime, or physical-delivery safety
  violations.

Rejection has precedence over deferral. Epic 10.13 remains simulator-only:
shadow runtime is deferred, live runtime is rejected, and any environment that
allows physical delivery is rejected. Authorization identifiers are
deterministic for an identical preflight snapshot, preserving replay and audit
semantics.

This milestone does not construct execution plans, translate operations,
deliver commands, verify observations, or invoke Home Assistant or Pentair.
