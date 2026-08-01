# ADR-037: Operational Disposition Model

## Status

Accepted and implemented in Epic 10.15A.

## Context

PoolOS already has a deterministic, command-free decision orchestration layer.
It freezes evaluation context, coalesces triggers, plans, applies stability
rules, records accepted decisions, and projects diagnostics. Creating a second
"operational evaluation engine" would duplicate that responsibility and risk
introducing two competing supervisory authorities.

The completed simulator execution pipeline answers a different question: how an
authorized execution plan is delivered, observed, verified, advanced, and
completed. A narrow boundary is still needed between accepted supervisory intent
and execution-plan handling.

That boundary must decide whether PoolOS should wait, schedule reevaluation,
submit a new plan, keep an existing plan, cancel an obsolete plan, replace an
outdated plan, or block. It must not perform any of those actions itself.

## Decision

PoolOS introduces a deterministic **Operational Disposition Model** after the
Decision Orchestrator and before execution proposal and authorization.

```text
Decision Orchestrator
        |
        v
Operational Disposition Engine
        |
        +-- WAIT
        +-- SCHEDULE_REEVALUATION
        +-- SUBMIT_NEW_PLAN
        +-- KEEP_EXISTING_PLAN
        +-- CANCEL_EXISTING_PLAN
        +-- REPLACE_EXISTING_PLAN
        +-- BLOCK
```

The boundary consists of:

- `OperationalDecisionSnapshot`, a minimal immutable view of the decision
  accepted by orchestration;
- `OperationalPlanSummary`, a minimal immutable view of the active execution
  plan;
- `OperationalEvaluationRequest` and `OperationalEvaluationResult`;
- `OperationalDisposition` and stable `OperationalReasonCode` enums;
- `OperationalDispositionEngine`, a side-effect-free deterministic evaluator.

`OperationalDecisionSnapshot.from_orchestration()` resolves the accepted
supervisory decision correctly:

- blocked orchestration produces a blocked snapshot with no decision;
- retained orchestration uses the active recorded decision, not the rejected
  equivalent proposal;
- completed orchestration uses the newly accepted decision.

The active-plan summary intentionally exposes only plan identity, source decision
identity, lifecycle status, and whether cancellation or replacement is allowed.
It does not expose delivery endpoints, vendor commands, equipment state, or
mutable coordinator internals.

## Deterministic Rules

1. Invalid evaluation context produces `BLOCK`.
2. An accepted blocked decision produces `BLOCK`.
3. A selected decision with no active plan produces `SUBMIT_NEW_PLAN`.
4. A selected decision matching the active plan's decision produces
   `KEEP_EXISTING_PLAN`.
5. A changed selected decision with a replaceable plan produces
   `REPLACE_EXISTING_PLAN`.
6. A changed selected decision with a non-replaceable plan produces `BLOCK`.
7. A non-selected decision with a cancellable active plan produces
   `CANCEL_EXISTING_PLAN`.
8. A non-selected decision with a non-cancellable active plan produces `BLOCK`.
9. A non-selected decision with no plan and a future-change hint produces
   `SCHEDULE_REEVALUATION`.
10. A non-selected decision with no plan and no future-change hint produces
    `WAIT`.

## Safety Boundary

The Operational Disposition Engine:

- does not build execution proposals;
- does not authorize execution;
- does not create or mutate execution plans;
- does not advance an execution coordinator;
- does not cancel or replace plans;
- does not translate or deliver commands;
- does not call Home Assistant;
- does not communicate with Pentair;
- does not actuate physical equipment.

It returns one immutable recommendation with stable reason codes and diagnostics.
A future milestone may consume that recommendation through a separately reviewed
and explicitly authorized integration boundary.

## Consequences

### Positive

- Existing orchestration remains the single supervisory decision authority.
- Plan handling becomes explicit and testable without introducing side effects.
- Decision retention is distinguished from execution-plan retention.
- Future cancel and replace workflows can be added without changing decision
  intelligence.
- Deterministic replay remains possible because all inputs and outputs are
  immutable.

### Tradeoffs

- The model recommends actions that are not yet performed.
- Cancellation and replacement permissions are summarized by the caller and
  must eventually be derived from an authoritative execution policy.
- Reevaluation hints remain descriptive strings until a future scheduling
  contract defines typed times and triggers.

## Rejected Alternative

A new Operational Evaluation Engine duplicating context evaluation, planning,
and decision stability was rejected because PoolOS already implements those
responsibilities in the Decision Orchestrator.
