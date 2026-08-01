# PoolOS Supervisory Execution Pipeline

## Status

Epic 10.13 establishes the execution architecture without enabling live
actuation. Epic 10.13A defines immutable execution-domain models. Epic 10.13B adds
command-free proposal generation from current, changed, recorded decisions.

PoolOS remains command-free at the decision boundary and continues to operate
within this safety envelope:

```text
OBSERVE -> EVALUATE -> DECIDE -> EXPLAIN -> RECORD -> PUBLISH
```

The execution work introduced by Epic 10.13 is additive and initially
simulation-only:

```text
recorded decision
  -> execution proposal
  -> authorization
  -> deterministic execution plan
  -> canonical PoolOperation steps
  -> simulated delivery
  -> independent verification
  -> execution outcome
```

## Canonical boundaries

### Decision orchestration

The decision orchestrator evaluates, stabilizes, explains, records, and
publishes decisions. It does not translate or deliver commands.

### Execution proposal

An `ExecutionProposal` references the recorded decision and frozen evaluation
context that produced it. It carries one or more canonical `PoolOperation`
objects, an objective, a reason, and an expected final state.

A proposal is intent, not permission.

### Authorization

`ExecutionAuthorization` records whether a proposal may proceed. Authorization
is explicit and immutable. A rejected authorization must identify at least one
blocking reason.

Future authorization policy will consider decision currency, control
authority, runtime mode, safety constraints, endpoint class, and context age.
Physical delivery remains prohibited throughout Epic 10.13.

### Execution plan

An `ExecutionPlan` is a deterministic ordered sequence of `ExecutionStep`
objects. Every step contains exactly one canonical `PoolOperation`. Plans do
not contain Home Assistant entity IDs, Pentair commands, transport payloads, or
other vendor-specific delivery details.

### Delivery and verification

Delivery acceptance and state verification are separate facts. `StepOutcome`
therefore records a delivery lifecycle status and an independent
`VerificationStatus`.

A delivered command is not considered verified until the expected observation
is confirmed.

### Execution outcome

`ExecutionOutcome` is the immutable supervisory result for a complete plan. It
references the proposal, decision, and evaluation context, and contains the
step outcomes produced during execution.

## Runtime and restart safety

Epic 10.13 does not permit physical delivery. Simulation is the only execution
backend planned for this epic.

Incomplete execution must not be blindly resumed after restart. Restart
recovery will reconcile current observations, reevaluate the system, and create
a new proposal when work is still required.

## Legacy execution path

The existing generic `Command` and `ExecutionEngine` path remains temporarily
for backward compatibility with the older runtime. It is not the canonical
future execution architecture and must not receive new supervisory execution
responsibilities.

The canonical future actuation unit is `PoolOperation`.

## Epic 10.13B proposal-generation rules

`ExecutionProposalGenerator` consumes a `DecisionOrchestrationResult` and
canonical operations supplied explicitly by domain logic. Proposal generation
is deterministic and does not authorize or execute anything.

A proposal is generated only when all of the following are true:

- orchestration completed successfully;
- decision stability accepted a changed decision;
- the decision outcome selected an alternative;
- the accepted decision has a current Flight Recorder record;
- the orchestration active record, decision record, and stability result
  identify the same decision; and
- at least one canonical `PoolOperation` is supplied.

No proposal is generated for blocked contexts, retained decisions, no-action
or deferred decisions, unrecorded decisions, or stale/superseded decisions.
Repeating generation for the same accepted decision produces the same
deterministic proposal identifier.

Operation derivation remains outside decision ranking. The request boundary
accepts canonical `PoolOperation` objects only; Home Assistant services,
Pentair commands, and transport payloads remain prohibited.

## Epic 10.13A scope

Epic 10.13A adds only:

- immutable execution-domain models;
- validation and lifecycle invariants;
- public package exports;
- tests and architectural documentation.

It does not add:

- proposal generation;
- authorization policy;
- execution coordination;
- command translation or delivery;
- Home Assistant service calls;
- Pentair network calls;
- physical endpoint support;
- restart resumption.

## Epic 10.13B scope

Epic 10.13B adds:

- immutable proposal-generation requests and results;
- deterministic proposal identifiers;
- current-decision and recording checks;
- explicit non-generation dispositions; and
- tests proving blocked, retained, unrecorded, non-actionable, and stale
  decisions do not produce proposals.

It does not add authorization, execution planning, translation, delivery,
verification, Home Assistant service calls, or physical actuation.

## Epic 10.13C authorization and safety-preflight rules

`ExecutionAuthorizationEngine` evaluates an immutable proposal against the
current decision record, its frozen evaluation context, the selected runtime
environment, and active safety blockers. The result is an immutable
`ExecutionAuthorization`; authorization does not create a plan or deliver an
operation.

Authorization has three dispositions:

- `AUTHORIZED` — every identity and safety check passed and the proposal may
  proceed to deterministic plan construction;
- `DEFERRED` — a temporary condition requires reevaluation before planning,
  such as a newer context, expired context, active context blocker, active
  safety blocker, or shadow runtime; and
- `REJECTED` — an invariant is broken or unsafe, such as a missing/current
  decision mismatch, superseded decision, context identity mismatch, runtime
  mismatch, live runtime, or a physical-delivery policy.

Rejection takes precedence over deferral when both types of issue are present.
Blocking reason codes are deterministic and preserved in the authorization
artifact for recording and future publication.

Throughout Epic 10.13, only simulation proposals can be authorized. Shadow
proposals are deferred and live proposals are rejected. A runtime environment
that allows physical delivery is rejected even if other checks pass. The
preflight performs no endpoint delivery and cannot call Home Assistant or
Pentair.

Authorization also verifies that:

- the proposal references the active Flight Recorder decision;
- decision, objective, and evaluation-context identifiers agree;
- the decision has not been explicitly superseded;
- the proposal, context, and runtime environment use the same runtime mode;
- proposal and decision timestamps are not in the future;
- the context is still current and has not passed an explicit validity bound;
  and
- no temporary context or safety blockers are active.

Authorization IDs are deterministic for the same proposal, evaluation time,
disposition, and blocker set. Repeating the same preflight snapshot therefore
produces the same auditable result.

## Epic 10.13C scope

Epic 10.13C adds:

- immutable authorization-preflight requests;
- simulator-only authorization policy;
- authorized, deferred, and rejected dispositions;
- current-decision, context, runtime, endpoint-class, and safety checks;
- deterministic authorization identifiers; and
- tests covering successful authorization and every major blocking class.

It does not add execution-plan construction, operation translation, simulated
delivery, verification, Home Assistant service calls, Pentair commands, or
physical actuation.

## Epic 10.13D deterministic execution-plan rules

`DeterministicExecutionPlanBuilder` converts one authorized
`ExecutionProposal` into one immutable `ExecutionPlan`. Plan construction is a
pure data transformation. It does not translate or deliver operations and does
not contact simulator, Home Assistant, Pentair, or any physical endpoint.

A plan is built only when:

- the authorization disposition is `AUTHORIZED`;
- the authorization references the same proposal;
- authorization did not precede proposal creation;
- every proposal operation has exactly one step specification; and
- no step specification refers to an unknown operation.

Each `ExecutionStepSpecification` explicitly defines:

- operation preconditions;
- expected observations;
- whether verification is required; and
- step metadata.

Verification-required steps must define at least one expected observation.
Specifications accept JSON-serializable planning facts only so deterministic
plan identifiers can include all planning annotations.

The builder preserves the canonical operation order from the proposal. The
order in which step specifications are supplied cannot reorder operations.
Step sequences are contiguous from one, and step IDs are deterministically
derived from the plan ID and sequence.

Plan identifiers are deterministic for the same proposal, authorization,
ordered operations, step specifications, and plan metadata. Repeating the same
build request therefore produces the same immutable plan.

Rejected build attempts return explicit reason codes, including unauthorized
or mismatched authorization, missing or unknown specifications, duplicate
specifications, and temporally invalid authorization.

## Epic 10.13D scope

Epic 10.13D adds:

- immutable execution-step specifications;
- deterministic execution-plan construction;
- explicit built and rejected plan-build results;
- operation-order preservation;
- step preconditions and expected-observation requirements;
- deterministic plan and step identifiers; and
- tests proving plan construction does not translate or deliver operations.

It does not add operation translation, simulator delivery, verification,
execution coordination, Home Assistant service calls, Pentair commands,
physical actuation, or restart resumption.

## Epic 10.13E execution state-machine rules

`ExecutionStateMachine` is the single authoritative validator for supervisory
execution lifecycle changes. It is a pure domain component: it does not
coordinate steps, translate `PoolOperation` objects, deliver commands, inspect
Home Assistant, contact Pentair, or perform physical actuation.

The canonical successful lifecycle is explicit:

```text
AUTHORIZED
  -> PLANNED
  -> EXECUTING
  -> DELIVERING
  -> DELIVERED
  -> VERIFYING (when verification is required)
  -> VERIFIED
  -> COMPLETED
```

A delivered step or plan that does not require observation verification may
move directly from `DELIVERED` to `VERIFIED`, but it must still transition to
`COMPLETED` before the lifecycle is finished.

Exceptional terminal states are:

```text
REJECTED
FAILED
TIMED_OUT
ABORTED
SUPERSEDED
```

`COMPLETED` is also terminal. Terminal states cannot resume or transition to
another status. Restart recovery must therefore reconcile and reevaluate
rather than mutate an old terminal or incomplete lifecycle into a resumed
execution.

Every accepted transition produces an immutable `ExecutionStateTransition`
containing:

- deterministic transition identity;
- plan identity;
- prior and next lifecycle status;
- timezone-aware occurrence time;
- actor and reason; and
- immutable metadata.

`ExecutionLifecycle` stores the immutable current status and complete accepted
transition history. The history must be chronologically ordered, status
contiguous, plan consistent, and synchronized with the lifecycle's current
status and update timestamp.

Rejected transition requests do not mutate lifecycle state. They return an
explicit reason such as:

```text
status_unchanged
terminal_state_cannot_transition
transition_time_precedes_current_state
illegal_transition:authorized->delivered
```

Transition identifiers are deterministic for the same plan, source state,
target state, timestamp, actor, reason, transition number, and metadata. This
supports future replay and Flight Recorder comparison without introducing a
runtime side effect.

## Epic 10.13E scope

Epic 10.13E adds:

- canonical `PLANNED`, `EXECUTING`, and `COMPLETED` lifecycle states;
- one authoritative legal-transition table;
- immutable execution lifecycle and transition artifacts;
- deterministic transition identifiers;
- terminal-state lockout;
- chronological and status-contiguous history validation; and
- tests proving that the state machine has no delivery collaborator.

It does not add execution coordination, operation translation, simulator
command delivery, observation verification, Flight Recorder persistence,
Home Assistant service calls, Pentair commands, physical actuation, or restart
resumption.

## Epic 10.13F execution-coordination rules

`ExecutionCoordinator` is a thin, pure lifecycle consumer above the immutable
`ExecutionPlan` and authoritative `ExecutionStateMachine`. It admits only an
authorized plan, transitions it to `PLANNED`, starts coordination by
transitioning it to `EXECUTING`, and exposes exactly one current step at a time.

The coordinator maintains an immutable `ExecutionCoordinationSession` with:

- the plan-specific lifecycle;
- the current step sequence;
- completed step identifiers;
- explicit stop state and reason; and
- immutable, deterministic coordination events.

Step advancement requires an explicit completion signal for the currently
selected step. Out-of-order, duplicate, stale-time, cross-plan, terminal, and
post-stop requests are rejected without mutating the session. The completion
signal is a coordination fact only: the coordinator does not determine whether
delivery or verification succeeded.

After the final step-completion signal, coordination stops with
`plan_steps_exhausted`. The lifecycle intentionally remains `EXECUTING`; later
milestones must provide real delivery and verification facts before advancing
the lifecycle through `DELIVERING`, `DELIVERED`, `VERIFYING`, `VERIFIED`, and
`COMPLETED`. The coordinator never fabricates those states.

## Epic 10.13F scope

Epic 10.13F adds:

- immutable coordination sessions, events, and results;
- authorized-plan admission;
- deterministic lifecycle advancement to `PLANNED` and `EXECUTING`;
- one-current-step selection;
- ordered completion-signal handling;
- explicit stop conditions; and
- tests covering identity, ordering, time, terminal, and immutability rules.

It does not translate `PoolOperation` objects, create vendor commands, deliver
to the simulator, verify observations, invoke Home Assistant or Pentair,
perform physical actuation, or resume an incomplete session after restart.

## Epic 10.13G execution-verification rules

`ExecutionVerificationEngine` is a pure evidence-evaluation boundary. It
compares one `ExecutionStep` with canonical typed observations already admitted
to an `ObservationStore`. It does not deliver commands, advance the coordinator,
or transition the lifecycle state machine.

Verification evaluates only observations matching the request's required
source identity. Epic 10.13 remains simulation-only, so verification defaults
to `SIMULATED` observations. A live observation cannot silently satisfy a
simulation verification request.

Each expected observation produces immutable evidence classified as:

```text
MATCHED
MISMATCHED
MISSING
STALE
FUTURE
UNUSABLE
LOW_CONFIDENCE
```

The aggregate verification result is:

- `VERIFIED` when every expected observation is fresh, usable, sufficiently
  confident, and equal to its expected value;
- `FAILED` when all expected observations are resolved with fresh usable
  evidence and at least one value does not match;
- `PARTIAL` when at least one expectation matches but other evidence remains
  unresolved before the deadline;
- `PENDING` when verification still lacks sufficient evidence before the
  deadline;
- `TIMED_OUT` when the deadline is reached without complete verification; or
- `NOT_REQUIRED` when the plan step explicitly requires no verification.

Delivery acceptance and verification remain separate facts. The verification
engine consumes existing observation freshness, provenance, quality, and
confidence semantics; it does not create a second observation model.
Verification identifiers are deterministic for an identical evidence snapshot.

## Epic 10.13G scope

Epic 10.13G adds immutable verification requests, evidence, and results;
source-aware observation lookup; freshness, quality, and confidence gates;
partial and timeout semantics; and deterministic verification identities.

It does not translate operations, create vendor commands, contact simulator
endpoints, invoke Home Assistant or Pentair, advance coordination, transition
execution lifecycle state, perform physical actuation, or resume work after a
restart.

## Epic 10.13H execution-flight-recorder rules

`InMemoryExecutionFlightRecorder` is the canonical append-only history boundary
for supervisory execution. It preserves the existing immutable execution
artifacts rather than translating them into a second domain model:

```text
ExecutionProposal
ExecutionAuthorization
ExecutionPlan
ExecutionStateTransition
ExecutionCoordinationEvent
ExecutionVerificationResult
ExecutionOutcome
```

Each `ExecutionFlightRecord` carries a contiguous sequence number, deterministic
record ID, event time, artifact type and ID, and complete decision, context,
proposal, authorization, plan, and session lineage where those identities
exist. Proposal and authorization facts precede plan creation; plan-scoped
facts share one stable execution-session identity.

The recorder enforces causal and chronological history. A proposal must be
recorded before its authorization, an authorization before its plan, and a plan
before lifecycle, coordination, verification, or outcome facts. Duplicate
artifacts, backdated appends, cross-lineage plans or outcomes, unknown plan-step
references, and records appended after a completed outcome are rejected without
mutating history.

`ExecutionTimeline` provides an immutable validated view. The recorder exposes
ordered history by plan, decision, and execution session, while `export_json()`
produces a stable complete artifact snapshot for diagnostics and future durable
persistence. The original immutable artifact is retained on every record so
callers can recover the typed execution fact without reconstructing it from a
lossy summary.

## Epic 10.13H scope

Epic 10.13H adds immutable execution flight records and timelines, stable
session and record identities, append-order and lineage validation, complete
artifact snapshots, deterministic JSON export, and execution-history queries.

It does not coordinate execution, translate operations, create or deliver
vendor commands, contact simulator endpoints, evaluate observations, invoke
Home Assistant or Pentair, advance lifecycle state, perform physical actuation,
or resume incomplete work after restart.

## Epic 10.13I — Execution restart recovery

Execution restart recovery interprets append-only execution history without
restoring execution authority. `ExecutionRestartRecoveryEngine` classifies one
recorded execution lineage and emits immutable, deterministic recommendations.
It never rebuilds a coordinator cursor, retries an operation, or resumes a
partially completed plan.

The recovery rule is:

```text
execution history != execution authority
```

Interrupted histories are classified as occurring before authorization, before
plan creation, before execution, during execution, during verification, or
after terminal verification without a final outcome. Completed histories need
no execution action. Terminal failures recommend fresh reevaluation. Invalid,
future-dated, noncontiguous, or causally inconsistent histories are classified
as corrupt and require explicit corruption recording and operator review.

Every interrupted executable lineage recommends that prior intent be treated as
superseded and that PoolOS obtain fresh observations and reevaluate. Recovery
never grants permission to resume. The wider runtime may later use the
assessment to reconcile actual state and create new intent if still required.

This milestone does not coordinate execution, translate operations, create or
deliver vendor commands, contact simulator endpoints, invoke Home Assistant or
Pentair, perform physical actuation, or mutate the recorded timeline.

## Epic 10.13J — Golden end-to-end execution scenarios

PoolOS maintains a permanent golden scenario catalog for the supervisory
execution pipeline. These scenarios validate behavior across immutable
execution artifacts without introducing simulator delivery or hardware access.

The required scenarios cover:

- verified execution with a recorded terminal outcome;
- verification-not-required behavior;
- rejected and deferred authorization;
- failed and timed-out verification;
- restart during execution and verification;
- completed restart recovery; and
- corrupt execution history.

The catalog lives in `poolos.execution_golden_scenarios`; executable regression
coverage lives in `tests/test_execution_golden_scenarios.py`. Scenario IDs are
stable and the catalog is validated for uniqueness and completeness.

These scenarios deliberately stop at the supervisory boundary. They do not
translate operations, create vendor commands, contact a simulator endpoint,
call Home Assistant, call Pentair, or permit interrupted execution to resume.

## Epic 10.14A — Simulator execution gateway

`SimulatorExecutionGateway` is the first simulator-delivery integration point
for the supervisory execution architecture. It composes the existing validated
runtime-environment, endpoint-registry, vendor-command gateway, and
simulator-endpoint boundaries without duplicating any of them.

Construction is permitted only from a `SIMULATION` runtime that prohibits
physical delivery and contains at least one endpoint classified as
`SIMULATOR`. The gateway exposes deterministic simulator routes and delivers a
single already-translated `VendorCommand` through the existing
`VendorCommandGateway` exactly once.

Automatic routing by vendor is permitted only when one unambiguous simulator
endpoint exists for that vendor. Installations with multiple simulator
endpoints for the same vendor must select an explicit endpoint ID.

This milestone deliberately does not consume `ExecutionPlan` or
`ExecutionStep` objects, translate `PoolOperation` objects, advance coordinator
or lifecycle state, verify observations, call Home Assistant, contact physical
Pentair equipment, or resume interrupted execution.

## Simulator step delivery (10.14B-C)

`SimulatorStepDeliveryEngine` connects exactly one `ExecutionStep` to the
existing translation handler and simulator execution gateway. It validates that
the step is an exact member of the plan and that the lifecycle is `EXECUTING`,
then records deterministic execution-scoped receipt identities while preserving
the underlying `DeliveryReceipt` objects.

The boundary stops at `DELIVERED`, `FAILED`, or `TIMED_OUT`. It does not verify
observations, advance the coordinator cursor, complete a plan, or permit any
physical endpoint.

## Epic 10.14D: Closed-loop simulator execution

PoolOS separates the lifecycle of the whole execution plan from the lifecycle
of each step. The plan remains `EXECUTING` while each selected step independently
moves through delivery and verification:

```text
Plan: EXECUTING

Step: PENDING -> DELIVERING -> DELIVERED -> VERIFYING -> VERIFIED
                                                   |
                                                   +-> FAILED / TIMED_OUT
```

After simulator delivery, the closed-loop engine applies the canonical
`PoolOperation` to deterministic simulated equipment state, publishes typed
`SIMULATED` observations, verifies those observations, and only then advances
the coordinator. When all steps are verified, the coordinator transitions the
plan from `EXECUTING` to `COMPLETED`.

This milestone remains simulator-only. It does not call Home Assistant, route to
physical Pentair equipment, retry failed work, or resume interrupted execution.

## Simulator fault injection and recovery (Epic 10.14E)

The closed-loop simulator accepts an optional immutable `SimulatorFaultPlan`.
Fault rules target an exact execution step and inject a deterministic failure at
one of two boundaries:

```text
step delivery
or
simulated observation publication / verification
```

Supported faults include rejected, failed, and timed-out delivery; missing,
stale, and mismatched observations; and verification timeout. Every injected
fault creates a `SimulatorFaultRecord` containing deterministic identity,
lineage, reason, and non-actuating recovery recommendations.

Fault recovery is intentionally fail-safe:

```text
terminate affected step
→ terminate the current plan attempt
→ await operator or obtain fresh observations and reevaluate
```

The fault layer does not retry, advance the coordinator, resume a prior plan,
call Home Assistant, or contact physical equipment.
