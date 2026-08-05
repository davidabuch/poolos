# Capability Map

> **Architecture Manual v1.0** · Chapter 4 of 15

## Purpose

This chapter describes PoolOS by capability rather than by class or file. It is the fastest way to understand what the system does and how responsibilities are divided.

## Executive capability map

```text
External facts and operator intent
                |
                v
+---------------------------------------------+
| Observation and Environment                 |
| telemetry | forecasts | freshness | quality |
+---------------------------------------------+
                |
                v
+---------------------------------------------+
| Cognitive System                            |
| goals | policies | planning | ranking       |
| decisions | explanations | flight records   |
+---------------------------------------------+
                |
                v
+---------------------------------------------+
| Supervisory Runtime                         |
| submission | coalescing | assembly          |
| invocation | disposition | routing evidence |
+---------------------------------------------+
                |
                v
+---------------------------------------------+
| Execution System                            |
| proposals | authorization | plans           |
| lifecycle | verification | recovery         |
+---------------------------------------------+
                |
                v
+---------------------------------------------+
| Integration Layer                           |
| Home Assistant | Pentair | future vendors   |
+---------------------------------------------+
```

No layer may bypass the layer below it to perform hardware actuation.

## Observation and environment

### Why it exists

The system needs a trustworthy, typed representation of current reality before it can reason safely.

### Primary inputs

- controller telemetry;
- Home Assistant state;
- weather and forecast data;
- simulator state;
- configuration and installation knowledge;
- explicit freshness and quality information.

### Primary outputs

- canonical observations;
- observation provenance;
- freshness and quality classifications;
- runtime environment facts;
- normalized equipment and body state.

### Responsibilities

- normalize external facts;
- preserve source and time evidence;
- distinguish unknown, stale, unavailable, and invalid information;
- provide vendor-independent observations to higher layers.

### Non-responsibilities

- choosing a plan;
- deciding what equipment should do;
- authorizing execution;
- sending commands.

## Cognitive system

### Why it exists

Facts alone do not determine what should happen. The cognitive system evaluates goals, policies, constraints, alternatives, and expected outcomes.

### Primary inputs

- evaluation context;
- goals and objectives;
- current observations;
- forecasts;
- active policies;
- prior decision evidence;
- candidate alternatives.

### Primary outputs

- ranked alternatives;
- selected, blocked, or deferred decisions;
- human-readable explanations;
- technical explanations;
- decision flight records;
- stability and churn-control evidence.

### Responsibilities

- evaluate alternatives deterministically;
- explain why an option was selected or blocked;
- preserve prior-decision continuity where appropriate;
- remain command-free and vendor-independent.

### Non-responsibilities

- scheduling hardware actions;
- delivering commands;
- mutating controller state;
- performing vendor-specific translation.

## Supervisory runtime

### Why it exists

The cognitive capabilities are individually deterministic, but production use requires one reviewed composition path for a complete supervisory evaluation cycle.

### Primary inputs

- accepted runtime submissions;
- coalesced triggers;
- explicit evaluation and invocation times;
- current planning facts;
- optional prior-decision evidence;
- optional current execution-plan summary.

### Primary outputs

- assembled evaluation context;
- orchestration result;
- operational disposition;
- command-free routing instruction;
- deterministic runtime and provenance identities.

### Responsibilities

- compose existing boundaries without duplicating their logic;
- preserve identity and provenance across the complete cycle;
- translate a decision into an operational recommendation;
- remain simulation-safe and non-actuating.

### Non-responsibilities

- polling;
- retries;
- persistence I/O;
- execution authorization;
- command delivery;
- Home Assistant or Pentair communication.

## Operational routing

Operational routing sits at the boundary between cognition and execution.

### Primary inputs

- accepted decision evidence;
- current plan summary;
- operational disposition.

### Primary outputs

- wait;
- schedule reevaluation;
- submit new plan;
- retain plan;
- cancel plan;
- replace plan;
- block or request review.

### Responsibilities

- express what the execution side should consider next;
- identify the logical target boundary;
- remain command-free.

### Non-responsibilities

- invoking the target;
- building vendor commands;
- mutating an execution plan;
- scheduling background work.

## Execution system

### Why it exists

A good decision is not yet a safe action. The execution system turns accepted intent into authorized, ordered, observable, and recoverable work.

### Primary inputs

- canonical execution proposals;
- accepted decision identity;
- operational routing instruction;
- runtime mode and authority;
- current execution state;
- verification evidence.

### Primary outputs

- execution authorization;
- immutable execution plans;
- lifecycle transitions;
- delivery receipts;
- verification results;
- recovery recommendations;
- execution flight records.

### Responsibilities

- authorize intent;
- construct deterministic plans;
- control lifecycle progression;
- verify observed outcomes;
- terminate safely after faults;
- preserve ordered execution evidence.

### Non-responsibilities

- choosing the original goal;
- ranking decision alternatives;
- embedding vendor-specific transport logic in core models;
- bypassing runtime mode or authority.

## Simulation

Simulation supports both cognitive and execution capabilities.

### Responsibilities

- provide deterministic equipment state;
- accept simulator-only delivery;
- exercise lifecycle transitions;
- inject faults;
- produce golden scenarios;
- validate replay equivalence.

### Non-responsibilities

- proving Home Assistant deployment readiness;
- proving vendor protocol correctness;
- authorizing live equipment actuation.

## Integration layer

### Why it exists

External platforms and hardware speak in vendor-specific entities, services, protocols, and state models. The integration layer translates those details at the edge.

### Current integration areas

- Home Assistant observation and publication boundaries;
- IntelliCenter immutable read models;
- future Home Assistant custom-component deployment;
- future Pentair command delivery;
- future vendor adapters.

### Responsibilities

- translate external state into canonical observations;
- translate approved canonical operations into platform-specific requests;
- manage platform lifecycle and connectivity;
- preserve the core safety and delivery contracts.

### Non-responsibilities

- redefining policy;
- selecting decision alternatives;
- bypassing execution authorization;
- allowing entity code to become the supervisory authority.

## Capability responsibility matrix

| Capability | Understands goals | May create decisions | May create execution plans | May communicate externally | May actuate live hardware |
|---|:---:|:---:|:---:|:---:|:---:|
| Observation | No | No | No | Read only | No |
| Cognitive system | Yes | Yes | No | No | No |
| Supervisory runtime | Yes | Composes | No | No | No |
| Operational routing | No | No | No | No | No |
| Execution system | No | No | Yes | Through adapters only | Not directly |
| Simulator | No | No | Simulated only | Simulator only | No |
| Integration layer | No | No | No | Yes | Only after explicit commissioning |

## End-to-end conceptual flow

```text
Observe reality
    -> build context
    -> evaluate goals and alternatives
    -> select and explain a decision
    -> determine operational disposition
    -> authorize and build execution work
    -> deliver through an adapter
    -> verify observed outcome
    -> record evidence
```

## Architectural rule

A higher layer may request work from the next lower layer, but it may not assume the lower layer's responsibility.

Examples:

- A decision may request execution, but it may not authorize itself.
- Execution may request vendor delivery, but it may not redefine the decision.
- An adapter may deliver a command, but it may not choose the goal.

## Responsibilities

This chapter provides the conceptual map used to place new capabilities and review subsystem boundaries.

## Non-responsibilities

It does not define detailed dependencies, package locations, identity derivation, or live commissioning requirements. Those are covered in later chapters.

## Future evolution

As new capabilities are added, they should fit within an existing layer whenever possible. A new layer should require a compelling architectural reason and an ADR.

---

[Previous: Guiding Principles](02-guiding-principles.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: System Layers](04-system-layers.md)
