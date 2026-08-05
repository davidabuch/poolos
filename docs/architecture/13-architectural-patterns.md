# Architectural Patterns

> **Architecture Manual v1.0** · Chapter 14 of 15

## Purpose

PoolOS repeatedly uses a small set of patterns to preserve determinism, safety, explainability, and maintainability. Contributors should recognize these patterns before introducing new abstractions.

## Immutable boundary objects

Requests, results, plans, records, and canonical domain models are immutable whenever practical.

This pattern:

- prevents downstream mutation of prior evidence;
- makes reasoning boundaries easier to test;
- supports hashing and identity derivation;
- improves replayability;
- makes concurrency and composition safer.

Mutation belongs in explicit stateful infrastructure, not inside evidence objects.

## Explicit time injection

Architectural boundaries receive the relevant time explicitly rather than consulting the wall clock during evaluation.

This pattern:

- makes tests deterministic;
- prevents identity drift;
- supports historical replay;
- distinguishes event time from processing time.

Timezone-aware values are required when a timestamp participates in evidence or identity.

## Canonical serialization and derived identity

When identity depends on content, PoolOS normalizes the defining evidence, serializes it canonically, and derives a stable identifier.

This pattern requires:

- stable field selection;
- deterministic ordering;
- explicit handling of enums, times, mappings, and sequences;
- exclusion of incidental process state.

Identity should answer what an artifact *is*, not when a random object instance happened to be created.

## Evidence accumulation

Each boundary adds its own evidence while preserving upstream identity and provenance.

```text
submission evidence
  -> coalescing evidence
  -> assembly evidence
  -> decision evidence
  -> disposition evidence
  -> execution evidence
  -> verification evidence
```

This pattern makes end-to-end traceability possible without allowing one object to become an unbounded container for the entire system.

## Command-query separation

Observation and evaluation paths do not actuate equipment. Command delivery is isolated behind authorized execution and adapters.

This pattern keeps read models, reasoning, and explanation safe to run in simulation, diagnostics, replay, and degraded modes.

## Reasoning-execution separation

Cognitive components decide what should happen. Execution components determine how accepted intent may be carried out safely.

The separation prevents:

- decisions from authorizing themselves;
- execution from silently redefining goals;
- adapters from becoming policy engines;
- platform entities from becoming the supervisory authority.

## Layered dependency direction

Higher layers may depend on lower-level canonical contracts, but vendor and platform details must not flow upward into core reasoning.

Cross-layer shortcuts are architectural debt even when they appear convenient.

## Functional core, imperative shell

Most domain evaluation is deterministic and side-effect free. I/O, scheduling, persistence, and external communication remain at the edges.

This pattern makes the core easy to test and the imperative shell easier to constrain.

## Composition over duplication

Runtime boundaries compose existing evaluators and models rather than reimplementing their rules.

A composition layer may coordinate order and preserve provenance, but it should not become a second planner, decision engine, or execution engine.

## Explicit authority gates

Permission is represented and checked explicitly before execution proceeds.

The presence of intent, a plan, a runtime call, or an adapter does not imply authority.

## Fail-closed actuation

When required authority, safety evidence, or transport guarantees are missing, live actuation is blocked.

The system may continue observation, explanation, simulation, and command-free evaluation where safe.

## Bounded recovery

Retries and recovery paths have explicit limits, terminal outcomes, and recorded evidence.

Unbounded retry loops can convert a temporary fault into unsafe or unpredictable behavior.

## Observe after act

PoolOS treats post-delivery observation as authoritative. A successful adapter response is evidence of submission, not proof of physical completion.

## Flight-recorder pattern

Material decisions and execution transitions produce structured records suitable for audit, diagnostics, and replay.

Flight records should preserve identities and causality rather than merely emit human-readable log messages.

## Golden-scenario testing

Representative deterministic scenarios validate multi-boundary behavior, fault handling, and replay equivalence.

Golden scenarios complement focused unit tests; they do not replace them.

## Compatibility facade

Existing imports or interfaces may remain available as a compatibility surface while new code uses clearer defining-module boundaries.

Compatibility is deliberate and tested. It must not silently redefine the stable API.

## Degraded-mode modeling

Connectivity loss, stale observations, and unavailable sources are represented explicitly rather than collapsed into false values or generic errors.

Degraded operation should preserve safe capabilities while preventing unsupported certainty or actuation.

## Pattern selection guidance

Before adding a new framework or abstraction, ask:

1. Can an existing canonical model represent the concept?
2. Can the behavior be a deterministic evaluator?
3. Is the proposed component composing boundaries or duplicating them?
4. Does it preserve identity and provenance?
5. Does it introduce hidden time, state, I/O, or authority?
6. Can it be exercised in simulation and replay?

## Responsibilities

This chapter documents the reusable design patterns contributors should apply consistently.

## Non-responsibilities

It does not mandate one class structure or prohibit justified exceptions approved through an ADR.

## Future evolution

Patterns may be refined as the system matures, but exceptions to core safety and determinism patterns require explicit architectural review.

---

[Previous: Glossary and Terminology](12-glossary-and-terminology.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Future Evolution](14-future-evolution.md)
