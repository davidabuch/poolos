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
