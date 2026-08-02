# ADR-046: Due Reevaluation Trigger Boundary

## Status

Accepted and implemented for Epic 10.15J.

## Context

ADR-045 established deterministic, in-memory recording and cancellation of
reevaluation requests. It intentionally stopped before selecting due records or
creating a runtime trigger. PoolOS now needs a reviewed bridge from immutable
scheduling evidence to the typed trigger model established by ADR-028.

Calling the Decision Orchestrator directly from the scheduler would combine
time selection, trigger publication, context construction, and decision
evaluation. It would also make replay depend on hidden scheduler state. The
bridge must therefore emit trigger evidence without running a decision cycle.

## Decision

PoolOS introduces `DueReevaluationTriggerBoundary`. It consumes:

- a tuple of immutable `ReevaluationScheduleResult` records;
- one explicit timezone-aware `as_of` time;
- immutable identities for requests completed by prior trigger emission.

It returns one immutable `DueReevaluationTriggerBatch` containing ordered
`ReevaluationTriggerResult` values, typed `EvaluationTriggerRequest` values for
due work, and updated completion evidence.

Records are sorted by scheduled time, request identity, and schedule-result
identity. Input order therefore does not affect the batch or emitted trigger
order.

## Trigger semantics

A valid due schedule emits:

```text
EvaluationTriggerRequest(
    trigger=EXPECTED_CHANGE_REACHED,
    requested_at=as_of,
    urgency=NORMAL,
    source="poolos.due_reevaluation_trigger_boundary",
)
```

`EXPECTED_CHANGE_REACHED` is used because the original operational disposition
deferred reevaluation until an anticipated change. The trigger reason preserves
the descriptive reevaluation hint. The boundary does not parse the hint or use
it as the scheduling time.

The typed request is evidence for the existing trigger-coalescing boundary. It
is not submitted to a runtime and does not invoke the Decision Orchestrator in
Epic 10.15J.

## Outcomes and completion

Each schedule record receives one explicit outcome:

- `EMITTED` when a valid schedule is due and has not been completed;
- `NOT_DUE` when its scheduled time is later than `as_of`;
- `CANCELLED` when current scheduling evidence is cancelled;
- `DUPLICATE` when its request identity is already complete;
- `REJECTED` for invalid scheduling outcomes or evidence processed after
  `as_of`.

Emitted request identities are added to sorted immutable completion evidence.
Duplicate input records therefore emit at most one typed trigger. Cancelled,
not-due, rejected, and duplicate records never emit a trigger and never add a
completion identity.

Completion evidence is explicit input and output rather than hidden mutable
state. ADR-047 persists that evidence together with current scheduling records
and restores both as equivalent immutable inputs after restart.

## Deterministic identity and provenance

Every result receives a SHA-256-derived emission ID over canonical schedule,
time, outcome, reason, completion, boundary, and trigger evidence. The batch ID
is derived from the explicit `as_of`, boundary identity, initial completion
evidence, and ordered result identities.

Trigger results preserve downstream action, scheduling, context, decision,
correlation, hint, and timing diagnostics. Replaying the same immutable inputs
produces the same result order, completion set, trigger requests, and IDs.

## Safety constraints

The due trigger boundary:

- does not mutate the reevaluation scheduler;
- does not poll a system clock or run a background timer;
- does not build an evaluation context or evaluate a decision;
- does not invoke the Decision Orchestrator or runtime;
- does not create, authorize, mutate, or execute a plan;
- imports no Home Assistant, Pentair, RS-485, HAL, delivery, vendor, or network
  implementation;
- performs no physical actuation.

## Future extension points

Future milestones may add:

- a runtime-facing publisher that submits typed requests to the existing
  trigger coalescer;
- acknowledgement that an emitted trigger was accepted into an evaluation
  cycle;
- completion or supersession evidence tied to the resulting decision record.

Runtime submission must remain separate from due selection and must preserve
trigger coalescing, evaluation-context construction, and Decision Orchestrator
authority.

ADR-047 implements persistent completion and scheduling evidence without
submitting the typed requests or introducing storage I/O in the PoolOS core.

## Consequences

- Due reevaluations become deterministic typed trigger requests.
- Cancelled, invalid, future, and completed work fails closed.
- Duplicate records cannot emit duplicate triggers within the same completion
  evidence chain.
- Replay requires no hidden clock or mutable boundary state.
- Actual runtime submission and decision evaluation remain future work.
