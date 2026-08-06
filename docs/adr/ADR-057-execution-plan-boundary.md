# ADR-057: Execution Plan Request Boundary

## Status

Accepted for Epic 10.16C.

## Context

Epic 10.16B introduced a deterministic execution proposal boundary that converts one validated `REQUEST_PROPOSAL` operational action into immutable `ExecutionProposalRequest` evidence. PoolOS still requires a separate boundary between an accepted proposal request and any future execution-plan construction.

Creating a plan directly inside the proposal boundary would combine routing validation, proposal acceptance, plan construction, and eventual execution concerns. That would weaken provenance and make later authorization and safety review harder to isolate.

## Decision

Introduce one command-free `ExecutionPlanBoundary`.

The boundary consumes one `ExecutionProposalBoundaryResult` and:

1. requires accepted proposal-boundary evidence;
2. verifies proposal, action, context, and decision identity consistency;
3. derives one deterministic `ExecutionPlanRequest` identity;
4. preserves proposal result, proposal request, action, context, decision, and correlation identities;
5. emits immutable accepted or rejected boundary evidence with stable reason codes.

The boundary creates request evidence only. It does not create an `ExecutionPlan`.

## Boundaries

Epic 10.16C does not:

- generate execution steps;
- construct, validate, authorize, schedule, submit, mutate, cancel, replace, or execute an execution plan;
- invoke the execution coordinator or simulator execution engine;
- persist or recover plan state;
- deliver commands;
- call Home Assistant, Pentair, vendors, transports, or networks;
- actuate physical equipment.

## Consequences

PoolOS gains an explicit, deterministic handoff between accepted proposal evidence and future plan construction. Downstream work can consume one immutable request without reinterpreting supervisory routing or proposal acceptance.

The next milestone may define deterministic execution-plan construction from this request while preserving a separate authorization boundary.
