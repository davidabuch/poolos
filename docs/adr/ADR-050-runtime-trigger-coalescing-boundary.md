# ADR-050: Runtime Trigger Coalescing Boundary

## Status

Accepted and implemented for Epic 10.15N.

## Context

ADR-048 introduced deterministic acceptance evidence for reevaluation runtime
submissions. ADR-049 made accepted submission identities restart-safe. PoolOS
already has a pure `EvaluationTriggerCoalescer`, but no reviewed boundary yet
connects accepted reevaluation submission evidence to that coalescer.

Directly constructing evaluation contexts or invoking the Decision Orchestrator
would combine intake validation, duplicate suppression, trigger precedence,
context construction, and decision evaluation. Those responsibilities remain
separate.

## Decision

PoolOS introduces `RuntimeTriggerCoalescingBoundary`.

The boundary consumes immutable `ReevaluationRuntimeSubmissionResult` values,
an explicit timezone-aware `coalesced_at` time, and explicit previously consumed
submission identities. It validates and consumes accepted submissions, delegates
trigger precedence to the existing `EvaluationTriggerCoalescer`, and returns one
immutable `RuntimeTriggerCoalescingBatch`.

The batch contains ordered per-submission evidence, sorted consumed submission
identities, an optional `CoalescedEvaluationTrigger`, deterministic identities,
and provenance.

## Invariants

- Only `ACCEPTED` runtime-submission results may be consumed.
- The accepted submission ID must be present in the submission result's explicit
  acceptance evidence.
- Future-dated submission evidence is rejected relative to `coalesced_at`.
- Previously consumed identities return duplicate evidence and are not
  re-coalesced.
- Duplicate inputs are consumed at most once.
- Input order does not affect result order, identities, or coalesced output.
- Trigger precedence remains owned by the existing `EvaluationTriggerCoalescer`.

## Safety boundary

The boundary does not:

- construct `DecisionEvaluationContext` values;
- invoke the Decision Orchestrator;
- enqueue, schedule, publish, or persist work;
- poll clocks or create timers or threads;
- perform filesystem, database, network, Home Assistant, Pentair, vendor, HAL,
  delivery, or equipment operations;
- actuate physical equipment.

## Future work

A later reviewed milestone may construct a frozen evaluation context from the
coalesced trigger and existing immutable observation, goal, policy, and runtime
state. Decision Orchestrator invocation remains a separate boundary.

## Consequences

- Accepted restart-safe submissions now enter the existing deterministic trigger
  precedence model through one reviewed seam.
- Duplicate consumption is explicit and replayable.
- PoolOS avoids introducing a second queue, bus, or coalescer.
- Runtime evaluation remains deliberately deferred.
