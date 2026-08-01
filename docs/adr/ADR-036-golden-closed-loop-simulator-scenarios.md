# ADR-036: Golden Closed-Loop Simulator Scenarios

## Status

Accepted and implemented for Epic 10.14F.

## Context

PoolOS already had a permanent golden-scenario catalog for the supervisory
execution framework. That catalog intentionally stopped before command
delivery. Epic 10.14A-E added simulator-only delivery, immutable receipts,
closed-loop observation verification, and deterministic fault recovery.

A second set of permanent scenarios is therefore required to protect the full
simulator execution pipeline without changing the scope of the earlier
supervisory catalog.

## Decision

PoolOS provides a distinct closed-loop simulator scenario catalog and one
reusable deterministic runner.

The runner composes the actual production boundaries:

1. immutable execution plan;
2. execution coordinator and executing plan session;
3. canonical operation translation;
4. simulator-only execution gateway;
5. simulator delivery engine;
6. deterministic simulated equipment state;
7. typed observation store;
8. verification engine;
9. optional simulator fault plan;
10. coordinator advancement and plan completion.

The permanent catalog covers:

- single-step success;
- multi-step success;
- delivery rejection;
- delivery failure;
- delivery timeout;
- missing observation;
- stale observation;
- mismatched observation;
- verification timeout;
- deterministic replay equivalence.

Golden assertions target externally meaningful outcomes: plan disposition,
plan lifecycle, completed step identities, terminal step lifecycle, command
count, immutable fault records, recovery recommendations, and a deterministic
outcome fingerprint.

## Lifecycle invariant

The runner preserves two independent lifecycles.

Plan lifecycle:

```text
AUTHORIZED -> PLANNED -> EXECUTING -> COMPLETED
```

Step lifecycle:

```text
PENDING -> DELIVERING -> DELIVERED -> VERIFYING -> VERIFIED
```

A multi-step plan remains `EXECUTING` while intermediate steps become
`VERIFIED`. The plan reaches `COMPLETED` only after the final step is verified.
A failed step never advances the coordinator.

## Safety consequences

The runner constructs only a `SIMULATION` runtime environment and admits only a
simulator endpoint. It contains no Home Assistant service client, Pentair
physical endpoint, RS-485 transport, or physical equipment actuation path.
Fault scenarios do not retry automatically.

## Consequences

- The earlier supervisory golden catalog remains intact.
- Closed-loop behavior has a permanent regression boundary.
- Scenario implementations are reusable outside pytest.
- Deterministic replay can be checked using stable outcome fingerprints.
- New simulator execution behavior should extend this catalog instead of
  creating isolated end-to-end fixtures.
