# ADR-040: Canonical Operational Action Pipeline

## Status

Accepted for Epic 10.15D.

## Context

ADR-037 introduced immutable operational dispositions. ADR-038 introduced a
command-free orchestrator that converts each disposition into one routing
instruction. ADR-039 introduced the canonical operational context snapshot.

A durable boundary is still required between the routing decision and future
subsystems that may schedule reevaluation, request execution proposals, retain
plans, request cancellation or replacement, or halt for operator review.
Directly invoking those subsystems from the orchestrator would mix routing with
side effects and weaken deterministic replay.

The existing `OperationalOrchestrationInstruction` remains the routing
decision. Epic 10.15D must not introduce a second competing router.

## Decision

PoolOS will introduce:

1. `CanonicalOperationalAction`, an immutable canonical work request derived
   from one orchestration instruction;
2. a deterministic action identifier derived from stable instruction identity;
3. `OperationalActionPipeline`, which validates route compatibility and
   duplicate action identity;
4. `OperationalActionPipelineResult`, an immutable accepted or rejected result;
5. stable pipeline reason codes and diagnostics.

The pipeline performs logical routing only. It identifies the target boundary
but does not invoke it.

## Deterministic identity

The action identifier is a SHA-256-derived identifier over canonical JSON
containing the action, target, context, disposition, decision, plan, reason
code, and reevaluation hint. Replaying the same instruction produces the same
action identifier. A different instruction identity produces a different ID.

This supports replay equivalence and duplicate suppression without random UUIDs
or wall-clock dependence.

## Validation rules

The pipeline validates that each action targets its canonical logical boundary:

- no action -> none;
- request reevaluation -> reevaluation scheduler;
- request proposal -> execution proposal boundary;
- retain, cancel, or replace plan -> execution plan boundary;
- halt -> operator review.

An already accepted action ID is rejected as a duplicate. The accepted-ID set is
provided as immutable input and returned as immutable evidence; the pipeline
does not own persistence.

## Safety boundary

The pipeline does not:

- schedule reevaluation;
- create execution proposals;
- authorize execution;
- mutate, cancel, replace, or retain plans;
- deliver commands;
- call Home Assistant;
- communicate with Pentair;
- actuate physical equipment.

Everything remains simulator-only and command-free.

## Consequences

Positive consequences:

- the orchestrator remains a pure routing decision authority;
- operational work requests gain canonical identity and correlation;
- route validation and duplicate detection become deterministic;
- future side-effect adapters can be introduced behind explicit boundaries;
- replay and audit evidence remain stable.

Tradeoffs:

- one additional immutable model and result boundary are introduced;
- accepted action IDs must eventually be persisted by a separate owner;
- actual target invocation remains deferred.
