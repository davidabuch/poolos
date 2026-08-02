# ADR-047: Persistent Reevaluation State and Restart Recovery

## Status

Accepted and implemented for Epic 10.15K.

## Context

ADR-045 records immutable current reevaluation schedule evidence in memory.
ADR-046 consumes those records together with explicit completed request
identities so a due request emits at most once. Both inputs are deterministic,
but neither survives a process restart unless an external caller preserves and
reconstructs them.

Restart recovery must not turn persistence into a runtime, timer, execution
path, or stale command replay mechanism. It must preserve the exact evidence
needed by the existing pure due-trigger boundary and reject incomplete or
inconsistent state before any trigger can be emitted.

## Decision

PoolOS introduces one `ReevaluationStatePersistenceBoundary` and one immutable
`ReevaluationStateSnapshot`.

The boundary:

1. captures the current `SCHEDULED` and `CANCELLED`
   `ReevaluationScheduleResult` records;
2. captures the sorted identities of requests already completed by trigger
   emission;
3. requires an explicit timezone-aware `captured_at` value;
4. normalizes schedule and completion evidence into deterministic order;
5. serializes the complete typed evidence as compact canonical JSON;
6. restores equivalent immutable models after restart; and
7. rejects malformed, unsupported, or inconsistent state fail-closed.

The snapshot schema was introduced at version 1. ADR-049 evolves it to version
2 by adding accepted ADR-048 runtime-submission identities. A deterministic
snapshot ID is derived from the canonical schema, capture time, complete
scheduling evidence, provenance, completion identities, and accepted submission
identities. Restore verifies that identity after reconstructing the typed
models.

The boundary performs no file, database, network, or platform I/O. A host may
store the serialized value using an independently reviewed adapter. This keeps
the PoolOS core vendor-neutral and avoids overlapping store, repository,
snapshot, and recovery abstractions.

## Recovery invariants

Restore accepts only state that satisfies all of the following:

- the current supported schema version is present;
- all timestamps are explicit and timezone-aware;
- schedule records have unique request identities and deterministic order;
- only current scheduled or cancelled evidence is present;
- processing does not occur after capture or before the original request;
- each record still contains a validated deferred reevaluation route;
- completed identities are unique, sorted, and reference persisted schedules;
- cancelled schedules never carry completion evidence; and
- completed schedules were due by the snapshot capture time.

The restored schedule records and completion identities are passed directly to
`DueReevaluationTriggerBoundary`. Completed requests therefore remain
duplicates, cancelled requests remain cancelled, and future requests remain
not due until a caller supplies a sufficiently late `as_of` value.

When restored evidence produces an emitted trigger, ADR-048 can reconstruct the
same deterministic runtime-submission request. Accepted submission identities
remain separate explicit evidence. ADR-049 persists them in schema version 2
without merging them with trigger-emission completion identities.

Schema version 1 is rejected after ADR-049 because treating absent accepted
submission evidence as an empty set could cause duplicate acceptance after
restart.

## Determinism and replay

Serialization uses sorted keys, compact separators, explicit enum values,
ISO-8601 timestamps, deterministic record ordering, and sorted string maps.
Input order does not affect the snapshot or serialized bytes. Replaying the
same explicit `as_of` against original or restored evidence produces equivalent
trigger batches and identities.

No system clock, background timer, random identifier, or hidden mutable state
participates in capture, serialization, restore, or replay.

## Safety constraints

The persistence and recovery boundary:

- does not invoke the Decision Orchestrator;
- does not submit `EvaluationTriggerRequest` values to the runtime;
- does not build evaluation contexts or run decision cycles;
- does not create, mutate, authorize, deliver, or execute plans or commands;
- imports no Home Assistant, Pentair, RS-485, HAL, delivery, vendor, or network
  implementation;
- restores no equipment state or actuator intent; and
- performs no physical actuation.

## Future extension points

Future reviewed milestones may add:

- a host-owned file, database, or platform storage adapter for the canonical
  serialized snapshot;
- transactional persistence coordination around schedule or completion
  updates;
- runtime coalescing and acknowledgement for typed trigger requests; or
- migrations from explicitly supported future schema versions.

Runtime publication and storage I/O remain outside Epic 10.15K.

## Consequences

- Reevaluation scheduling and duplicate-suppression evidence are restart-safe.
- Recovery reconstructs immutable state rather than replaying commands or
  restoring runtime intent.
- Corrupt or incompatible state cannot silently emit reevaluation triggers.
- The PoolOS core remains deterministic and independent of storage vendors.
- A durable host adapter and transactional write policy remain future work.
