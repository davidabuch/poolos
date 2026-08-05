# How PoolOS Thinks

## Purpose

PoolOS is not a collection of independent automations. It is a deterministic decision system that separates understanding, choosing, acting, and verifying.

The central mental model is:

```text
Observe
  -> normalize
  -> build context
  -> generate alternatives
  -> evaluate
  -> rank
  -> decide
  -> determine disposition
  -> authorize
  -> plan execution
  -> deliver
  -> verify
  -> record
```

Each stage produces evidence for the next stage. No stage is allowed to silently assume the responsibility of another.

## 1. Observe reality

PoolOS begins with facts from equipment, integrations, forecasts, configuration, simulation, and operator intent.

An observation is not merely a value. It also carries enough evidence to answer questions such as:

- where did this fact come from;
- when was it observed;
- is it fresh;
- is it complete;
- can it be trusted for this decision.

Unknown, stale, unavailable, and invalid facts must remain distinguishable. Missing information is not equivalent to a negative value.

## 2. Normalize external facts

External systems describe the same physical reality in different ways. PoolOS converts those descriptions into canonical, vendor-independent concepts.

Normalization prevents decision logic from depending on entity names, transport details, or one controller's vocabulary. It also creates a stable boundary where quality, freshness, and provenance can be evaluated.

## 3. Build evaluation context

A decision requires more than current state. PoolOS assembles an immutable context containing the facts relevant to one evaluation cycle, including:

- observations and forecasts;
- goals and objectives;
- active policies and constraints;
- runtime mode;
- explicit evaluation time;
- prior decision evidence when continuity matters;
- blockers and freshness classifications.

The context is a snapshot for reasoning. Later changes in the outside world do not retroactively alter the decision that used it.

## 4. Generate alternatives

PoolOS asks what plausible courses of action exist rather than jumping directly from a trigger to a command.

Alternatives may include acting now, retaining an existing plan, replacing a plan, waiting, scheduling reevaluation, blocking, or requesting review. Alternatives remain descriptions of possible intent; they are not commands.

## 5. Evaluate and rank

Each alternative is evaluated against goals, policies, safety constraints, timing, expected outcomes, and current operating conditions.

Ranking is deterministic. Equivalent inputs should produce equivalent results, including the same ordering and tie-breaking behavior.

The evaluation should preserve both:

- the technical evidence needed for audit and replay; and
- an explanation a human can understand.

## 6. Decide

The decision boundary selects, blocks, or defers an alternative. It explains why the outcome was reached and records the evidence that materially influenced it.

A decision answers:

> What should happen, given this context?

It does not answer:

> Which platform service should be called right now?

That separation is fundamental.

## 7. Determine operational disposition

Operational disposition translates accepted decision evidence into a command-free recommendation for the execution side.

Typical outcomes include:

- wait;
- reevaluate later;
- submit a new plan;
- retain an existing plan;
- cancel or replace a plan;
- block;
- request review.

Disposition preserves the meaning of the decision without performing execution work.

## 8. Authorize execution

Before work can proceed, the execution side independently confirms that the request is permitted under the current authority, runtime mode, safety state, and ownership rules.

A valid decision is not self-authorizing. Simulation evidence is not live authority. An adapter is not permitted to infer permission from the existence of a request.

## 9. Build an execution plan

Accepted intent is converted into an immutable, ordered plan. The plan identifies steps, dependencies, verification expectations, failure handling, and stable identities.

Execution planning answers:

> How can this accepted intent be carried out safely and observably?

It must not reinterpret the original objective or silently choose a different goal.

## 10. Deliver through an adapter

Only the integration edge translates canonical operations into external requests.

Adapters understand platform entities, services, protocols, connectivity, and transport errors. They do not own policy, planning, or authority.

Live delivery remains behind explicit commissioning and safety boundaries.

## 11. Verify observed outcomes

A successful service call is not proof that reality changed as intended.

PoolOS compares expected outcomes with new observations. Verification may confirm success, detect partial completion, identify contradiction, or trigger bounded recovery.

The observed world remains the source of truth.

## 12. Record evidence

Decision and execution evidence is recorded so the system can answer:

- what happened;
- what PoolOS believed;
- why it chose an outcome;
- what it attempted;
- what was observed afterward;
- whether replay produces the same result.

The flight-recorder pattern is not an afterthought. It is part of the operating model.

## Continuity without hidden state

PoolOS may use prior decision or execution evidence to reduce churn, preserve stable plans, or recover after interruption. That continuity must be explicit in the next request rather than hidden in mutable global state.

## Degraded operation

When information or transport is unavailable, PoolOS should degrade deliberately:

- preserve what is known;
- identify what is stale or unknown;
- avoid inventing certainty;
- block actions that require missing authority or evidence;
- continue safe, non-actuating reasoning when possible;
- recover through normal boundaries when trustworthy inputs return.

## Core rule

PoolOS thinks in evidence and intent before it acts in commands.

## Responsibilities

This chapter defines the end-to-end mental model used to interpret the rest of the architecture.

## Non-responsibilities

It does not define individual algorithms, package locations, vendor protocols, or commissioning procedures.

## Future evolution

New cognitive, execution, or integration capabilities should extend this sequence without collapsing its boundaries.
