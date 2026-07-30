# ADR-016: Decision Validation and Golden Rule Verification

- **Status:** Accepted
- **Milestone:** 10.6
- **Date:** 2026-07-30

## Context

PoolOS already has deterministic simulation, reusable scenarios, accelerated soak runs, and
Home Assistant comparison tooling. The next requirement is to prove behavioral correctness:
important operating and safety rules must be expressed as repeatable scenarios with explicit
expected outcomes, and unintended changes must be visible before any live-control work.

Direct assertions scattered across tests are useful but do not provide a reusable diagnostic
contract, batch reporting, or complete-timeline regression protection.

## Decision

Introduce `poolos.validation` as a simulator-only supervisory layer.

A `DecisionValidationCase` combines one immutable `SimulationScenario` with typed
`DecisionExpectation` objects. `DecisionValidationRunner` creates a fresh simulation for each
case, executes the scenario, evaluates every expectation, and returns immutable per-check and
suite reports.

Built-in expectations cover final grid state, equipment activity and availability, body
circulation/heating/temperature, event and snapshot counts, timeline ordering, and golden
fingerprints. Numeric temperature checks may use an explicit tolerance.

Golden fingerprints are SHA-256 digests of behaviorally relevant snapshots and applied event
kinds. Volatile identifiers are excluded. They protect the complete simulated timeline while
remaining deterministic across equivalent runs.

## Safety boundary

The validation runner accepts only a simulation factory and calls only the simulation runtime.
It has no Home Assistant client, publication endpoint, HAL transport, or live equipment command
interface. Validation cannot control physical equipment.

## Consequences

- Canonical operating and safety rules can become named, tagged regression cases.
- Failures identify the exact expectation, expected value, and observed value.
- Suites distinguish behavioral failures from execution errors.
- Intentional behavior changes require deliberate expectation or golden-fingerprint updates.
- Golden files are not mandatory; fingerprints can be stored directly in code or fixtures.
