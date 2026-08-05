# Guiding Principles

> **Architecture Manual v1.0** · Chapter 3 of 15

These principles are the architectural constitution of PoolOS. New ADRs and major changes should align with them or explicitly explain why an exception is justified.

## 1. Determinism over convenience

### Statement

The same canonical inputs should produce the same logical outputs.

### Rationale

Automation decisions must be reproducible for testing, replay, audit, and restart recovery. Hidden dependence on wall-clock time, mutable process state, iteration order, or implicit external context makes the system harder to trust.

### Architectural consequences

- Time is supplied explicitly where it affects behavior.
- Identity is derived from canonical evidence.
- Order-insensitive collections are normalized.
- Randomness is avoided in core decision paths.
- Replay equivalence is tested.

### Trade-off

Callers may need to provide more explicit data, but the resulting behavior is easier to inspect and reproduce.

## 2. Immutability by default

### Statement

Evidence crossing a boundary should be immutable unless mutation is essential to the responsibility of that boundary.

### Rationale

Immutable evidence preserves historical meaning. It prevents a downstream consumer from observing a different fact than the one originally emitted.

### Architectural consequences

- Dataclasses representing evidence are commonly frozen.
- Collections are normalized into immutable forms where practical.
- Results are replaced by new results rather than updated in place.
- Persistence and replay use snapshots rather than live references.

### Trade-off

Immutability can create more objects, but it substantially reduces ambiguity and accidental coupling.

## 3. Reasoning before execution

### Statement

The system that determines what should happen must remain separate from the system that performs actions.

### Rationale

Decision quality and execution safety are different concerns. Combining them makes it easy for planning logic to bypass authorization, ownership, verification, or vendor-delivery controls.

### Architectural consequences

- Decisions remain command-free.
- Operational disposition is expressed before execution begins.
- Execution receives canonical intent rather than policy internals.
- Hardware communication occurs only at integration boundaries.

### Trade-off

The architecture contains more explicit seams, but each seam can be independently reviewed and tested.

## 4. Vendor independence

### Statement

Core PoolOS logic must not depend on a specific controller, manufacturer, transport, or Home Assistant entity identifier.

### Rationale

Pools and spas have stable domain concepts even when hardware platforms differ. Encoding vendor behavior in core logic would make policy brittle and limit reuse.

### Architectural consequences

- Core models are vendor-neutral.
- Adapters translate at the edge.
- Integration failures do not redefine decision semantics.
- Future vendor support does not require a new cognitive system.

### Trade-off

Adapters must perform more translation, but the center of the system remains portable and coherent.

## 5. Safety before automation

### Statement

A beneficial action is not valid unless it is also authorized, safe, and verifiable.

### Rationale

Pool equipment can create thermal, hydraulic, electrical, and operational risk. Convenience cannot outrank safety boundaries.

### Architectural consequences

- Runtime mode is explicit.
- Live actuation remains disabled until separately commissioned.
- Authority and ownership are explicit.
- Unsafe or inconsistent evidence fails closed.
- Verification is part of execution, not an optional afterthought.

### Trade-off

The system may defer or block actions that a simpler automation would attempt immediately.

## 6. Replayability

### Statement

Important decisions and execution outcomes should be reconstructable from preserved evidence.

### Rationale

Replay enables debugging, recovery, regression analysis, and operator trust.

### Architectural consequences

- Inputs and provenance are preserved.
- Identity flows across boundaries.
- Restart recovery does not blindly restore stale commands.
- Flight recorders capture accepted decisions and execution evidence.

### Trade-off

More evidence must be stored and validated, but failures become far easier to understand.

## 7. Explainability

### Statement

Every important recommendation should be explainable to both humans and machines.

### Rationale

Automation that cannot explain itself is difficult to trust, operate, or improve.

### Architectural consequences

- Alternatives and reasons are modeled explicitly.
- Human and technical renderings are distinct.
- Diagnostics preserve relevant context.
- Blocked and retained outcomes are first-class results.

### Trade-off

Decision models are richer than a simple boolean or command, but they provide far greater operational value.

## 8. Composable boundaries

### Statement

Large workflows should be assembled from smaller boundaries with explicit contracts.

### Rationale

Composition preserves clarity and avoids central managers that accumulate unrelated responsibilities.

### Architectural consequences

- Each boundary has defined responsibilities and non-responsibilities.
- Composition layers reuse existing models instead of inventing parallel ones.
- Side effects remain isolated.
- Tests can target both individual boundaries and composed flows.

### Trade-off

The call graph is more explicit, but architecture remains understandable as the system grows.

## Applying the principles

When reviewing a proposed change, ask:

1. Are all inputs explicit?
2. Is the output immutable evidence?
3. Does the change preserve the separation between reasoning and execution?
4. Is vendor-specific behavior isolated?
5. Does failure remain safe?
6. Can the result be replayed?
7. Can an operator understand the outcome?
8. Is the new responsibility placed at the narrowest appropriate boundary?

## Responsibilities

These principles guide architectural decisions, code review, testing strategy, release gates, and future integrations.

## Non-responsibilities

They do not replace ADRs. A principle provides direction; an ADR records a concrete decision and its consequences.

## Future evolution

The principle set should remain small. New principles should be added only when they express a durable architectural rule rather than a temporary implementation preference.

---

[Previous: Design Philosophy](01-design-philosophy.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Capability Map](03-capability-map.md)
