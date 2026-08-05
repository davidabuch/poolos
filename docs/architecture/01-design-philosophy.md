# Design Philosophy

> **Architecture Manual v1.0** · Chapter 2 of 15

## Why PoolOS exists

Traditional pool automation usually begins with a controller, a set of relays, and a collection of schedules. That approach can operate equipment, but it does not provide a durable model for reasoning about goals, safety, energy, uncertainty, or changing conditions.

PoolOS begins from a different premise: pool automation is an operating-system problem.

The system must observe reality, construct a trustworthy context, evaluate competing objectives, explain a recommendation, preserve evidence, and only then allow a separate execution system to determine whether and how an action may occur.

PoolOS therefore treats hardware as an endpoint rather than the source of truth for automation policy.

## Thinking and acting are different responsibilities

The central architectural idea in PoolOS is the separation of reasoning from execution.

The reasoning side answers questions such as:

- What is happening now?
- What is likely to happen next?
- Which goals are active?
- Which constraints or policies apply?
- Which alternatives are available?
- Which option is preferred, and why?
- Should the current plan be kept, replaced, cancelled, or deferred?

The execution side answers different questions:

- Is the proposed action authorized?
- Is the system in a safe operating mode?
- Which equipment operations are required?
- In what order should they occur?
- Did the equipment respond as expected?
- What should happen after failure or interruption?

Keeping these responsibilities separate makes the system easier to test, explain, replay, and audit. It also prevents decision logic from bypassing safety, authorization, or vendor-delivery boundaries.

## Vendor independence is a core constraint

PoolOS is not designed around one manufacturer.

The core system models pools, spas, goals, observations, policies, decisions, plans, and execution evidence in vendor-independent terms. Pentair IntelliCenter is an integration target, not the definition of the domain.

This means:

- policy does not depend on Pentair entity names;
- planning does not depend on Home Assistant service calls;
- decision logic does not import vendor libraries;
- vendor adapters translate canonical intent at the edge;
- future vendors can be added without redesigning the cognitive system.

Vendor independence is not merely a portability feature. It is a safety feature because it keeps hardware-specific behavior isolated behind explicit boundaries.

## Determinism is preferred over convenience

PoolOS favors explicit inputs and reproducible outputs.

Whenever practical, a boundary receives all information needed to make a decision. Time is passed explicitly. Evidence is immutable. Identity is derived from canonical inputs. Order-insensitive data is normalized before hashing or comparison.

This makes it possible to answer a critical operational question:

> Given the same evidence, would PoolOS reach the same conclusion again?

Determinism enables reliable tests, restart recovery, replay, audit, and diagnosis. It also reduces hidden dependencies on system time, process state, call order, or external mutable objects.

## Simulation precedes actuation

PoolOS does not treat live equipment as the first test environment.

New capabilities are developed against simulation or non-actuating boundaries before they are allowed to approach live delivery. The simulator is used to validate lifecycle behavior, fault handling, verification, and recovery while preserving a hard separation from Home Assistant and Pentair command paths.

This progression is intentional:

```text
Model
  -> simulate
  -> verify
  -> review
  -> stage
  -> actuate
```

A green unit-test suite is necessary but not sufficient for live control. Hardware commissioning, Home Assistant runtime validation, rollback planning, and operational safety review remain separate release gates.

## Explainability is part of correctness

A recommendation that cannot be explained is incomplete.

PoolOS records not only what it selected, but also the evidence, alternatives, constraints, and reasoning that produced the result. Human-readable explanations and technical explanations are separate outputs because they serve different audiences.

Explainability supports:

- operator trust;
- troubleshooting;
- auditability;
- regression review;
- comparison of alternatives;
- safe refinement of policies.

The explanation layer is not decorative. It is part of the decision contract.

## Immutable evidence over mutable state

PoolOS uses immutable records to represent important facts and outcomes.

Mutable runtime components may exist where coordination requires them, but the evidence crossing architectural boundaries should be stable. An observation, context, decision, disposition, invocation, execution record, or delivery receipt should not silently change after it has been emitted.

Immutability reduces accidental coupling and makes replay possible. It also makes boundaries easier to reason about because consumers receive a historical fact rather than a live object whose meaning may change later.

## Composition instead of centralization

PoolOS does not rely on one giant manager that observes, decides, schedules, executes, and delivers.

Larger workflows are composed from smaller deterministic boundaries. Each boundary has a narrow responsibility and explicit non-responsibilities. This allows capabilities to be tested independently and replaced without redefining the entire system.

The supervisory evaluation runtime is an example: it composes trigger coalescing, input assembly, invocation, decision orchestration, operational disposition, and command-free routing. It does not duplicate those responsibilities.

## Safety takes precedence over automation

Automation is useful only when it remains bounded by safety.

PoolOS treats runtime mode, authority, ownership, validation, execution authorization, verification, and delivery as distinct controls. No policy or decision component is permitted to bypass them merely because an action appears beneficial.

The system prefers to block, defer, or request review rather than create ambiguous command behavior.

## Long-term architectural vision

The long-term system is divided into five major concerns:

1. Observation establishes what is known.
2. Cognition determines what should happen.
3. Supervision coordinates one deterministic evaluation cycle.
4. Execution determines how approved intent is carried out safely.
5. Integration translates vendor-independent operations into platform- and vendor-specific behavior.

This separation is the foundation for a system that can remain understandable as capabilities grow.

## Responsibilities

This philosophy defines how PoolOS should approach new features, reviews, ADRs, integrations, and releases.

## Non-responsibilities

This chapter does not define concrete APIs, class names, deployment steps, or hardware commissioning procedures.

## Future evolution

Future architectural changes should preserve these principles or document an explicit reason for departing from them.

---

[Previous: Executive Overview](00-executive-overview.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Guiding Principles](02-guiding-principles.md)
