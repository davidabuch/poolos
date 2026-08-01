# ADR-041: Operational Action Registry

## Status

Accepted for Epic 10.15E.

## Context

ADR-040 introduced the canonical operational-action pipeline.  The pipeline
must validate that each action targets the correct downstream boundary, but a
hard-coded action-to-target table inside the pipeline would make routing
procedural and duplicate knowledge already expressed by the orchestration
contract.

PoolOS needs one declarative, immutable authority that defines which logical
boundary may consume each operational action.  That authority must remain
command-free and must not become a dispatcher.

## Decision

Introduce an immutable `OperationalActionRegistry` containing
`OperationalActionRegistration` values.  Each registration binds exactly one
`OperationalAction` to one logical `OperationalTarget`, a stable boundary name,
and a human-readable description.

The registry:

- validates duplicate and conflicting registrations at construction time;
- performs deterministic action lookup;
- returns immutable found or unsupported results with stable reason codes;
- exposes no invocation or mutation capability;
- becomes the route authority consulted by `OperationalActionPipeline`.

The canonical default registry contains one entry for every currently defined
`OperationalAction`.  Tests may construct partial registries to prove
unsupported-action behavior.

## Consequences

- Action routing is declarative rather than an expanding conditional chain.
- The pipeline no longer owns a separate route table.
- Unsupported actions fail closed and produce deterministic evidence.
- Future downstream boundaries can be represented by registrations without
  embedding invocation logic in the registry.
- Actual dispatch, scheduling, proposal generation, authorization, plan
  mutation, delivery, Home Assistant calls, Pentair communication, and physical
  actuation remain outside this milestone.

## Rejected Alternatives

### Add an operational action dispatcher now

Rejected because it would overlap the pipeline's routing responsibility and
introduce premature side effects.

### Keep a private route map in the pipeline

Rejected because it would make the pipeline the implicit registration authority
and encourage duplicate route definitions.

### Store callable handlers in registry entries

Rejected because callables would turn a declarative registry into an execution
mechanism and weaken deterministic replay and simulator-only safety.
