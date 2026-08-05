# Repository and Module Guide

## Purpose

This chapter helps contributors find the correct implementation boundary without requiring them to infer architecture from filenames alone.

PoolOS currently uses a predominantly flat `poolos/` Python package rather than a deep hierarchy of subpackages. That is an important fact: conceptual layers exist even when their modules share one filesystem directory. Contributors should organize dependencies by responsibility, not assume that physical proximity grants permission to couple modules.

## Repository overview

```text
poolos/
    Core domain, planning, decision, supervisory, execution,
    simulation, runtime, and supporting modules

intellicenter/
    Pentair IntelliCenter read models and integration-facing code

tests/
    Unit, contract, scenario, replay, and architecture-oriented tests

docs/
    Architecture Manual, ADRs, roadmap, and public API policy

.github/
    Continuous-integration and repository automation
```

## How to navigate the repository

If you are looking for:

```text
Canonical domain concepts
    -> poolos/bodies.py
    -> poolos/equipment.py
    -> poolos/capabilities.py
    -> poolos/commands.py
    -> poolos/observations.py

Configuration and time boundaries
    -> poolos/config.py
    -> poolos/clock.py

Policy and constraints
    -> poolos/policy.py
    -> poolos/constraints.py
    -> poolos/authority.py

Planning
    -> poolos/planning.py
    -> poolos/decision_planning.py

Decision intelligence
    -> poolos/alternative_ranking.py
    -> poolos/decision_intelligence.py
    -> poolos/decision_orchestrator.py
    -> poolos/decision_stability.py
    -> poolos/explanations.py
    -> poolos/decision_flight_recorder.py

Evaluation context
    -> poolos/evaluation_context.py

Supervisory runtime
    -> poolos/runtime_trigger_submission.py
    -> poolos/runtime_trigger_coalescing.py
    -> poolos/supervisory_evaluation_assembly.py
    -> poolos/supervisory_evaluation_invocation.py
    -> poolos/supervisory_evaluation_runtime.py

Operational disposition and routing
    -> poolos/operational_disposition.py
    -> poolos/operational_disposition_orchestrator.py

Execution
    -> poolos/execution_*.py
    -> poolos/authority.py

Simulation and deterministic scenarios
    -> poolos/simulator*.py
    -> poolos/closed_loop_simulator_execution.py
    -> poolos/golden_scenarios.py

Legacy or broad runtime composition
    -> poolos/runtime.py
    -> poolos/kernel.py

Pentair integration-facing models
    -> intellicenter/

Architectural decisions
    -> docs/adr/

Stable and compatibility imports
    -> docs/PUBLIC_API.md
    -> poolos/__init__.py
```

The exact module set evolves. Use this guide to identify responsibility, then inspect the defining module and its tests before changing behavior.

## Conceptual module groups

### Domain foundation

Representative modules:

- `bodies.py`
- `equipment.py`
- `capabilities.py`
- `commands.py`
- `observations.py`
- `config.py`
- `clock.py`

Purpose:

- define stable vocabulary;
- represent bodies, equipment, capabilities, commands, and observations;
- provide immutable or tightly controlled value objects;
- avoid dependency on Home Assistant, Pentair protocols, persistence, or orchestration.

Allowed dependencies:

- Python standard library;
- lower-level domain modules.

Forbidden responsibilities:

- policy selection;
- execution scheduling;
- vendor communication;
- background work.

### Policy, constraints, and authority

Representative modules:

- `policy.py`
- `constraints.py`
- `authority.py`

Purpose:

- express what is allowed, blocked, prioritized, or owned;
- keep authorization concepts distinct from command transport;
- produce explicit evidence rather than hidden side effects.

These modules may depend on domain types. They should not depend on Home Assistant entities or Pentair-specific state.

### Planning

Representative modules:

- `planning.py`
- `decision_planning.py`

Purpose:

- describe objectives and candidate approaches;
- construct deterministic alternatives from explicit facts;
- remain separate from final decision acceptance and execution.

Planning does not deliver commands and does not own equipment.

### Decision intelligence

Representative modules:

- `alternative_ranking.py`
- `decision_intelligence.py`
- `decision_orchestrator.py`
- `decision_stability.py`
- `explanations.py`
- `decision_flight_recorder.py`
- `evaluation_context.py`

Purpose:

- evaluate alternatives;
- rank outcomes;
- apply decision stability and churn control;
- create technical and human-readable explanations;
- produce immutable decision evidence.

Decision modules may depend on domain, policy, planning, and evaluation-context types. They must remain command-free.

### Supervisory composition

Representative modules:

- `runtime_trigger_submission.py`
- `runtime_trigger_coalescing.py`
- `supervisory_evaluation_assembly.py`
- `supervisory_evaluation_invocation.py`
- `supervisory_evaluation_runtime.py`

Purpose:

- accept explicit runtime submissions;
- coalesce deterministic triggers;
- assemble evaluation inputs;
- invoke the existing decision boundary;
- compose a complete command-free evaluation cycle;
- preserve provenance and deterministic identities.

Supervisory composition must not poll, persist, schedule background tasks, or perform equipment I/O.

### Operational disposition and routing

Representative modules:

- `operational_disposition.py`
- `operational_disposition_orchestrator.py`

Purpose:

- translate accepted decision evidence into a command-free operational recommendation;
- decide whether execution should wait, retain, submit, cancel, replace, block, or request review;
- identify the next logical boundary without invoking it.

These modules sit between cognition and execution. They do not build vendor commands or mutate execution state.

### Execution

Representative modules follow the `execution_*.py` naming family and include plan, authorization, coordinator, lifecycle, verification, recovery, delivery, and flight-record responsibilities.

Purpose:

- accept canonical execution proposals;
- authorize work;
- build immutable ordered plans;
- advance lifecycle state;
- request delivery through narrow adapters;
- verify observed outcomes;
- recommend recovery;
- record complete execution evidence.

Execution may depend on domain, authority, policy, and accepted decision identities. Core execution models must not depend on Pentair or Home Assistant implementation types.

### Simulation

Representative modules:

- `simulator.py` and related simulator modules;
- `closed_loop_simulator_execution.py`;
- `golden_scenarios.py`.

Purpose:

- provide deterministic equipment behavior;
- exercise execution without hardware;
- inject failures;
- validate replay and scenario equivalence;
- support safe development of new lifecycle behavior.

Simulator delivery is not a live adapter and must never be presented as proof of deployment readiness.

### Kernel and broad runtime

Representative modules:

- `kernel.py`
- `runtime.py`

These modules expose older or broader composition surfaces that remain supported for compatibility. New code should not automatically extend them simply because they are convenient. Prefer the narrow defining module for new subsystem work and consult the public API policy before adding root exports.

### IntelliCenter integration area

The `intellicenter/` package contains Pentair IntelliCenter-facing models and integration work.

Purpose:

- represent external controller data without contaminating core domain models;
- translate vendor-specific state at the edge;
- support future adapter boundaries.

It must not become the owner of goals, planning, decision policy, or execution authority.

## Tests as architecture evidence

The `tests/` directory is not merely implementation verification. It documents contracts.

Common test roles include:

- domain invariants;
- deterministic identity derivation;
- serialization and immutability;
- decision equivalence;
- supervisory composition;
- execution lifecycle progression;
- fault injection and recovery;
- golden scenarios;
- public API contracts;
- replay consistency.

When changing a boundary, read both the defining module and its focused tests. A behavior covered by tests is part of the effective contract even when it is not yet promoted to a stable public API.

## Documentation roles

### Architecture Manual

Explains enduring concepts, responsibilities, and dependency rules.

### ADRs

Record specific design decisions, alternatives, and consequences.

### Roadmap

Records milestone sequencing and implementation status.

### Public API policy

Defines stable root exports, compatibility exports, and preferred import behavior.

## Adding a new module

Before adding a module, answer:

1. Which conceptual layer owns this responsibility?
2. Is an existing module already the canonical owner?
3. What inputs and outputs form the boundary?
4. Can the implementation be pure and deterministic?
5. Which dependencies are allowed?
6. Does it perform I/O, scheduling, persistence, or actuation?
7. Is a new public export actually required?
8. Which focused tests will define the contract?
9. Does the change require an ADR or manual update?

A new module should have one clear reason to exist. Avoid “manager,” “service,” or “utils” modules that accumulate unrelated responsibilities.

## Physical structure versus conceptual structure

PoolOS may later introduce subpackages or facades. Until then, the flat package is not permission for unrestricted imports.

The dependency direction remains conceptual:

```text
Domain
  -> Policy and Planning
  -> Decision Intelligence
  -> Supervisory Composition
  -> Operational Routing
  -> Execution
  -> Integration
```

Cross-cutting evidence modules such as clocks, identities, explanations, and flight records should remain narrow and explicit.

## Responsibilities

This chapter maps repository locations to architectural responsibilities and gives contributors a safe starting point for navigation and module placement.

## Non-responsibilities

It does not freeze the filesystem layout, declare every module public, or authorize package moves. Physical reorganization requires compatibility analysis and a dedicated milestone.

## Future evolution

A later architecture review may introduce subsystem facades or physical subpackages. Such changes should reduce ambiguity without breaking compatibility imports silently or creating circular dependencies.
