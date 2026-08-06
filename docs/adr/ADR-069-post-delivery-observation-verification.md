# ADR-069: Post-Delivery Observation Verification

- **Status:** Accepted
- **Milestone:** 10.19B
- **Date:** 2026-08-05

## Context

PoolOS can now deliver a Home Assistant service call through the production REST
executor and record canonical delivery acknowledgement and receipt evidence. A
successful service call proves only that Home Assistant accepted the request; it
does not prove that the intended equipment state was subsequently observed.

PoolOS already contains a canonical, observation-store-based execution
verification engine and a Home Assistant observation bridge. The missing piece
is a reviewed boundary that connects completed delivery evidence to those
existing components without introducing polling, retry, or reconciliation.

## Decision

Add a post-delivery observation verification boundary that:

- accepts only a completed execution receipt;
- validates available plan and step identity provenance;
- ingests explicit Home Assistant state snapshots through the existing binding
  profile and observation bridge;
- delegates expected-value comparison, freshness, timeout, and deterministic
  verification identity to the existing execution verification engine;
- classifies verified, pending, mismatched, unavailable, stale, timed-out, and
  rejected outcomes as immutable evidence;
- preserves receipt, verification, correlation, plan, and step provenance.

The boundary performs one evaluation over caller-supplied snapshots. It does not
poll Home Assistant, subscribe to events, retry commands, reconcile state,
advance an execution coordinator, or actuate equipment.

## Consequences

- Successful delivery and observed-state verification remain separate auditable
  lifecycle stages.
- Existing generic verification and Home Assistant observation components are
  reused rather than duplicated.
- A future runtime may repeatedly invoke this pure boundary as new observations
  arrive, but that lifecycle is outside this milestone.
- Recovery and reconciliation remain deferred until verification evidence is
  proven in production-oriented vertical slices.
