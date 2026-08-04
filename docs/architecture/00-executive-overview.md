# PoolOS Architecture Manual

## 00 — Executive Overview

PoolOS is a deterministic automation operating system for swimming pools and spas. It separates observation, reasoning, supervision, execution, and hardware integration into independent architectural layers so that automation decisions remain explainable, replayable, and independent of any specific vendor.

## Why PoolOS Exists

Traditional pool automation is usually organized around controller commands, schedules, and vendor-specific equipment models. That approach works for basic control, but it becomes difficult to reason about when automation must also account for safety, energy cost, changing conditions, competing goals, equipment faults, and future recovery.

PoolOS treats pool automation as an operating-system problem instead of a controller-script problem.

The system first establishes what is true, then determines what should happen, explains why, records the evidence, and only then considers whether and how an action may be executed. Hardware communication is deliberately kept at the outer edge of the architecture.

## The Core Architectural Idea

PoolOS separates thinking from acting.

```text
Observe reality
      |
      v
Construct context
      |
      v
Evaluate goals, policies, and alternatives
      |
      v
Choose and explain a decision
      |
      v
Determine the operational disposition
      |
      v
Authorize, execute, verify, and recover
      |
      v
Translate into vendor-specific commands
```

The cognitive system decides **what should happen**.

The execution system determines **how it can happen safely**.

The integration layer determines **how vendor-independent intent is translated into platform- and device-specific operations**.

## Major Architectural Layers

### Observation Layer

The observation layer gathers and normalizes facts from Home Assistant, forecasts, simulators, and future data sources. It represents current conditions without embedding automation policy.

### Cognitive System

The cognitive system evaluates goals, policies, forecasts, observations, constraints, and alternatives. It produces deterministic decisions, explanations, and audit evidence without actuating equipment.

### Supervisory Runtime

The supervisory runtime coordinates one complete decision cycle. It composes trigger handling, input assembly, decision invocation, operational disposition, and command-free routing while preserving deterministic identity and provenance.

### Execution System

The execution system converts accepted intent into authorized plans, coordinates lifecycle transitions, verifies outcomes, records execution evidence, and recommends recovery actions. Its core remains vendor-neutral.

### Integration Layer

The integration layer connects PoolOS to Home Assistant, Pentair IntelliCenter, and future vendors. It is responsible for platform-specific communication and is the only layer that may eventually reach physical equipment through explicit safety and delivery boundaries.

## Architectural Principles

PoolOS is guided by several enduring principles:

1. Determinism over convenience.
2. Immutability by default.
3. Separation of reasoning and execution.
4. Vendor independence.
5. Safety before automation.
6. Replayability.
7. Explainability.
8. Composition of small, testable boundaries.

These principles are expanded in later chapters of this manual and should guide future architecture decisions.

## What PoolOS Is Not

PoolOS is not:

- a replacement firmware for a pool controller;
- a collection of ad hoc Home Assistant automations;
- a Pentair-specific decision engine;
- a direct RS-485 command implementation;
- a system that permits decision logic to bypass execution safety boundaries;
- a live-actuation platform today.

The current production safety boundary stops before live automatic actuation. Simulator execution and command-delivery abstractions exist, but Home Assistant service calls, Pentair delivery, and physical equipment actuation remain separately reviewed capabilities.

## Current System Boundary

PoolOS currently performs:

```text
OBSERVE -> EVALUATE -> DECIDE -> EXPLAIN -> RECORD -> PUBLISH
```

It also contains a simulator-only execution framework used to validate authorization, planning, delivery, verification, fault handling, and recovery without contacting live equipment.

## Why the Architecture Is Structured This Way

This separation provides four important properties:

### Safety

Reasoning cannot directly actuate equipment. Every action must pass through explicit execution and delivery boundaries.

### Portability

Core intelligence does not depend on Pentair, Home Assistant, or any other vendor.

### Auditability

Important decisions and execution outcomes preserve identities, timestamps, provenance, and immutable evidence.

### Testability

Each boundary can be validated independently and then composed into deterministic end-to-end scenarios.

## How to Read This Manual

Start with the design philosophy and guiding principles, then continue to the capability map and layered architecture. Later chapters describe data flow, identity, safety boundaries, subsystem responsibilities, and repository navigation.

The Architecture Manual explains the enduring design of PoolOS. Architecture Decision Records explain why individual decisions were made. The source code implements those decisions.

## Responsibilities

This chapter:

- introduces PoolOS at the system level;
- explains why its major layers exist;
- defines the current safety boundary;
- establishes the vocabulary used throughout the manual.

## Non-responsibilities

This chapter does not:

- document individual classes or functions;
- define implementation-level APIs;
- replace ADRs;
- describe installation or end-user operation;
- authorize live equipment control.

## Future Evolution

Future versions of PoolOS may add reviewed Home Assistant execution, Pentair command delivery, and additional vendor adapters. Those capabilities must preserve the separation between observation, reasoning, execution, and integration described here.
