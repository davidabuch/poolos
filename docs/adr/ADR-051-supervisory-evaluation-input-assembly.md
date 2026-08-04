# ADR-051: Supervisory Evaluation Input Assembly

## Status

Accepted for Epic 10.15O.

## Context

Epic 10.15N produces immutable runtime-trigger coalescing evidence and delegates trigger precedence to the existing `EvaluationTriggerCoalescer`. PoolOS already has the canonical immutable `DecisionEvaluationContext` and the canonical `DecisionOrchestrationRequest` consumed by the `DecisionOrchestrator`.

The missing responsibility is deterministic assembly of those existing models from explicit current facts and successful coalescing evidence. Creating another context type, runtime queue, planning engine, or orchestration layer would duplicate existing architecture.

## Decision

Introduce one pure `SupervisoryEvaluationInputAssembler` boundary.

The boundary consumes:

- one successful `RuntimeTriggerCoalescingBatch`;
- an explicit timezone-aware evaluation time;
- an explicit runtime mode;
- immutable current goals;
- one existing `DecisionPlanningRequest`;
- explicit observations, forecast, freshness, policies, blockers, and metadata;
- optional previous-decision and active-record evidence.

The boundary produces:

- one existing `DecisionEvaluationContext`;
- one existing `DecisionOrchestrationRequest`;
- immutable assembly evidence with deterministic context and assembly identities.

The assembler normalizes order-insensitive inputs, validates JSON-compatible identity evidence, preserves coalescing provenance, and rejects missing, future-dated, inconsistent, or incomplete inputs fail-closed.

## Boundaries

Epic 10.15O does not:

- invoke the `DecisionOrchestrator`;
- evaluate planning alternatives;
- create plans or operational actions;
- call `PoolRuntime`;
- enqueue work or schedule background tasks;
- perform persistence or network I/O;
- contact Home Assistant, Pentair, vendors, or hardware;
- actuate physical equipment.

## Consequences

PoolOS gains one deterministic handoff from runtime-trigger coalescing into the already-established supervisory evaluation models without adding a parallel context or orchestration abstraction.

The next reviewed milestone may invoke the existing `DecisionOrchestrator` with the assembled request while preserving simulation-only safety and immutable invocation evidence.
