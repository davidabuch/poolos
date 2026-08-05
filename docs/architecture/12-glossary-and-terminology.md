# Glossary and Terminology

> **Architecture Manual v1.0** · Chapter 13 of 15

## Purpose

This chapter defines the canonical vocabulary used throughout PoolOS. Documentation, ADRs, APIs, and tests should prefer these terms and avoid creating near-synonyms without a clear need.

## Core domain terms

### Adapter

A boundary component that translates between canonical PoolOS models and an external platform, vendor, protocol, or simulator.

### Alternative

One possible course of action considered during decision evaluation. An alternative is not yet selected, authorized, or executable.

### Authority

Explicit permission to perform a class of operation in a particular runtime context. Authority is separate from intent and capability.

### Blocker

A fact or condition that prevents an evaluation, decision, disposition, or execution path from proceeding.

### Canonical identity

A deterministic identifier derived from the stable evidence that defines an architectural object or operation.

### Canonical model

A vendor-independent representation used inside PoolOS as the authoritative form of a concept.

### Capability

A coherent system ability with defined inputs, outputs, responsibilities, and non-responsibilities.

### Command

A platform- or device-facing request that asks an external system to perform an operation. Commands belong at the integration edge, after authorization.

### Constraint

A rule that limits which alternatives, plans, or operations are acceptable.

### Context

An immutable collection of facts, goals, policies, timing, and prior evidence assembled for one evaluation boundary.

### Decision

The deterministic outcome of evaluating alternatives against the supplied context. A decision may select, block, or defer.

### Decision evidence

The inputs, scores, policies, explanations, identities, and provenance needed to understand and replay a decision.

### Delivery

The act of submitting an authorized canonical operation to an adapter or simulator boundary.

### Disposition

A command-free operational recommendation derived from accepted decision evidence. It describes what the execution side should consider next.

### Equipment state

Canonical observed information about physical or simulated equipment. It describes reality rather than desired intent.

### Evaluation

The deterministic process of applying goals, policies, constraints, and evidence to alternatives.

### Evidence

Immutable information used to support, explain, verify, or replay an architectural outcome.

### Execution

The controlled lifecycle that turns authorized intent into ordered work, delivery, verification, and terminal evidence.

### Execution plan

An immutable, ordered description of authorized work, including steps, dependencies, expected outcomes, and recovery information.

### Flight record

Structured evidence that captures a decision, execution transition, delivery, verification, or other material event.

### Freshness

A classification describing whether observed information is recent enough for a particular purpose.

### Goal

A desired outcome the planning and decision systems attempt to advance.

### Identity derivation

The deterministic process used to create a canonical identity from normalized evidence.

### Integration layer

The architectural edge that communicates with Home Assistant, vendor systems, external services, or simulators.

### Intent

A vendor-independent description of what PoolOS wants to accomplish. Intent is not authority, a command, or proof of completion.

### Observation

A canonical statement about current or historical reality, together with relevant time, source, quality, and provenance.

### Operational routing

Command-free guidance that identifies which execution boundary should receive a disposition if an outer runtime chooses to route it.

### Planner

A capability that constructs or evaluates candidate ways to satisfy an objective. It does not deliver commands.

### Policy

A rule that influences evaluation, ranking, authorization, or safety behavior.

### Provenance

Evidence describing where information or an identity came from and which upstream artifacts contributed to it.

### Recommendation

A proposed outcome produced by an evaluator or subsystem. A recommendation is not necessarily an accepted decision or authorized action.

### Recovery

A bounded response to execution failure, contradiction, timeout, or incomplete verification.

### Replay

Reevaluating recorded evidence to confirm that the same deterministic boundaries produce the same outcome.

### Runtime

A composition boundary that coordinates already-defined capabilities for one operating cycle. A runtime does not automatically imply background work, polling, persistence, or actuation.

### Runtime mode

An explicit operating classification, such as simulation or a future commissioned live mode, that affects what behavior is permitted.

### Safety boundary

A component or rule that prevents intent from becoming unsafe or unauthorized work.

### Simulation

Execution against deterministic simulated state and delivery boundaries without live hardware actuation.

### State

A canonical description of current condition. State must not be confused with desired intent or a previously issued command.

### Submission

An immutable request offered to a runtime boundary for validation, coalescing, or evaluation.

### Supervisor or supervisory runtime

The command-free composition layer that accepts runtime submissions, assembles evaluation context, invokes decision orchestration, and produces operational disposition evidence.

### Trigger

Evidence that explains why an evaluation cycle was requested. A trigger is not itself a decision.

### Verification

The comparison of expected outcomes with subsequent observations.

## Important distinctions

### Decision vs. command

A decision states what should happen. A command asks an external system to perform an operation.

### Intent vs. authority

Intent describes a desired outcome. Authority determines whether execution is permitted.

### Delivery vs. verification

Delivery reports that a request was submitted. Verification reports whether observed reality matched the expected result.

### State vs. intent

State describes what is true. Intent describes what is desired.

### Unknown vs. false

Unknown means the system lacks sufficient evidence. False is a known negative value.

### Stale vs. unavailable

Stale data exists but may be too old for the current purpose. Unavailable data cannot currently be obtained from its source.

### Compatibility API vs. stable API

A compatibility API remains importable to avoid breakage. A stable API is an explicitly supported long-term contract.

## Naming guidance

- Use `*_id` for canonical identifiers.
- Use `*_at` for timezone-aware event times.
- Use `observed_*` for measured state and `desired_*` for intent.
- Use `request`, `result`, and `record` according to boundary direction and evidence role.
- Avoid using `runtime`, `manager`, `controller`, or `engine` as interchangeable terms.
- Avoid naming a recommendation as though it has already been executed.

## Responsibilities

This chapter provides the authoritative meanings for recurring PoolOS terms.

## Non-responsibilities

It does not replace detailed type documentation or define every implementation-specific field.

## Future evolution

New terms should be added only when they represent a durable architectural concept rather than a temporary implementation detail.

---

[Previous: How PoolOS Thinks](11-how-poolos-thinks.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Architectural Patterns](13-architectural-patterns.md)
