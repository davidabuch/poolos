# ADR-032: Canonical Supervisory Execution Pipeline

- Status: Accepted
- Date: 2026-07-31
- Supersedes: None

## Context

PoolOS contains two historical execution-related paths:

1. a generic `Command -> ExecutionEngine -> CommandExecutor` path used by the
   older runtime; and
2. a canonical `PoolOperation -> translation -> VendorCommand -> endpoint`
   path that preserves vendor and transport independence.

Adding supervisory execution directly to either path without clarifying their
roles would create overlapping execution authorities and make future live
actuation difficult to audit safely.

The command-free decision orchestrator, immutable evaluation contexts,
runtime-mode safety boundary, deterministic replay, restart recovery, and
Flight Recorder must remain intact.

## Decision

PoolOS will use `PoolOperation` as the canonical future actuation unit.

The supervisory execution flow will be:

```text
Decision
  -> ExecutionProposal
  -> ExecutionAuthorization
  -> ExecutionPlan
  -> ordered ExecutionStep objects
  -> PoolOperation translation and delivery
  -> independent verification
  -> ExecutionOutcome
```

The decision orchestrator will remain command-free.

The generic `Command` and `ExecutionEngine` path will remain temporarily for
backward compatibility but will not be expanded as the supervisory execution
architecture. Its eventual migration or retirement will be considered only
after the new execution pipeline is mature.

All execution during Epic 10.13 will be simulator-only. Physical Home
Assistant or Pentair delivery is explicitly prohibited and deferred to a later
epic.

Incomplete execution will not be resumed blindly after restart. PoolOS will
reconcile observations and reevaluate before creating new executable intent.

## Consequences

### Positive

- One canonical vendor-independent execution intent exists.
- Decision intelligence remains independent from delivery infrastructure.
- Authorization, delivery, and verification become separately auditable.
- Simulation can exercise the complete execution lifecycle before live control.
- Restart behavior remains conservative and deterministic.

### Costs

- The legacy generic command engine remains temporarily alongside the new
  architecture.
- A later migration is required for `PoolRuntime`.
- Additional domain artifacts must be recorded and projected.

## Epic 10.13A implementation

The first milestone defines immutable models only:

- `ExecutionProposal`
- `ExecutionAuthorization`
- `ExecutionPlan`
- `ExecutionStep`
- `StepOutcome`
- `ExecutionOutcome`
- authorization, lifecycle, and verification enums

No delivery behavior changes in this milestone.

## Epic 10.13B implementation

Proposal generation is implemented as a command-free boundary above decision orchestration. Only a current, changed, selected, recorded decision may produce an `ExecutionProposal`. Blocked contexts, retained decisions, non-selected outcomes, unrecorded decisions, and stale or superseded decisions produce explicit non-generation results.

Canonical operations are supplied explicitly to proposal generation by domain logic. Decision ranking does not contain vendor commands or transport payloads. Proposal IDs are deterministic for an accepted decision, preventing repeated evaluation of the same result from creating distinct executable intent.

This milestone does not authorize, plan, translate, deliver, verify, or resume execution.

## Epic 10.13C implementation

Authorization is implemented as a pure, command-free safety-preflight boundary.
`ExecutionAuthorizationEngine` consumes an `ExecutionProposal` plus the current
Flight Recorder decision, frozen evaluation context, runtime environment, and
active safety blockers. It returns an immutable `ExecutionAuthorization` and
performs no planning, translation, or delivery.

Three authorization dispositions are supported:

- `AUTHORIZED` for a current, recorded simulation proposal that passes every
  preflight check;
- `DEFERRED` for temporary conditions requiring fresh evaluation; and
- `REJECTED` for identity, supersession, runtime, or physical-delivery safety
  violations.

Rejection has precedence over deferral. Epic 10.13 remains simulator-only:
shadow runtime is deferred, live runtime is rejected, and any environment that
allows physical delivery is rejected. Authorization identifiers are
deterministic for an identical preflight snapshot, preserving replay and audit
semantics.

This milestone does not construct execution plans, translate operations,
deliver commands, verify observations, or invoke Home Assistant or Pentair.

## Epic 10.13D implementation

Deterministic plan construction is implemented as a pure boundary between
successful authorization and future execution coordination.
`DeterministicExecutionPlanBuilder` consumes a matching authorized proposal and
one explicit `ExecutionStepSpecification` for every canonical operation. It
returns either an immutable `ExecutionPlan` or an explicit rejected build
result.

The proposal remains authoritative for operation order. Step specifications
supply preconditions, expected observations, verification requirements, and
metadata but cannot reorder or replace operations. Plans require contiguous
step numbering, unique step and operation identifiers, and deterministic plan
and step identifiers.

Verification-required steps must state their expected observations. Planning
facts used to derive deterministic identifiers must be JSON-serializable.
Unauthorized or mismatched authorizations, missing, duplicate, or unknown step
specifications, and authorization timestamps preceding proposal creation are
rejected before a plan exists.

This milestone is data-only. It does not translate `PoolOperation` objects,
deliver simulator commands, verify observations, invoke Home Assistant or
Pentair, or permit physical actuation.

## Epic 10.13E implementation

The supervisory execution lifecycle is governed by one authoritative pure
state machine. `ExecutionStateMachine` defines legal transitions and returns
immutable transition results without coordinating execution or contacting any
delivery system.

The successful lifecycle is:

```text
AUTHORIZED -> PLANNED -> EXECUTING -> DELIVERING -> DELIVERED
           -> VERIFYING -> VERIFIED -> COMPLETED
```

When verification is not required, `DELIVERED -> VERIFIED` is permitted. All
successful lifecycles still end at `COMPLETED`.

`REJECTED`, `FAILED`, `TIMED_OUT`, `ABORTED`, `SUPERSEDED`, and `COMPLETED` are
terminal. A terminal lifecycle cannot resume. Illegal, duplicate, stale-time,
and post-terminal transition requests are rejected without mutating state.

Every accepted transition creates an immutable, deterministic
`ExecutionStateTransition`. `ExecutionLifecycle` retains the accepted history
and validates that it is plan-consistent, chronologically ordered, and status
contiguous. These artifacts establish the audit boundary required by future
execution coordination, Flight Recorder persistence, diagnostics, replay, and
restart reconciliation.

This milestone does not coordinate plan steps, translate operations, deliver
simulator commands, verify observations, invoke Home Assistant or Pentair, or
permit physical actuation.

## Epic 10.13F implementation

Execution coordination is implemented as a thin pure layer above
`ExecutionPlan` and `ExecutionStateMachine`. `ExecutionCoordinator` admits an
authorized plan, records the transition to `PLANNED`, starts coordination by
recording the transition to `EXECUTING`, and selects exactly one current step.

An immutable `ExecutionCoordinationSession` stores the lifecycle, current step
cursor, completed step identifiers, stop state, and deterministic coordination
events. A step cursor advances only after an explicit external completion signal
for the currently selected step. Out-of-order, duplicate, cross-plan,
backdated, terminal, and post-stop requests are rejected without mutation.

A completion signal is not a delivery receipt or verification result. When all
steps have received completion signals, the coordinator stops with
`plan_steps_exhausted` while the lifecycle remains `EXECUTING`. Future delivery
and verification milestones are solely responsible for advancing the lifecycle
through delivery, verification, and completion states.

This milestone does not translate operations, create vendor commands, contact
the simulator, verify observations, invoke Home Assistant or Pentair, perform
physical actuation, or resume incomplete work after restart.

## Epic 10.13G implementation

Execution verification is implemented as a pure typed-observation evaluation
boundary. `ExecutionVerificationEngine` consumes one immutable `ExecutionStep`,
an `ObservationStore`, explicit timing and freshness policy, required source
identity, accepted quality levels, and a minimum confidence threshold. It
returns immutable per-observation evidence and one aggregate verification
result.

The engine reuses canonical `PoolObservation` freshness, provenance, quality,
confidence, and store-selection semantics. It does not infer success from a
delivery receipt and does not mutate the execution coordinator or state
machine. In simulation, only matching simulated observations may satisfy the
verification request.

Aggregate results distinguish `VERIFIED`, `FAILED`, `PARTIAL`, `PENDING`,
`TIMED_OUT`, and `NOT_REQUIRED`. Missing, stale, future-dated, unusable, and
low-confidence evidence cannot be treated as success. Verification IDs are
deterministic for the same plan, step, evaluation time, deadline, metadata, and
evidence snapshot.

This milestone does not translate operations, create or deliver vendor
commands, contact simulator endpoints, invoke Home Assistant or Pentair,
perform physical actuation, advance lifecycle state, or resume incomplete work
after restart.

## Epic 10.13H implementation

Execution history is persisted through one append-only supervisory recording
boundary. `InMemoryExecutionFlightRecorder` records the immutable artifacts
created by proposal generation, authorization, deterministic planning,
lifecycle transition, coordination, verification, and outcome modeling. It
does not replace those artifacts with a parallel logging model.

Every `ExecutionFlightRecord` has a contiguous sequence, deterministic record
identity, artifact identity, event timestamp, and complete available lineage.
A stable execution-session identity begins when the plan is recorded and is
shared by all later plan-scoped records. `ExecutionTimeline` validates unique
records and artifacts, contiguous sequence, and chronological ordering.

The recorder enforces causal append order and identity consistency. It rejects
missing prerequisite artifacts, mismatched proposal, authorization, decision,
or context identities, unknown step references, duplicate or backdated facts,
and appends after a completed outcome. Complete typed artifacts remain directly
recoverable, and deterministic JSON export preserves full snapshots for future
durable storage, replay, diagnostics, restart reconciliation, and projection.

This milestone is recording-only. It does not coordinate plan steps, translate
operations, deliver simulator commands, verify observations, invoke Home
Assistant or Pentair, perform physical actuation, or resume execution after a
restart.

## Epic 10.13I implementation

Restart recovery for execution is a pure interpretation boundary above the
append-only execution Flight Recorder. `ExecutionRestartRecoveryEngine`
validates a recorded history snapshot, selects the requested or latest proposal
lineage, classifies its interruption point, and returns immutable
recommendations. It does not restore execution authority.

The governing invariant is:

```text
execution history != execution authority
```

No assessment can permit resumption. Interrupted authorized work is marked for
supersession and fresh reevaluation. Completed outcomes require no action;
terminal failures recommend reevaluation. Deferred and rejected authorizations
remain distinct. Invalid sequence, future records, missing proposal lineage,
cross-plan or cross-session facts, and other causal inconsistencies are
classified as corrupt and require corruption recording plus operator review.

Recovery does not mutate history, reconstruct a coordinator cursor, resend an
operation, contact a simulator or external system, invoke Home Assistant or
Pentair, or perform physical actuation. Actual-state reconciliation and new
proposal generation remain later runtime responsibilities.

## Epic 10.13J addendum: permanent golden scenarios

The canonical execution pipeline SHALL maintain a stable catalog of permanent
end-to-end supervisory scenarios. The catalog must cover success,
authorization refusal, verification failure and timeout, interruption,
completed recovery, and corrupt history.

Golden scenarios assert externally observable execution facts rather than
private implementation details. They must remain deterministic, must use only
canonical execution and observation artifacts, and must not introduce command
delivery or hardware collaborators.

The permanent catalog is `poolos.execution_golden_scenarios`, with executable
coverage in `tests/test_execution_golden_scenarios.py`.
