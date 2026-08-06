# ADR-056: Deterministic Execution Proposal Boundary

## Status

Accepted for Epic 10.16B.

## Context

Epic 10.16A composes supervisory evaluation, canonical operational-action
validation, and safe non-hardware adaptation. Actions requesting a new execution
proposal are intentionally rejected by the non-hardware adapter because no
reviewed execution-proposal boundary existed.

PoolOS needs a narrow next boundary that can acknowledge a validated
`REQUEST_PROPOSAL` action without creating an execution plan or crossing into
execution, scheduling, delivery, Home Assistant, vendor, network, or physical
control behavior.

## Decision

Introduce one immutable `ExecutionProposalBoundary`.

The boundary consumes only an accepted `OperationalActionPipelineResult` and
requires:

- action `REQUEST_PROPOSAL`;
- target `EXECUTION_PROPOSAL_BOUNDARY`;
- canonical boundary name `execution_proposal_boundary`;
- preserved accepted action identity;
- a non-empty decision identity;
- no existing plan identity.

A valid action produces one deterministic `ExecutionProposalRequest` containing
proposal-request identity, source action identity, context identity, decision
identity, optional correlation identity, reason evidence, and immutable
provenance.

Invalid or unsupported evidence produces an immutable rejected result with a
stable reason code and no proposal request.

## Boundaries

Epic 10.16B does not:

- generate alternatives or choose equipment commands;
- create, authorize, submit, schedule, retain, cancel, replace, or execute a plan;
- mutate runtime or persistent state;
- perform retries, queueing, polling, or background work;
- invoke Home Assistant, Pentair, vendor transports, networks, or hardware;
- actuate physical equipment.

## Consequences

PoolOS gains a deterministic handoff from validated supervisory intent into
future proposal construction while preserving the separation between reasoning
and execution. A later milestone may consume `ExecutionProposalRequest` to build
reviewed proposal evidence, but ADR-056 authorizes no plan creation or actuation.
