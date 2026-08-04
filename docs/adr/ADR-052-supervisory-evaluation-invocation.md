# ADR-052: Deterministic Supervisory Evaluation Invocation

## Status

Accepted for Epic 10.15P.

## Context

Epic 10.15O produces immutable `SupervisoryEvaluationAssemblyResult` evidence containing the existing `DecisionEvaluationContext` and existing `DecisionOrchestrationRequest`. PoolOS already has one canonical `DecisionOrchestrator` that performs command-free planning, stability evaluation, optional decision recording, and Home Assistant projection.

The missing responsibility is a reviewed boundary that consumes one successful assembly and invokes that existing orchestrator exactly once while preserving upstream identities. Creating another orchestrator, queue, runtime loop, status enum, or planning abstraction would duplicate established architecture.

## Decision

Introduce one stateless `SupervisoryEvaluationInvoker` boundary.

The boundary consumes:

- one immutable `SupervisoryEvaluationAssemblyResult`;
- one explicit timezone-aware invocation time;
- the existing `DecisionOrchestrator` collaborator;
- the existing `PoolKernel` collaborator.

The boundary:

- validates assembly, context, and coalescing identity consistency;
- requires simulator runtime mode;
- derives one stable invocation identity from the boundary, assembly, coalescing, and context identities;
- invokes `DecisionOrchestrator.evaluate()` exactly once;
- preserves the existing `OrchestrationStatus` outcomes of completed, retained, or blocked context;
- returns immutable invocation evidence and provenance.

Invocation time is recorded as evidence but is not part of the logical invocation identity. Replaying the same assembly therefore preserves the same invocation identity.

Invalid evidence and unexpected orchestrator failures remain explicit exceptions. Epic 10.15P does not introduce a parallel rejected-outcome enum or hide programming and evaluation failures inside a generic result.

## Boundaries

Epic 10.15P does not:

- create another decision orchestrator;
- assemble evaluation inputs again;
- change planning, stability, recording, or projection behavior;
- suppress duplicate invocation;
- add retries, queues, scheduling, persistence, or restart recovery;
- route operational actions;
- call the mutable `PoolRuntime` command loop;
- create or execute operational plans;
- contact Home Assistant directly;
- contact Pentair, vendors, transports, or hardware;
- perform networking or physical equipment actuation.

## Consequences

PoolOS gains a deterministic, simulator-only invocation seam between assembled reevaluation evidence and the existing supervisory decision authority. Epic 10.15Q may compose the full closed reevaluation loop and define end-to-end duplicate, restart, replay, and failure-handling invariants without changing the orchestrator contract.
