# Public API Integration

## Purpose

Architecture boundaries are useful only when callers can identify which interfaces are intended for reuse and which are implementation details. This chapter connects the conceptual architecture to the existing PoolOS public API policy.

The canonical contract remains [PoolOS Public API Policy](../PUBLIC_API.md). This chapter explains how contributors should apply that policy across subsystems.

## Current API surfaces

PoolOS currently has three practical API categories.

### Stable root API

The stable wildcard API is deliberately small. The symbols declared in `poolos.__all__` are:

- `BodyType`
- `CommandPriority`
- `EquipmentType`
- `HeatingSource`
- `PolicyPriority`
- `RecommendationSeverity`

These names are broad domain vocabulary suitable for stable root import.

### Compatibility root API

`poolos/__init__.py` historically re-exports many additional names. They remain directly importable for compatibility but are not automatically long-term stable root APIs.

Examples include:

- `PoolKernel`
- `PoolRuntime`
- `RuntimeContext`
- `PlanObjective`
- `PolicyEngine`
- `ExecutionPlan`
- `ExecutionCoordinator`
- `ClosedLoopSimulatorExecutionEngine`

Compatibility means “do not break existing callers without a deliberate migration,” not “promote every name into the permanent root contract.”

### Defining-module and subsystem APIs

New code should normally import from the module that owns the concept.

```python
from poolos.supervisory_evaluation_runtime import SupervisoryEvaluationRuntime
from poolos.operational_disposition import OperationalDispositionEngine
from poolos.execution_coordinator import ExecutionCoordinator
```

This import style exposes responsibility and reduces accidental coupling to the root package.

## Architectural API rule

> Public interfaces should expose domain intent and immutable evidence, not internal orchestration convenience.

A good subsystem API:

- uses canonical domain types;
- accepts explicit immutable input;
- returns explicit immutable output;
- preserves deterministic identity and provenance;
- declares failure rather than hiding it;
- avoids vendor-specific entity IDs in core contracts;
- does not require callers to mutate internal state;
- does not perform unrelated I/O as a side effect.

## Domain API

Domain types are the shared language of the system.

Appropriate public candidates include:

- body and equipment classifications;
- capability descriptions;
- canonical commands and observations;
- policy priority and recommendation severity;
- immutable configuration and value objects.

Domain APIs should be stable, small, and dependency-light. They must not import execution, supervisory, Home Assistant, or Pentair implementation modules.

## Planning API

A planning boundary should accept:

- explicit objective;
- canonical observations;
- relevant constraints and policies;
- explicit evaluation time where time matters.

It should return deterministic planning evidence or candidate alternatives.

It should not:

- issue commands;
- acquire ownership;
- schedule work;
- read Home Assistant state directly;
- hide current time or environment access.

## Decision API

A decision boundary should accept a complete evaluation context and planning evidence. It should return:

- selected, deferred, blocked, or no-op decision evidence;
- ranked alternatives where applicable;
- explanation evidence;
- deterministic decision identity;
- provenance needed for replay.

A decision result is not an execution plan and must not imply authorization.

## Supervisory runtime API

The supervisory API composes existing deterministic boundaries.

Its external contract should remain explicit about:

- accepted trigger submissions;
- trigger coalescing evidence;
- evaluation and invocation timestamps;
- assembled context identity;
- prior-decision continuity;
- orchestration result;
- operational disposition;
- routing recommendation.

The supervisory API must remain command-free. It should not expose hidden polling loops, persistence handles, Home Assistant objects, or vendor clients as required inputs.

## Operational disposition API

Operational disposition converts decision evidence into a recommendation for the execution side.

Appropriate outputs include:

- wait;
- schedule reevaluation;
- submit a new plan;
- retain an existing plan;
- cancel a plan;
- replace a plan;
- block;
- request review.

This API identifies what boundary should be considered next. It does not invoke that boundary or mutate its state.

## Execution API

The execution API should separate distinct responsibilities rather than expose one unrestricted “execute” function.

Expected boundaries include:

1. proposal creation;
2. authorization;
3. plan construction;
4. lifecycle advancement;
5. delivery request;
6. delivery receipt;
7. verification;
8. recovery recommendation;
9. execution flight recording.

Each boundary should consume and produce immutable evidence with stable identities.

Core execution APIs must use canonical operations. Vendor service names and Home Assistant entity IDs belong in adapters.

## Simulator API

Simulator APIs support deterministic state evolution and fault injection.

A simulator boundary should:

- accept explicit simulated state and operation;
- return deterministic updated state and receipts;
- allow controlled fault scenarios;
- avoid network, clock, or filesystem dependence unless injected;
- remain impossible to confuse with commissioned live delivery.

Simulator APIs may mirror execution adapter contracts where useful, but their mode and evidence must remain explicit.

## Integration API

Integration boundaries translate between external systems and canonical PoolOS contracts.

Observation adapters should return:

- canonical state;
- source identity;
- observation time;
- freshness or quality evidence;
- connection or availability status.

Delivery adapters should accept only already authorized canonical operations and return:

- delivery attempt identity;
- adapter identity and version;
- transport outcome;
- vendor correlation data where available;
- error evidence without false normalization;
- no fabricated verification.

An integration API must not make planning or policy decisions.

## API identity requirements

For deterministic boundaries, IDs should derive from canonical input evidence when the operation is conceptually reproducible. For delivery attempts or external events, identities may also include explicit attempt or correlation evidence.

APIs should not generate opaque random identifiers when callers need replay equivalence, unless nondeterministic uniqueness is a documented requirement.

Every downstream record should preserve the upstream IDs needed to reconstruct lineage.

## Time requirements

Time is data.

Public subsystem APIs should accept explicit timezone-aware timestamps when behavior or identity depends on time. They should not call the wall clock deep inside deterministic logic.

Clock access belongs at a runtime boundary and should be injected into lower-level code when necessary.

## Error model

Public APIs should distinguish:

- invalid input;
- blocked or unauthorized work;
- unavailable dependency;
- stale evidence;
- transport failure;
- verification failure;
- timeout;
- unsupported capability;
- internal invariant violation.

Do not collapse these into a generic false result or a successful no-op. The distinction matters for safety, retry behavior, explanation, and replay.

## Serialization

Evidence intended for persistence, replay, or inter-process boundaries should have deterministic serialization rules:

- stable field meanings;
- explicit enum values;
- sorted or canonicalized mappings where identity depends on them;
- timezone-aware timestamps;
- no unserializable runtime clients;
- no reliance on object memory identity;
- backward-compatibility planning before schema changes.

## Import guidance

### Preferred

```python
from poolos.execution_authorization import ExecutionAuthorizationEngine
from poolos.supervisory_evaluation_assembly import SupervisoryEvaluationInputAssembler
```

### Acceptable for currently stable root vocabulary

```python
from poolos import BodyType, EquipmentType
```

### Compatibility-only; avoid in new code unless specifically required

```python
from poolos import PoolRuntime, ExecutionCoordinator
```

### Avoid

```python
from poolos import *
```

Wildcard import hides subsystem ownership and makes compatibility cleanup harder.

## Adding or changing an API

Before changing a public or compatibility-facing interface:

1. identify the owning subsystem;
2. classify the current surface as stable, compatibility, subsystem, or internal;
3. inspect repository callers and tests;
4. preserve deterministic identity semantics;
5. define migration behavior;
6. update focused contract tests;
7. update `docs/PUBLIC_API.md` when classification changes;
8. add an ADR for material compatibility or facade decisions;
9. do not expand `poolos.__all__` silently.

## Facades

Future subsystem facades may improve discoverability, for example a narrow planning or execution import surface. A facade should:

- expose a small reviewed contract;
- re-export only subsystem-owned concepts;
- avoid importing every implementation class;
- preserve dependency direction;
- include contract tests;
- have an explicit compatibility policy.

A facade is not a dumping ground and should not recreate the root-package problem at a lower level.

## Relationship to tests

The public API contract tests protect declared root behavior. Focused subsystem tests protect defining-module contracts. Both are necessary:

- root tests prevent accidental import breakage;
- subsystem tests preserve behavior, identity, immutability, and serialization;
- integration tests verify composition without converting internal details into public APIs.

## Responsibilities

This chapter explains how domain, planning, decision, supervisory, operational, execution, simulation, and integration boundaries should expose reusable contracts while preserving the existing root API policy.

## Non-responsibilities

It does not promote new stable symbols, remove compatibility exports, create subsystem facades, or authorize package moves. Those changes require dedicated implementation and compatibility milestones.

## Future evolution

A later API-classification milestone may inventory every compatibility export and introduce reviewed subsystem facades. Until then, defining-module imports remain the preferred pattern for new code.
