# PoolOS Supervisory Execution Pipeline

## Status

Epic 10.13 establishes the execution architecture without enabling live
actuation. Epic 10.13A defines immutable execution-domain models only.

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
