# ADR-067: End-to-End Equipment Execution Vertical Slice

- **Status:** Accepted
- **Milestone:** 10.18B
- **Date:** 2026-08-05

## Context

PoolOS now contains reviewed deterministic boundaries for operational-action validation, execution-proposal and plan requests, canonical plan construction, plan authorization, scheduling, dispatch, vendor translation, transport routing, Home Assistant delivery, acknowledgement normalization, execution receipts, and append-only execution recording.

Each boundary has focused tests, but the complete evidence chain has not yet been exercised as one vertical slice. A cross-boundary test is required before adding more execution infrastructure or live connectivity.

## Decision

Add an integration-style golden-path test for one pump-speed operation. The test begins with a canonical `REQUEST_PROPOSAL` operational action and passes the resulting evidence through every reviewed execution boundary to an injected Home Assistant executor, canonical acknowledgement, execution receipt, and in-memory execution flight recorder.

The scenario sets the pool pump speed to 2200 RPM through a mocked Home Assistant `number.set_value` service call. It verifies ordered composition, deterministic identities, correlation continuity, upstream provenance, exact service-call content, one acknowledgement, one terminal receipt, and one append-only flight record.

No new production component is introduced. The test composes existing defining-module APIs and uses no live Home Assistant instance, authentication, network connection, background task, retry, state reconciliation, or physical actuation.

## Consequences

- PoolOS gains its first tested end-to-end execution vertical slice.
- Existing boundary contracts are validated together rather than only in isolation.
- Any future live executor can target a proven service-call and receipt path.
- Successful delivery remains distinct from later observed-state verification.
