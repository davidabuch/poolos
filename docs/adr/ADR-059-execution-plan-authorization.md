# ADR-059: Execution Plan Authorization

## Status

Accepted for Epic 10.16E.

## Context

Epic 10.16D constructs a canonical `ExecutionPlan` only after validating the
supervisory plan-request chain and delegating to the existing deterministic
builder. That builder already requires proposal-level authorization before a
plan can exist.

PoolOS still needs a separate, explicit admission decision for the constructed
plan before any future scheduling or dispatch boundary may consume it. This is
not a replacement for proposal authorization. It is a final command-free policy
gate over the complete plan artifact.

## Decision

Introduce `ExecutionPlanAuthorizer` and immutable request/result models.

The authorizer:

- consumes one `ExecutionPlanConstructionResult`;
- requires explicit caller-supplied, timezone-aware evaluation time;
- accepts explicit blocking and deferral reasons;
- validates construction and identity evidence;
- emits deterministic `AUTHORIZED`, `DEFERRED`, or `REJECTED` evidence;
- preserves plan, proposal, decision, context, construction, policy-version,
  and optional correlation identities;
- excludes wall-clock evaluation time from logical authorization identity.

Blocking reasons take precedence over deferral reasons. Only an authorized
result exposes the plan as eligible for a later scheduling boundary.

## Boundaries

Epic 10.16E does not:

- authorize the original execution proposal;
- mutate the plan;
- schedule or dispatch work;
- translate operations;
- invoke execution coordinators or gateways;
- call Home Assistant, Pentair, vendors, transports, or networks;
- actuate physical equipment.

## Consequences

PoolOS gains a deterministic final policy gate over the complete execution plan
while preserving the existing requirement that proposal authorization occurs
before plan construction. Future scheduling work can consume only explicit
plan-authorization evidence rather than inferring permission from plan
existence.
