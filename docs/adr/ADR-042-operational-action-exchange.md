# ADR-042: Operational Action Exchange

## Status

Accepted for Epic 10.15F.

## Context

ADR-040 introduced immutable canonical operational actions and pipeline
acceptance evidence. ADR-041 introduced the declarative action registry as the
single authority for logical action routes. PoolOS still needs a final,
explicit boundary between operational reasoning and future downstream adapters.

A generic event bus would overlap the existing event infrastructure and would
prematurely introduce asynchronous semantics. A dispatcher would invoke
boundaries before proposal, scheduler, operator-review, and execution contracts
are ready for side effects.

## Decision

Introduce a synchronous, deterministic, command-free
`OperationalActionExchange`.

The exchange:

- accepts exactly one immutable `OperationalActionExchangeRequest`;
- requires an accepted `OperationalActionPipelineResult`;
- verifies that the canonical action ID remains present in acceptance evidence;
- resolves the action through the immutable `OperationalActionRegistry`;
- verifies consistency among the canonical action target, pipeline route, and
  registry destination;
- emits one immutable `OperationalActionExchangeResult` with a deterministic
  exchange ID, destination, boundary name, reason code, and diagnostics;
- fails closed for rejected pipeline results, missing acceptance evidence,
  unsupported routes, or conflicting route evidence.

The exchange never invokes the resolved boundary. It performs no scheduling,
proposal generation, plan mutation, authorization, command delivery, Home
Assistant call, Pentair communication, or physical actuation.

## Consequences

- PoolOS gains a clear architectural seam between the operational decision
  domain and future side-effecting adapters.
- Accepted action and route evidence remain replayable and independently
  auditable.
- A destination cannot be selected when pipeline or registry evidence is
  inconsistent.
- Future adapters can consume exchange results without changing disposition,
  orchestration, pipeline, or registry contracts.
- Simulator-only safety remains intact.

## Rejected Alternatives

### Introduce a second event bus

Rejected because PoolOS already has event infrastructure and 10.15F requires a
synchronous decision boundary, not asynchronous publication semantics.

### Invoke downstream handlers from the registry

Rejected because callable registrations would convert declarative route data
into an execution mechanism and weaken deterministic replay.

### Add an operational dispatcher now

Rejected because downstream invocation contracts and side-effect policies are
not yet defined. The exchange deliberately stops at an immutable destination
decision.
