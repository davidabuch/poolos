# ADR-048: Reevaluation Runtime Submission Boundary

## Status

Accepted and implemented for Epic 10.15L.

## Context

ADR-046 converts due reevaluation schedules into typed
`EvaluationTriggerRequest` values and explicit trigger-emission completion
evidence. ADR-047 makes the scheduling and completion inputs restart-safe.
Neither boundary defines the reviewed handoff through which an emitted request
may later enter the supervisory runtime.

Submitting directly from the due selector would combine due-time evaluation,
runtime handoff, trigger coalescing, context construction, and decision
evaluation. It would also obscure duplicate suppression and make replay depend
on hidden runtime state. The handoff therefore requires its own immutable,
side-effect-free evidence boundary.

## Decision

PoolOS introduces:

- `ReevaluationRuntimeSubmissionRequest`, an immutable wrapper around one typed
  trigger request plus trigger-result, schedule, operational-action, context,
  decision, correlation, and provenance evidence;
- `ReevaluationRuntimeSubmissionResult`, immutable accepted, rejected, or
  duplicate evidence with stable machine-readable reasons;
- `ReevaluationRuntimeSubmissionBatch`, immutable ordered batch evidence and
  explicit accepted submission identities; and
- `ReevaluationRuntimeSubmissionBoundary`, a pure validator that performs no
  runtime invocation.

Submission requests are constructed from emitted ADR-046
`ReevaluationTriggerResult` evidence. The boundary accepts one or more requests
and requires an explicit timezone-aware `submitted_at`. It sorts inputs by
trigger request time and deterministic submission identity so caller input
order does not affect results.

## Validation and outcomes

The boundary accepts only an `EXPECTED_CHANGE_REACHED` request that:

- has normal urgency and the canonical scheduled-change reason shape;
- is not future-dated relative to `submitted_at`;
- carries emitted trigger outcome and reason evidence;
- preserves trigger source, evaluation time, and trigger type;
- preserves schedule request and result identities;
- preserves operational action, context, decision, and non-empty correlation
  evidence; and
- preserves the reevaluation hint represented in the trigger reason.

Each request returns exactly one outcome:

- `ACCEPTED` with `SUBMISSION_ACCEPTED` when all evidence is valid and its
  deterministic submission identity was not accepted previously;
- `DUPLICATE` with `SUBMISSION_ALREADY_ACCEPTED` when explicit prior acceptance
  evidence already contains that identity; or
- `REJECTED` with a stable reason for unsupported trigger type, invalid trigger
  evidence, future evidence, or inconsistent provenance.

Duplicate inputs in one batch are accepted at most once. Accepted submission
identities are sorted immutable output and must be supplied explicitly on a
later replay. The boundary owns no acceptance store or mutable duplicate set.
ADR-049 persists those identities in reevaluation snapshot schema version 2.

## Identity and replay

The submission identity is SHA-256-derived from canonical JSON containing the
complete typed trigger fields, trigger-result and schedule identities,
operational correlation identities, and sorted provenance. Result and batch
identities additionally include explicit submission time, boundary identity,
outcome, reason, and acceptance evidence.

Restored ADR-047 scheduling evidence produces the same ADR-046 trigger evidence
and therefore the same submission request, ordered results, identities, and
accepted-submission output. Previously accepted identities produce duplicate
evidence rather than renewed acceptance.

ADR-046 completion and ADR-048 acceptance remain distinct evidence:

- completion records that a due trigger request was emitted;
- acceptance records that the validated request crossed this logical handoff.

Neither status proves that a runtime cycle or decision evaluation occurred.

## Runtime separation

The accepted typed requests are immutable output for a future reviewed
integration with the ADR-028 trigger coalescer. Epic 10.15L does not call that
coalescer, `PoolRuntime`, or the Decision Orchestrator. It does not construct a
`DecisionEvaluationContext`, enqueue work, publish an event, or run a cycle.

The boundary is not a queue, bus, dispatcher, publisher, worker, runtime
adapter, or persistence store.

## Safety constraints

The runtime-submission boundary:

- uses only explicit timezone-aware time;
- has no system-clock, timer, thread, async task, or background worker;
- performs no file, database, network, or platform I/O;
- imports no runtime, Decision Orchestrator, Home Assistant, Pentair, RS-485,
  HAL, delivery, or vendor implementation;
- creates, authorizes, delivers, and executes no plan or command; and
- performs no physical actuation.

## Future extension points

Future reviewed milestones may add:

- an integration that passes accepted requests to the ADR-028 coalescer;
- acknowledgement that a coalesced request entered a runtime evaluation cycle;
  or
- linkage from submission evidence to a resulting decision record.

Those extensions must preserve Decision Orchestrator authority and must not
collapse submission acceptance into decision completion.

## Consequences

- Reevaluation triggers gain one deterministic, auditable runtime handoff.
- Invalid, future, inconsistent, and repeated evidence fails closed.
- Restart replay can reproduce submission behavior without hidden state.
- The existing scheduler, due selector, persistence snapshot, coalescer,
  runtime, and orchestrator retain separate responsibilities.
- Actual runtime submission remains future work. ADR-049 makes accepted
  identities restart-safe without adding runtime integration.
