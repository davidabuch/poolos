# ADR-049: Persistent Runtime-Submission Identities

## Status

Accepted and implemented for Epic 10.15M.

## Context

ADR-047 version 1 persists current reevaluation schedules and the request
identities completed by ADR-046 trigger emission. ADR-048 adds a distinct
side-effect-free submission boundary whose accepted submission identities must
be supplied explicitly for duplicate suppression.

Keeping accepted submission identities only in process memory would allow a
previously accepted trigger to be accepted again after restart. Connecting the
submission boundary to the trigger coalescer would not solve that evidence gap
and would prematurely combine persistence with runtime integration.

## Decision

PoolOS evolves `ReevaluationStateSnapshot` to schema version 2. The existing
snapshot and persistence boundary now include three separate immutable evidence
collections:

1. current scheduled or cancelled reevaluation records;
2. completed reevaluation request identities from ADR-046 trigger emission;
3. accepted runtime-submission identities from ADR-048.

`ReevaluationStatePersistenceBoundary.capture` accepts explicit
`accepted_submission_ids`, normalizes them into sorted order, and includes them
in the deterministic snapshot identity and canonical JSON. Restore reconstructs
the same immutable tuple for direct use as ADR-048 duplicate-suppression input.

No new store, repository, recovery service, queue, publisher, or runtime adapter
is introduced.

## Schema and fail-closed behavior

Schema version 2 adds the required `accepted_submission_ids` JSON field.
Accepted identities must:

- be non-empty and unique;
- appear in deterministic sorted order after normalization;
- use the canonical `reevaluation-runtime-submission-` prefix followed by the
  24-character lowercase hexadecimal digest produced by ADR-048; and
- not outnumber completed reevaluation request identities.

The count invariant preserves the lifecycle ordering that a submission can be
accepted only after a due trigger was emitted. Submission identities remain
opaque because schema version 2 intentionally persists identities rather than
duplicating complete ADR-048 request and result models.

Version 1 snapshots are rejected instead of being silently upgraded with an
empty acceptance set. Such an upgrade could erase real acceptance evidence and
allow duplicate acceptance after restart. Hosts must create a fresh version 2
snapshot from authoritative scheduling, emission-completion, and submission
acceptance evidence.

Missing, malformed, duplicate, noncanonical, or impossible acceptance evidence
is rejected before restore succeeds.

## Restart and replay

After restart:

1. restore the version 2 reevaluation snapshot;
2. supply `completed_request_ids` to ADR-046 due evaluation;
3. supply `accepted_submission_ids` to ADR-048 submission validation when
   replaying equivalent emitted trigger evidence.

Previously accepted submission identities produce `DUPLICATE` evidence rather
than renewed `ACCEPTED` evidence. Snapshot serialization and identity remain
independent of caller input ordering.

ADR-046 completion and ADR-048 acceptance remain distinct. Persisting both does
not assert that trigger coalescing, context construction, a runtime cycle, or a
decision evaluation occurred.

## Safety constraints

Schema version 2:

- performs no runtime or trigger-coalescer invocation;
- constructs no evaluation context and runs no decision cycle;
- introduces no clock polling, timer, thread, worker, or background task;
- performs no file, database, network, Home Assistant, vendor, HAL, delivery,
  or equipment operation; and
- creates, authorizes, delivers, or executes no command.

Time remains explicit and timezone-aware through the existing snapshot
`captured_at` contract.

## Consequences

- ADR-048 duplicate suppression is restart-safe.
- Snapshot identity covers all three reevaluation lifecycle evidence sets.
- Version 1 is intentionally incompatible and fails closed.
- Accepted submission identity remains evidence of logical handoff only.
- Trigger coalescer and runtime integration remain future reviewed milestones.
