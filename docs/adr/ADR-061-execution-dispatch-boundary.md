# ADR-061: Execution Dispatch Boundary

## Status

Accepted for Epic 10.16G.

## Context

Epics 10.16A through 10.16F established a deterministic path from supervisory
evaluation through execution-plan scheduling. The next safe responsibility is
to prepare a due scheduled plan for future delivery without translating or
sending any command.

## Decision

Introduce one `ExecutionDispatchBoundary` that consumes an immutable
`ExecutionPlanScheduleResult` plus an explicit timezone-aware evaluation time.

The boundary:

- accepts only immediate or scheduled plans with consistent authorization,
  schedule, and plan identities;
- emits a deterministic immutable `ExecutionDispatchRequest` only when the
  scheduled execution time has been reached;
- supports explicit deferred and cancelled outcomes;
- preserves schedule, authorization, plan, proposal, decision, context, and
  correlation identities and provenance;
- uses no system clock and performs no side effects.

## Boundaries

Epic 10.16G does not:

- translate canonical operations into vendor commands;
- choose a transport or vendor adapter;
- persist or enqueue work;
- deliver, acknowledge, verify, retry, or recover commands;
- call Home Assistant, Pentair, MQTT, networks, or physical equipment.

## Consequences

PoolOS gains a deterministic handoff between scheduling and future delivery.
The resulting dispatch request is evidence that work is due and structurally
valid, not proof that any command has been sent or executed.
