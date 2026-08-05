# System Layers

> **Architecture Manual v1.0** · Chapter 5 of 15

## Purpose

This chapter defines the major architectural layers of PoolOS and explains where each responsibility belongs. The layers are conceptual boundaries. They guide package design, dependency review, testing, and future integration work even when several layers currently share the same Python package.

## Why layers exist

Pool automation combines facts, policy, planning, execution, and vendor communication. When those concerns are mixed together, a connectivity failure can affect decision logic, a hardware detail can leak into policy, or a user-interface action can bypass safety controls.

PoolOS separates these concerns so that each layer can be reasoned about independently.

## Layer model

```text
External systems and operators
            |
            v
+-------------------------------+
| Integration and Presentation  |
+-------------------------------+
            |
            v
+-------------------------------+
| Observation and Environment   |
+-------------------------------+
            |
            v
+-------------------------------+
| Cognitive System              |
+-------------------------------+
            |
            v
+-------------------------------+
| Supervisory Runtime           |
+-------------------------------+
            |
            v
+-------------------------------+
| Operational Routing           |
+-------------------------------+
            |
            v
+-------------------------------+
| Execution System              |
+-------------------------------+
            |
            v
+-------------------------------+
| Delivery Adapters             |
+-------------------------------+
            |
            v
      Physical equipment
```

The diagram shows responsibility flow, not a requirement that every implementation call pass through every box synchronously.

## Integration and presentation

### Why it exists

Home Assistant, dashboards, configuration flows, and vendor integrations expose external state and operator intent. They are the system's edge, not its decision authority.

### Responsibilities

- receive external observations and user requests;
- translate platform-specific data into canonical inputs;
- publish approved state and explanations;
- manage platform lifecycle and connectivity;
- surface health, freshness, and degraded operation.

### Non-responsibilities

- choosing goals or policies;
- ranking alternatives;
- authorizing execution;
- silently overriding safety decisions.

## Observation and environment

### Why it exists

The rest of PoolOS needs a typed, normalized, and time-aware representation of reality.

### Responsibilities

- normalize telemetry and configuration;
- preserve source, timestamp, freshness, and quality;
- distinguish unavailable, stale, invalid, and unknown facts;
- describe bodies, equipment, resources, weather, and installation state;
- provide vendor-independent facts to higher layers.

### Non-responsibilities

- selecting a plan;
- issuing commands;
- assuming that stale data is current truth.

## Cognitive system

### Why it exists

Current facts do not by themselves determine what should happen. The cognitive layer evaluates goals, policies, constraints, alternatives, and expected outcomes.

### Responsibilities

- construct and evaluate decision context;
- generate and rank alternatives;
- select, retain, defer, or block decisions;
- explain the result;
- preserve stability and prior-decision continuity;
- record decision evidence.

### Non-responsibilities

- creating vendor commands;
- owning equipment communication;
- advancing execution lifecycle state.

## Supervisory runtime

### Why it exists

Individually deterministic decision components still require one reviewed composition path for a complete evaluation cycle.

### Responsibilities

- accept and coalesce runtime triggers;
- assemble evaluation inputs;
- invoke the existing decision orchestrator exactly once;
- derive operational disposition;
- preserve deterministic identity and provenance;
- return command-free runtime evidence.

### Non-responsibilities

- polling external systems;
- retrying delivery;
- persisting work queues;
- actuating equipment.

## Operational routing

### Why it exists

A decision must be translated into what the execution side should consider next without performing execution itself.

### Responsibilities

- express wait, reevaluate, submit, retain, replace, cancel, or block outcomes;
- identify the appropriate downstream boundary;
- preserve decision and plan provenance.

### Non-responsibilities

- invoking the target boundary;
- changing equipment state;
- constructing vendor payloads.

## Execution system

### Why it exists

Accepted intent must become authorized, ordered, observable, verifiable, and recoverable work.

### Responsibilities

- generate execution proposals;
- enforce authority and runtime mode;
- construct deterministic execution plans;
- manage lifecycle transitions;
- verify outcomes;
- classify failure and recovery;
- preserve execution evidence.

### Non-responsibilities

- redefining the original goal;
- bypassing authority;
- embedding vendor protocols in core execution models.

## Delivery adapters

### Why they exist

Physical controllers and external platforms use vendor-specific protocols and service calls.

### Responsibilities

- translate approved execution steps into platform operations;
- return delivery receipts and errors;
- expose connectivity and capability constraints;
- preserve idempotency and attribution where supported.

### Non-responsibilities

- deciding whether a command is desirable;
- authorizing themselves;
- changing policy because a vendor API is convenient.

## Cross-cutting capabilities

Some capabilities span layers but do not erase layer boundaries:

- **Simulation** supplies deterministic observations and delivery without live actuation.
- **Flight recording** captures evidence from decision and execution boundaries.
- **Diagnostics** observe health without becoming the decision authority.
- **Configuration** supplies explicit facts but does not replace runtime evidence.
- **Human explanation** presents reasoning without altering it.

## Placement rule

A new capability belongs in the highest layer that can own it without assuming a lower layer's responsibility.

Examples:

- freshness classification belongs with observation;
- alternative ranking belongs with cognition;
- duplicate trigger coalescing belongs with supervision;
- authorization belongs with execution;
- HTTP, WebSocket, or Home Assistant service calls belong with adapters.

## Responsibilities

This chapter defines the conceptual layers used to place capabilities and review boundaries.

## Non-responsibilities

It does not prescribe a final directory reorganization or require one package per layer.

## Future evolution

Later cleanup may align package structure more closely with these layers. Such moves should preserve behavior and follow the public API policy.

---

[Previous: Capability Map](03-capability-map.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Dependency Rules](05-dependency-rules.md)
