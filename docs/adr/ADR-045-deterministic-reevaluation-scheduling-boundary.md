# ADR-045: Deterministic Reevaluation Scheduling Boundary

## Status

Accepted and implemented for Epic 10.15I.

## Context

ADR-044 introduced the first downstream operational-action adapter. A validated
reevaluation action produces an immutable deferred receipt, but the adapter
deliberately does not schedule work. PoolOS now needs a narrow boundary that can
record that reevaluation for a future time without invoking the decision
runtime or crossing into execution and hardware delivery.

The existing `Scheduler` coordinates immutable execution-plan steps. Reusing it
for supervisory reevaluation would combine distinct lifecycles and make a
reevaluation request appear executable. A dedicated boundary keeps decision
reevaluation separate from plan execution.

## Decision

PoolOS introduces:

- `ReevaluationScheduleRequest`, an immutable request derived from one
  downstream receipt plus explicit caller-supplied times;
- `ReevaluationScheduleResult`, immutable scheduling evidence;
- `DeterministicReevaluationScheduler`, an in-memory recording and cancellation
  authority for reevaluation requests only;
- explicit `SCHEDULED`, `REJECTED`, `DUPLICATE`, and `CANCELLED` outcomes;
- stable machine-readable outcome reasons and immutable provenance.

The scheduler accepts only receipts that are deferred for the canonical
`REEVALUATION_SCHEDULER` route. It revalidates the receipt, pipeline acceptance,
action identity, target, boundary name, and non-empty reevaluation hint before
recording a request.

The reevaluation hint remains descriptive provenance. Epic 10.15I does not parse
the hint into a time. The caller must supply `requested_at`, `scheduled_for`, and
the processing or cancellation time explicitly.

## Deterministic identity and time

The request ID is a SHA-256-derived identifier over canonical JSON containing:

- downstream receipt identity;
- canonical action identity;
- reevaluation hint;
- request time;
- scheduled time.

The result ID additionally includes scheduler identity, processing time,
outcome, reason, and cancellation reason. Replaying the same operation against
the same initial state produces the same request and result identities.

Every timestamp must be timezone-aware. Scheduling fails closed when processing
precedes the request or when the scheduled time precedes the request or current
processing time. No system clock, random UUID, or implicit local timezone is
used.

## Lifecycle behavior

- The first valid request is recorded as `SCHEDULED`.
- Reusing a recorded deterministic request ID is `DUPLICATE`.
- Invalid receipts, routes, or time ordering are `REJECTED` and are not stored.
- A recorded request may be replaced by an immutable `CANCELLED` record.
- Cancelling an unknown request is `REJECTED`.
- Repeated cancellation is `DUPLICATE`.
- Cancellation never invokes evaluation or execution.

Current records are held in memory and returned in deterministic request-ID
order. Due-request polling and runtime trigger publication remain outside this
milestone. ADR-047 adds a separate immutable persistence and restart-recovery
boundary for the current records without changing scheduler behavior.

## Safety constraints

The reevaluation scheduling boundary:

- consumes no raw observation, forecast, policy, plan, vendor command, or
  hardware endpoint;
- does not evaluate a decision or generate a new operational action;
- does not create, authorize, mutate, or execute a plan;
- does not invoke Home Assistant, Pentair, RS-485, HAL, delivery, or networking;
- does not contact or actuate physical equipment.

The scheduler records intent only. A future component that converts a due
record into an `EvaluationTriggerRequest` requires separate review and must
preserve decision-orchestrator authority and trigger coalescing from ADR-028.

## Future extension points

Future milestones may add:

- an immutable persistence and restart-recovery store;
- deterministic selection of due requests at an explicitly supplied time;
- conversion of due records into typed scheduled evaluation triggers;
- completion or supersession evidence after a reevaluation cycle.

None of those extensions may introduce vendor delivery or physical actuation.

ADR-046 implements deterministic due-request selection and typed trigger
conversion. ADR-047 implements persistent scheduling and completion evidence;
runtime submission remains deferred.

## Consequences

- Deferred reevaluation gains an explicit, testable lifecycle.
- Request, result, timing, and cancellation evidence are deterministic.
- Duplicate scheduling fails closed without overwriting the original record.
- Execution-plan scheduling remains a separate architecture.
- The scheduler itself remains in-memory; ADR-047 makes its immutable current
  evidence restart-safe through a separate pure snapshot boundary.
