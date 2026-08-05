# Dependency Rules

> **Architecture Manual v1.0** · Chapter 6 of 15

## Purpose

This chapter defines which architectural dependencies are allowed. The goal is not to prevent all coupling; it is to keep coupling directional, explicit, and reviewable.

## Core rule

A layer may depend on stable concepts from the same layer or a more foundational layer. It must not depend on a higher-level coordinator or on a vendor-specific edge unless it is itself an adapter.

```text
Domain and canonical models
            ^
            |
Observation and environment
            ^
            |
Cognitive system
            ^
            |
Supervisory composition
            ^
            |
Operational routing
            ^
            |
Execution system
            ^
            |
Delivery adapters
```

The arrows indicate permitted knowledge of more foundational abstractions. Runtime control flow may move downward toward execution, but type and policy ownership must not leak upward from adapters.

## Foundational domain

### May depend on

- Python standard-library concepts;
- small validation and identity utilities;
- vendor-independent enums and value objects.

### Must not depend on

- Home Assistant;
- Pentair or IntelliCenter;
- supervisory orchestration;
- execution coordinators;
- network clients.

## Observation and environment

### May depend on

- canonical domain models;
- freshness, quality, provenance, and time abstractions;
- adapter-neutral configuration contracts.

### Must not depend on

- decision ranking;
- operational disposition;
- execution authorization;
- vendor command delivery.

## Cognitive system

### May depend on

- canonical observations and environment facts;
- goals, policies, constraints, planning, and forecast models;
- prior decision evidence;
- decision-specific recording and explanation contracts.

### Must not depend on

- Home Assistant entities or services;
- Pentair protocols;
- execution state machines;
- delivery receipts;
- mutable hardware sessions.

## Supervisory runtime

### May depend on

- runtime-trigger contracts;
- evaluation assembly;
- the existing decision orchestrator;
- operational disposition and command-free routing models;
- immutable current-plan summaries.

### Must not depend on

- vendor adapters;
- live network clients;
- background workers;
- retry queues;
- direct command execution.

## Operational routing

### May depend on

- accepted decision evidence;
- immutable plan summaries;
- disposition enums and routing instructions.

### Must not depend on

- execution internals that it does not summarize;
- vendor payloads;
- transport availability;
- equipment service calls.

## Execution system

### May depend on

- accepted intent and decision identity;
- authority and runtime-mode contracts;
- canonical capabilities and equipment identities;
- verification observations;
- adapter interfaces.

### Must not depend on

- Home Assistant implementation details;
- Pentair-specific object models in core planning;
- cognitive alternative-ranking internals;
- UI state.

## Delivery adapters

### May depend on

- canonical execution-step contracts;
- vendor SDKs, protocols, and platform APIs;
- platform lifecycle facilities;
- connectivity and authentication services.

### Must not

- make policy decisions;
- create unapproved execution plans;
- bypass authority or runtime mode;
- reinterpret a rejected command as allowed.

## Presentation and UI

### May depend on

- published read models;
- explanations;
- diagnostics;
- explicit command-request interfaces.

### Must not

- mutate internal state directly;
- import private execution machinery;
- use entity availability as a substitute for authorization;
- become the sole source of safety enforcement.

## Prohibited shortcuts

The following dependencies are architectural violations unless an ADR explicitly changes the model:

- decision code importing Home Assistant entities;
- adapters choosing goals or policies;
- UI code mutating execution lifecycle state;
- observation code issuing commands;
- supervisory code performing delivery retries;
- execution plans containing vendor-specific transport objects;
- a vendor outage changing the meaning of a canonical decision.

## Boundary interfaces

Where two layers meet, dependencies should use narrow immutable contracts:

```text
Observation -> Evaluation context
Decision -> Orchestration result
Decision -> Operational disposition
Routing -> Execution proposal or plan request
Execution -> Canonical delivery request
Adapter -> Delivery receipt
Verification -> Execution result
```

These contracts should carry identity and provenance sufficient to trace the full chain without exposing internal mutable state.

## Dependency review questions

For every new import or collaborator, ask:

1. Which layer owns this concept?
2. Is the dependency toward a more foundational abstraction?
3. Could a vendor-neutral interface replace a platform-specific type?
4. Is immutable evidence sufficient, or is mutable state leaking across the boundary?
5. Would this dependency still make sense in the simulator?
6. Can the behavior be tested without Home Assistant or physical equipment?

## Enforcement

Dependency rules are currently enforced through design review, tests, MyPy, package boundaries, and ADRs. Future work may add automated import-boundary tests once the package layout is stable enough to make them durable.

## Responsibilities

This chapter defines allowed and prohibited architectural dependencies.

## Non-responsibilities

It does not list every current module import or require an immediate repository-wide refactor.

## Future evolution

AR-3 may identify legacy runtime names or imports that do not fit the intended layering. Corrections should be incremental and compatibility-aware.

---

[Previous: System Layers](04-system-layers.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Data Flow](06-data-flow.md)
