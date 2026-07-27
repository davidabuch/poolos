# ADR-007: Canonical Operation Boundary Between Planning and Hardware Integration

- **Status:** Accepted for Milestone 10.4 implementation
- **Date:** 2026-07-27
- **Decision owners:** PoolOS architecture
- **Supersedes:** None
- **Related:** ADR-003, ADR-006

## Context

PoolOS currently has two hardware-independent representations of intended work:

1. `poolos.commands.Command`
   - consumed by the existing planner, scheduler, policy, authority, runtime, and execution path;
   - intentionally generic (`target`, `action`, `value`);
   - currently embedded in `PlanStep.commands`.

2. `poolos.integration.operations.PoolOperation`
   - consumed by the vendor translation framework;
   - strongly typed (`SetPumpSpeed`, `StartPump`, `StopPump`, `SetHydraulicRoute`, and `SetHeatMode`);
   - translated into transport-neutral `VendorCommand` objects.

Both abstractions are vendor-independent, but they serve overlapping purposes. Adding hydraulic-route objectives without resolving this overlap would create one of three undesirable outcomes:

- the planner would emit Pentair-specific commands, violating the PoolOS domain boundary;
- route intent would be encoded as an untyped generic command and repeatedly decoded downstream;
- a second planner or parallel plan model would be introduced.

The repository also contains three adjacent hardware-facing areas whose responsibilities must remain distinct:

- `poolos/hal/`
- `poolos/integration/`
- `poolos/vendors/`

Milestone 10.4 must establish a single forward architecture before adding route planning.

## Decision

### 1. `PoolOperation` is the canonical planner-to-hardware work contract

The long-term execution pipeline is:

```text
Goal / Objective
        ↓
Planner and planning strategies
        ↓
Plan containing canonical PoolOperation work
        ↓
Scheduling, policy, constraints, and authority
        ↓
Execution and reconciliation
        ↓
Integration translator
        ↓
VendorCommand
        ↓
Vendor adapter and transport
        ↓
Physical equipment
```

Planning strategies may reason about domain goals and physical requirements, but they must emit only canonical PoolOS operations. They must not emit vendor commands, Home Assistant service calls, entity IDs, protocol payloads, or controller-specific aliases.

### 2. `Command` remains a supported legacy orchestration contract during migration

`Command` will not be deleted or redefined in Milestone 10.4. Existing planner, scheduler, runtime, policy, authority, execution, and test behavior must remain compatible while operation-native support is introduced.

`Command` is classified as the legacy orchestration representation. New hardware capabilities should not be modeled first as generic `Command` values when a typed `PoolOperation` can express them.

### 3. Migration will use one explicit compatibility boundary

A narrow compatibility component will bridge legacy `Command` objects into canonical `PoolOperation` objects where an unambiguous mapping exists.

The bridge must:

- be explicit and independently tested;
- reject ambiguous commands rather than infer hidden semantics;
- preserve correlation and metadata where applicable;
- contain no vendor-specific behavior;
- exist at the execution/integration boundary, not inside planning strategies or translators.

The bridge is transitional infrastructure, not a third command model.

### 4. Plan evolution must preserve one `Plan` and one `PlanStep`

PoolOS will not introduce a second planner, a parallel planning package, or a second plan hierarchy.

`PlanStep` will evolve to carry typed canonical work while maintaining compatibility for existing callers. The implementation must use a deliberate migration mechanism with explicit serialization and validation. An unconstrained `Any` field or arbitrary heterogeneous union is not acceptable.

The exact compatibility mechanism is an implementation detail of Milestone 10.4, but it must satisfy these constraints:

- one ordered step model;
- one dependency model;
- one lifecycle model;
- deterministic serialization;
- explicit work-item type identity;
- backward compatibility for current `commands` consumers during the migration window.

### 5. Layer ownership is defined as follows

#### Core domain and planning

Owns:

- goals and objectives;
- physical pool semantics;
- planning strategies;
- canonical operations required to satisfy a plan;
- rationale, assumptions, dependencies, timing, and completion conditions.

Must not own:

- vendor command names;
- protocol fields;
- Home Assistant entities or services;
- transport retries or delivery.

#### Execution and reconciliation

Owns:

- validation and admission of planned work;
- priority, deduplication, lifecycle, and audit;
- dispatch toward the canonical operation boundary;
- comparison of requested outcomes with observed state;
- retry, failure, and replan signals at the orchestration level.

Must not own:

- Pentair-specific command construction;
- raw transport calls;
- vendor capability naming.

#### Integration translation

Owns:

- translation from canonical `PoolOperation` types to `VendorCommand` objects;
- validation that required translation context and vendor capabilities are present;
- deterministic vendor command construction.

Must not own:

- planning;
- authorization policy;
- runtime safety sequencing;
- transport delivery;
- state reconciliation.

#### HAL

Owns:

- stable runtime-facing equipment contracts;
- equipment discovery and observations;
- adapter lifecycle and health;
- capability exposure;
- command receipts and physical-device interaction contracts.

HAL represents physical equipment behavior and observations. It does not decide which operation should occur.

#### Vendor packages

Own:

- vendor identities and domain models;
- vendor-specific adapter implementations;
- vendor-specific capability and configuration models;
- composition of translators, HAL equipment implementations, and transports for a vendor family.

Vendor packages must not leak vendor types into core planning models.

#### Transport

Owns:

- protocol delivery;
- connection management;
- serialization and I/O;
- transport-level timeout and retry mechanics;
- raw response handling.

Transport must not interpret user goals or pool operating policy.

### 6. Hydraulic routes use `SetHydraulicRoute`

The four accepted user-facing route intents map to canonical route operations:

| Intent | Suction body | Return body |
|---|---|---|
| Pool | Pool | Pool |
| Spa | Spa | Spa |
| Spillway | Pool | Spa |
| Drain Hot Tub | Spa | Pool |

The planner will express route work with `SetHydraulicRoute`. It will not emit `ActivateBody`, Pentair circuit commands, or direct valve commands.

Authorization and runtime safety for Drain Hot Tub remain downstream responsibilities and are not granted merely because the planner can represent the route.

## Consequences

### Positive

- PoolOS gains one typed, vendor-independent representation for new hardware work.
- The existing mature planner remains the only planner.
- Vendor translation remains isolated from goals, scheduling, policy, and authority.
- Route planning can be added without encoding Pentair behavior in the planner.
- The legacy runtime can migrate incrementally rather than through a repository-wide rewrite.

### Negative

- Milestone 10.4 must carry a temporary compatibility path.
- Plan serialization and public API compatibility require focused tests.
- Some existing generic commands may eventually need typed operation equivalents.
- The execution engine cannot become fully operation-native in one small milestone without broad changes.

### Risks

- A permissive compatibility bridge could become permanent technical debt.
- Supporting commands and operations without strict ownership could create duplicate execution paths.
- Renaming or replacing `PlanStep.commands` too early could break downstream consumers.

These risks are controlled by requiring one bridge, explicit type handling, contract tests, and a time-bounded migration roadmap.

## Milestone 10.4 implementation sequence

1. Add contract tests that freeze current `Plan`, `PlanStep`, and `Command` behavior.
2. Add goal/intention models above the current planner without creating a new planner service.
3. Add explicit typed planned-work support to the existing `PlanStep` model.
4. Add the narrow legacy-command-to-operation compatibility boundary.
5. Add hydraulic-route objective support to the existing strategy registry.
6. Emit `SetHydraulicRoute` for Pool, Spa, Spillway, and Drain Hot Tub intents.
7. Verify that policy, authority, execution, integration, and existing planner tests remain green.
8. Update architecture and roadmap documents to reflect the implemented boundary.

## Deferred decisions

The following are explicitly outside this ADR and should be handled separately:

- removal of the legacy `Command` model;
- full conversion of the execution queue to `PoolOperation`;
- deletion of the duplicate IntelliCenter source tree;
- restructuring root package exports;
- redesign of HAL adapter APIs;
- vendor transport implementation details;
- runtime valve sequencing, priming, and flow verification.

## Compliance rules

A future change violates this ADR if it:

- adds a second planner or plan model;
- allows planning code to construct `VendorCommand` objects;
- adds Pentair-specific fields to a core objective or operation;
- lets translators perform authorization, scheduling, or safety policy decisions;
- introduces a second generic compatibility command abstraction;
- treats Drain Hot Tub planning support as execution authorization.
