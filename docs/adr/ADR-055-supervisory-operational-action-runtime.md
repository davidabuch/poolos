# ADR-055: Supervisory Operational-Action Runtime Composition

## Status

Accepted for Epic 10.16A.

## Context

Epic 10.15Q established one deterministic entry point for a complete command-free supervisory evaluation cycle. Earlier 10.15 milestones established the canonical operational-action pipeline and a non-hardware downstream adapter that safely handles no-op, reevaluation, and operator-review routes while rejecting execution targets.

The next required boundary is composition. PoolOS needs one reviewed path that carries a supervisory instruction into canonical action validation and downstream adaptation without creating a scheduler, execution dispatcher, retry loop, network client, or hardware-control path.

## Decision

Introduce `SupervisoryOperationalActionRuntime`.

For one explicit supervisory runtime request, it composes exactly once and in order:

1. `SupervisoryEvaluationRuntime`;
2. `CanonicalOperationalAction.from_instruction`;
3. `OperationalActionPipeline`;
4. `NonHardwareOperationalActionAdapter`.

The result preserves the complete supervisory runtime evidence, canonical action, pipeline result, downstream receipt, stable composition identity, and merged provenance.

The composition accepts explicit prior accepted-action identities for deterministic duplicate suppression and an optional correlation identity. Logical identity is derived only from stable upstream and downstream evidence.

## Safety boundaries

Epic 10.16A does not:

- invoke a reevaluation scheduler;
- create, submit, cancel, replace, retain, or mutate an execution plan;
- create an execution proposal;
- authorize execution;
- retry or queue work;
- persist state;
- perform Home Assistant, Pentair, vendor, transport, or network calls;
- deliver commands or actuate physical equipment.

No-op, reevaluation, and operator-review routes may produce existing non-hardware receipts. Execution proposal and execution plan targets remain rejected by the non-hardware adapter.

## Consequences

PoolOS gains one deterministic, replayable bridge from supervisory reasoning to validated downstream operational evidence. The boundary exposes where future reviewed adapters may connect while preserving the existing safety separation between reasoning and execution.

A later milestone may introduce a narrowly scoped execution-side adapter, but only after its proposal, authorization, ownership, and simulation safety contracts are explicitly reviewed.
