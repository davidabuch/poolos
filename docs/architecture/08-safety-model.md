# Safety Model

> **Architecture Manual v1.0** · Chapter 9 of 15

## Purpose

PoolOS reasons about equipment that can move water, create suction, heat bodies of water, consume substantial electrical power, and interact with external automation systems. Safety therefore cannot be an afterthought attached to command delivery. It is an architectural property that constrains observation, decision-making, execution, integration, and recovery.

This chapter defines the safety model that all PoolOS capabilities must preserve.

## Foundational rule

> No recommendation becomes a physical action merely because it is desirable.

A decision expresses what the system believes should happen. Execution determines whether that intent is authorized, safe, timely, and technically deliverable. Integration code may translate an approved operation, but it may not invent authority or bypass execution controls.

## Safety is distributed but authority is explicit

Every layer contributes safety evidence, but not every layer may authorize action.

```text
Observation
  supplies freshness, quality, and current-state evidence

Cognitive system
  identifies constraints, blockers, and safer alternatives

Supervisory runtime
  preserves evidence and produces command-free disposition

Execution system
  authorizes, orders, verifies, and terminates work

Integration layer
  enforces final transport and commissioning boundaries
```

Safety checks may be repeated at boundaries when they protect against different failure modes. Repetition is acceptable when each check has a clear owner and purpose; duplicated policy logic with competing meanings is not.

## Safety invariants

The following invariants apply across the system.

### 1. Reasoning is command-free

Planning, ranking, decision intelligence, explanation, supervisory evaluation, and operational disposition must not actuate equipment or call vendor services.

### 2. Execution requires explicit authority

An execution proposal is not self-authorizing. Runtime mode, authority, ownership, policy constraints, and current equipment state must permit work before a plan can advance.

### 3. Unknown is not safe by default

Missing, stale, unavailable, contradictory, or invalid observations must remain distinguishable. They must not be silently coerced into reassuring values.

### 4. Live actuation is opt-in

Simulation capability does not imply deployment readiness. A live adapter must be explicitly implemented, reviewed, configured, and commissioned.

### 5. Verification follows delivery

A successful transport call proves only that a request was accepted by a boundary. It does not prove that equipment reached the intended state. Verification must use later observation evidence.

### 6. Faults terminate predictably

Execution failures must produce explicit lifecycle evidence and a safe terminal or recovery recommendation. They must not leave an ambiguous plan that appears active indefinitely.

### 7. External control remains observable

PoolOS must tolerate equipment changes initiated outside its own execution path. It must distinguish observed reality from its own intent and avoid immediately fighting unexplained external state changes.

### 8. Replay must not actuate

Historical replay, diagnostics, and golden scenarios must use pure or simulator-only boundaries. Replaying evidence must never resend live commands.

## Runtime modes

Runtime mode is a first-class safety input.

A useful conceptual hierarchy is:

```text
REPLAY / ANALYSIS
    no command delivery

SIMULATION
    simulator-only delivery

OBSERVATION / SHADOW
    evaluate and record, but do not deliver

LIVE
    delivery permitted only through commissioned adapters
```

Specific enum names may differ across modules, but the architectural distinction must remain explicit. Code must not infer live authority merely from the presence of an adapter or a valid plan.

## Authority and ownership

PoolOS separates three related questions:

1. **What should happen?** — decision responsibility.
2. **Who currently has authority to change it?** — ownership and authorization responsibility.
3. **How should the approved change be performed?** — execution and adapter responsibility.

An external operator, vendor application, local panel, Home Assistant automation, or safety subsystem may change equipment independently. PoolOS must observe those changes and preserve attribution evidence where available.

The system should prefer conservative behavior when ownership is uncertain:

- do not seize control silently;
- do not reverse unexplained external operation automatically;
- do not claim that a command caused a transition without matching evidence;
- allow higher-priority safety intervention to preempt ordinary control when explicitly designed.

## Safety gates

Before a live execution step may be delivered, the execution path should be able to answer:

- Is live mode enabled?
- Is the adapter commissioned for this operation?
- Is the requested operation within granted authority?
- Does current ownership permit PoolOS control?
- Are required observations fresh and valid?
- Is the plan still based on the current accepted decision?
- Are preconditions still true?
- Has a conflicting plan or manual action appeared?
- Is the command idempotent or otherwise protected from duplicate delivery?
- Is there a defined verification and timeout path?

A negative or unknown answer should block, defer, or request review rather than guess.

## Fail-safe and fail-closed behavior

“Fail safe” is context-specific. Turning equipment off is not universally safest: freeze protection, cooldown, circulation, or an externally managed service session may require continued operation.

PoolOS therefore uses a more precise rule:

> On uncertainty, stop creating new unverified work and preserve the safest known ownership and equipment assumptions.

Examples include:

- reject a new plan when critical observations are stale;
- retain external ownership rather than seize control;
- stop advancing a plan after verification failure;
- avoid issuing compensating commands unless a reviewed recovery policy authorizes them;
- preserve evidence needed for an operator to understand the state.

## Command delivery safety

A delivery adapter must be narrow. It receives an already authorized canonical operation and returns delivery evidence.

It must not:

- choose a goal;
- reinterpret the decision;
- skip authorization;
- manufacture successful verification;
- conceal vendor errors;
- retry indefinitely without policy;
- broaden one approved operation into unrelated commands.

Retries, when allowed, must be bounded and idempotency-aware. A repeated “turn on” request may be harmless for one device but unsafe for another operation. Retry policy belongs to execution, informed by adapter capability evidence.

## Verification and reconciliation

Verification compares intended effects with later observations. It should distinguish:

- delivered but not yet observed;
- observed success;
- observed contradictory state;
- timeout without evidence;
- transport failure;
- external intervention;
- stale or unavailable observation.

Reconciliation must not erase uncertainty. When state cannot be proven, the flight record should say so.

## Recovery

Recovery is a new safety decision, not an automatic continuation of the failed plan.

A recovery recommendation may:

- retry a safe idempotent step;
- wait for fresher observations;
- cancel remaining work;
- replace the plan;
- request operator review;
- preserve current equipment state;
- transition to a defined safe terminal state.

Recovery logic must retain the original plan, failure, delivery, and verification identities so the complete chain remains auditable.

## Emergency and protective behavior

Protective capabilities such as freeze handling, unsafe valve-state prevention, heater cooldown, electrical outage response, or “jets require spa mode” rules may require higher priority than ordinary optimization.

Such behavior must still be explicit:

- the triggering evidence is recorded;
- priority and authority are defined;
- the protected resources are scoped;
- preemption is visible;
- restoration behavior is deliberate;
- control returns to the normal owner only after reconciliation.

An emergency path is not permission for an unstructured bypass around the architecture.

## Human override

PoolOS must support humans and external systems without pretending all changes originated internally.

A human override should:

- be detected from observed state and attribution evidence;
- suspend conflicting PoolOS work;
- remain visible in status and flight records;
- end through explicit observation or policy;
- avoid short arbitrary timeouts that could reverse service work;
- remain subordinate only to reviewed protective safety behavior.

## Connectivity and degraded operation

Loss of an external connection must not collapse the conceptual model.

The integration layer should preserve:

- last-known-good values where appropriate;
- source and observation timestamps;
- freshness classification;
- connection health;
- distinction between stale data and current data;
- explicit inability to deliver when no transport is available.

A logical entity may remain available for display or alternate transport, but PoolOS must not treat stale cached state as fresh evidence merely because the entity still exists.

## Safety evidence

Safety-relevant records should include enough information to answer:

- What was requested?
- Which decision and plan authorized it?
- What runtime mode was active?
- What observations and policies were used?
- Which safety gates passed or failed?
- Who or what owned the equipment?
- Was delivery attempted?
- What did the adapter report?
- What state was later observed?
- Was recovery recommended or performed?

## Commissioning rule

A capability is not live-ready merely because unit tests pass.

Live commissioning requires, at minimum:

1. deterministic tests for the core boundary;
2. simulator and fault-injection coverage;
3. explicit adapter capability declaration;
4. reviewed authority and ownership behavior;
5. bounded timeout and recovery behavior;
6. observation and verification coverage;
7. staged activation on a low-risk path;
8. flight-record review after real operation;
9. an operator-visible method to disable or revoke control.

## Responsibilities

This chapter defines the system-wide rules that keep reasoning, authorization, delivery, verification, recovery, external ownership, and commissioning separate and auditable.

## Non-responsibilities

It does not specify installation-specific limits, electrical codes, hydraulic engineering requirements, manufacturer instructions, or the exact policy for every piece of equipment. Those belong in configuration, specialized policy modules, adapter contracts, and installation documentation.

## Future evolution

Future work may formalize safety policy facades, richer authority scopes, adapter commissioning manifests, and automated architecture tests. Any path that expands live actuation must preserve the invariants in this chapter and be accompanied by an ADR.

---

[Previous: Canonical Identity Model](07-canonical-identity-model.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Repository and Module Guide](09-repository-and-module-guide.md)
