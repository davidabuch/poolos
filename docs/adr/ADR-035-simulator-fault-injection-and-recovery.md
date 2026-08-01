# ADR-035: Deterministic Simulator Fault Injection and Recovery

## Status

Accepted.

## Context

Epic 10.14D established a closed-loop simulator path in which a plan step is
delivered, simulated state is mutated, canonical observations are published,
verification is evaluated, and the coordinator advances only after successful
verification.

Before broader simulator scenarios can be trusted, PoolOS needs a repeatable
way to exercise delivery and observation failures. Fault behavior must not be
implemented as ad-hoc mocks scattered through tests, and recovery must not
silently retry or restore execution authority.

## Decision

PoolOS defines an immutable `SimulatorFaultPlan` made of deterministic
`SimulatorFaultRule` values. Rules target one execution step and one supported
fault kind:

- delivery rejected;
- delivery failed;
- delivery timed out;
- observation missing;
- observation stale;
- observation mismatch;
- verification timeout.

The closed-loop simulator consumes the plan at explicit delivery and
observation boundaries. Every injected fault produces an immutable,
deterministically identified `SimulatorFaultRecord` with non-actuating recovery
recommendations.

Delivery faults terminate the step and plan and require operator review.
Observation and verification faults terminate the step and plan and recommend
fresh observation and reevaluation. No fault path grants permission to resume,
retry, or skip a failed step.

## Safety invariants

- Fault injection is available only inside the simulator closed loop.
- No Home Assistant, physical Pentair, or live endpoint is introduced.
- Injected delivery faults do not call the configured simulator endpoint.
- Verification faults never advance the coordinator cursor.
- Recovery recommendations are descriptive; they are not execution authority.
- Automatic retries and blind restart continuation remain prohibited.
- Fault records are immutable and deterministic for the same rule and time.

## Consequences

The simulator can now exercise important failure paths repeatably while
preserving the same lifecycle and verification boundaries as normal execution.
The resulting records can support diagnostics, future fault dashboards, and
golden simulator scenarios without embedding recovery policy in the delivery
or coordinator layers.
