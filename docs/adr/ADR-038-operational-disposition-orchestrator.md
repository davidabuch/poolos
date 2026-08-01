# ADR-038: Operational Disposition Orchestrator

## Status

Accepted

## Context

ADR-037 introduced a deterministic Operational Disposition Model that compares
one accepted supervisory decision with a minimal active-plan summary. The model
returns one immutable recommendation: wait, schedule reevaluation, submit, keep,
cancel, replace, or block.

That recommendation must not be interpreted independently by multiple callers.
A narrow routing boundary is needed to translate each disposition into one
stable next-action instruction while preserving the prohibition on side effects.

The Decision Orchestrator must remain the single supervisory evaluation
authority. The Operational Disposition Engine must remain a pure evaluator. The
execution pipeline must remain the only authority for proposal generation,
authorization, planning, delivery, verification, and completion.

## Decision

PoolOS introduces a deterministic **Operational Disposition Orchestrator** after
the Operational Disposition Engine.

```text
Decision Orchestrator
        |
        v
Operational Disposition Engine
        |
        v
Operational Disposition Orchestrator
        |
        +-- NO_ACTION ----------------------> NONE
        +-- REQUEST_REEVALUATION ----------> Reevaluation Scheduler boundary
        +-- REQUEST_PROPOSAL --------------> Execution Proposal boundary
        +-- RETAIN_PLAN --------------------> Execution Plan boundary
        +-- REQUEST_PLAN_CANCELLATION -----> Execution Plan boundary
        +-- REQUEST_PLAN_REPLACEMENT ------> Execution Plan boundary
        +-- HALT ---------------------------> Operator Review boundary
```

The orchestrator consumes exactly one `OperationalEvaluationResult` and returns
one immutable `OperationalOrchestrationInstruction` containing:

- one `OperationalAction`;
- one logical `OperationalTarget`;
- disposition, context, decision, and plan identity;
- stable reason code and human-readable reason;
- a reevaluation hint only when reevaluation is requested;
- deterministic diagnostics.

The target is a logical boundary name, not a live service, callback, transport,
or dependency injection handle.

## Deterministic Mapping

| Disposition | Action | Target |
|---|---|---|
| `WAIT` | `NO_ACTION` | `NONE` |
| `SCHEDULE_REEVALUATION` | `REQUEST_REEVALUATION` | `REEVALUATION_SCHEDULER` |
| `SUBMIT_NEW_PLAN` | `REQUEST_PROPOSAL` | `EXECUTION_PROPOSAL_BOUNDARY` |
| `KEEP_EXISTING_PLAN` | `RETAIN_PLAN` | `EXECUTION_PLAN_BOUNDARY` |
| `CANCEL_EXISTING_PLAN` | `REQUEST_PLAN_CANCELLATION` | `EXECUTION_PLAN_BOUNDARY` |
| `REPLACE_EXISTING_PLAN` | `REQUEST_PLAN_REPLACEMENT` | `EXECUTION_PLAN_BOUNDARY` |
| `BLOCK` | `HALT` | `OPERATOR_REVIEW` |

## Invariants

- Proposal requests require a decision identity and cannot identify an existing
  plan.
- Plan retention, cancellation, and replacement require a plan identity.
- Plan replacement also requires the newly accepted decision identity.
- Reevaluation requests require a reevaluation hint.
- Only reevaluation requests may carry a reevaluation hint.
- `NO_ACTION` must target `NONE`.
- Every actionable instruction must identify a non-`NONE` logical target.
- Diagnostics are immutable.

## Safety Boundary

The Operational Disposition Orchestrator:

- does not call the Decision Orchestrator;
- does not evaluate or change a disposition;
- does not schedule reevaluation;
- does not generate execution proposals;
- does not authorize execution;
- does not create, retain, cancel, replace, supersede, or mutate plans;
- does not deliver commands;
- does not call Home Assistant;
- does not communicate with Pentair;
- does not actuate physical equipment.

It returns one immutable routing instruction only. A future milestone may add a
separately reviewed dispatcher that consumes these instructions, but that
future dispatcher must preserve the authoritative subsystem boundaries.

## Consequences

### Positive

- Every disposition has one canonical interpretation.
- Routing semantics are explicit, deterministic, replayable, and testable.
- Decision intelligence, disposition evaluation, routing, and execution remain
  separate responsibilities.
- Future scheduling and plan-control contracts can evolve behind stable logical
  target names.
- Simulator-only safety remains intact.

### Tradeoffs

- The orchestrator still does not perform operational work.
- Logical targets are intentionally abstract until dedicated subsystem contracts
  exist.
- Cancellation and replacement remain recommendations, not implemented plan
  lifecycle transitions.

## Rejected Alternatives

### Invoke target subsystems directly

Rejected because it would combine routing with side effects and prematurely
couple operational intelligence to execution and scheduling implementations.

### Put routing inside the Operational Disposition Engine

Rejected because evaluation and routing answer different questions and should
remain independently testable.

### Let each caller interpret dispositions

Rejected because distributed interpretation would create duplicate mappings and
inconsistent behavior.
