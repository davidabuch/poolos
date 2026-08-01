# ADR-039: Canonical Operational Context Model

## Status

Accepted for Epic 10.15C.

## Context

ADR-037 introduced the immutable Operational Disposition Model. ADR-038 added a
command-free orchestrator that maps one disposition to one logical next-action
instruction. The operational layer now needs a deterministic description of
what already exists before later milestones may safely suppress duplicate work,
retain a plan, request cancellation, request replacement, or defer evaluation.

Allowing each consumer to read execution, scheduling, safety, and override state
directly would scatter state interpretation and couple operational routing to
multiple subsystem internals. It would also make replay and diagnostics depend
on mutable runtime objects.

## Decision

PoolOS will use one immutable `OperationalContext` snapshot as the canonical
operational-state boundary for a routing evaluation.

The context contains only:

- evaluation identity and capture time;
- an optional `ActivePlanSummary`;
- pending operational action;
- reevaluation summary;
- operational execution summary;
- high-level operational mode;
- safety posture;
- blocking reasons and immutable diagnostics.

`ActivePlanSummary` is a separate immutable value object. It exposes only plan
identity, plan lifecycle, current step identity, remaining step count, and plan
creation time. It does not expose operations, command translations, receipts,
verification evidence, or a mutable coordinator session.

A single `OperationalContextFactory` is the authoritative construction path. It
normalizes diagnostics and derives the high-level operational mode using the
following precedence:

1. serious safety state -> safe mode;
2. blocking reasons -> blocked;
3. manual override -> manual override;
4. waiting or scheduled reevaluation -> waiting;
5. otherwise -> normal.

## Boundaries

Operational context intentionally excludes:

- raw observations and observation stores;
- forecasts, policies, goals, and planning alternatives;
- canonical operations or vendor commands;
- authorization decisions;
- delivery receipts and verification evidence;
- scheduler timers and implementation objects;
- Home Assistant and Pentair clients.

The execution summary is not a second execution lifecycle. It is a small,
read-only operational projection of the existing execution subsystem.

## Consequences

- Operational routing receives one stable state snapshot instead of scattered
  mutable inputs.
- Active execution internals remain encapsulated.
- Context construction and mode precedence are centralized and testable.
- Deterministic replay can persist the exact state visible to routing.
- Future duplicate suppression, cancellation, replacement, scheduling, and
  operator-approval milestones can build on this boundary without redesigning
  execution.

Epic 10.15C introduces the model and construction authority only. It performs no
routing side effects, scheduling, proposal generation, authorization, plan
mutation, delivery, Home Assistant call, Pentair communication, or physical
actuation.
