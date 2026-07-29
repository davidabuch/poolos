# Buch IntelliCenter Architecture

## 1. Purpose

Buch IntelliCenter is a Home Assistant custom integration for Pentair IntelliCenter equipment. It provides a stable, typed, and observable boundary between the Pentair controller and higher-level pool automation logic.

The repository is currently a single Home Assistant integration package. During development, the future Command Center will remain inside the existing `intellicenter` package. A later split into a separate integration may be considered only after the design and public contracts are mature.

## 2. Core Boundary

Buch IntelliCenter answers:

> What is the equipment doing, what can it do, and how can it be commanded safely?

The Command Center answers:

> What should the equipment be doing right now?

These responsibilities must remain separate even while both components live in the same package.

## 3. Layered Architecture

```text
Pentair IntelliCenter controller
            |
            v
      pyintellicenter
            |
            v
IntelliCenterCoordinator
            |
            v
Immutable IntelliCenter API
      |             |
      v             v
HA entity layer   Command Center
                    |
                    v
              Decision Engine
                    |
                    v
           DesiredEquipmentState
                    |
                    v
            Ownership Manager
                    |
                    v
             Execution Engine
                    |
                    v
           Command Dispatcher
                    |
                    v
      Pentair controller commands
```

## 4. Repository Layout

Current and planned layout:

```text
buch-intellicenter/
├── .github/
│   └── workflows/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API_CONTRACT.md
│   ├── DEVELOPMENT_GUIDELINES.md
│   ├── ROADMAP.md
│   └── adr/
├── intellicenter/
│   ├── api/                  # Immutable read models and API facade
│   ├── command_center/       # Future policy and orchestration layer
│   │   ├── decision_engine.py
│   │   ├── execution_engine.py
│   │   ├── models.py
│   │   ├── ownership.py
│   │   ├── power_manager.py
│   │   ├── safety_manager.py
│   │   └── scheduler.py
│   ├── binary_sensor.py
│   ├── climate.py
│   ├── coordinator.py
│   ├── cover.py
│   ├── light.py
│   ├── number.py
│   ├── select.py
│   ├── sensor.py
│   └── switch.py
└── tests/
```

The `command_center/` directory is planned, not yet a requirement for the current stable release.

## 5. Coordinator Responsibilities

`IntelliCenterCoordinator` owns communication lifecycle concerns:

- Controller connection and reconnection
- Live Pentair model synchronization
- Push-update processing
- Discovery of equipment objects
- Scheduling Home Assistant refreshes
- Exposing the authoritative controller and model to internal consumers

The coordinator must not contain scheduling policy, ownership policy, or high-level pool operating decisions.

## 6. Immutable API

The immutable API is the normalized read boundary for Home Assistant entities and future Command Center components.

It must:

- Read from the coordinator's authoritative live model
- Return immutable snapshots rather than raw mutable `PoolObject` instances
- Normalize Pentair-specific attributes and values
- Preserve unknown, unavailable, and unsupported states explicitly
- Expose stable identifiers independent of Home Assistant entity IDs
- Remain free of scheduling and operational policy

The immutable API is read-only by design. Command execution belongs to the Execution Engine and Command Dispatcher.

## 7. Home Assistant Entity Layer

Home Assistant entities are presentation and interaction adapters. They should:

- Read state through the immutable API
- Translate immutable models into Home Assistant entity properties
- Avoid direct reads from raw `PoolObject` attributes when an immutable API model exists
- Avoid embedding policy decisions
- Avoid restoring stale state snapshots
- Preserve existing entity identifiers and behavior whenever practical

Entity service calls and user actions may request changes, but command delivery should migrate toward the single Execution Engine path described below.

## 8. Command Center

The Command Center is the future policy layer inside the existing `intellicenter` package. It will contain the following components.

### 8.1 Decision Engine

The Decision Engine evaluates current conditions and produces a complete `DesiredEquipmentState`.

Inputs may include:

- Current immutable equipment snapshot
- Time and schedules
- Water temperatures
- Heating and solar availability
- User-requested operating state
- Safety conditions
- Power availability
- Equipment faults

It must not send hardware commands directly.

### 8.2 Desired Equipment State

`DesiredEquipmentState` is a strongly typed, immutable description of what the system should be doing now.

It should distinguish between:

- Explicitly on
- Explicitly off
- A requested target value
- Unmanaged or no-op state
- Unsupported state

This distinction prevents accidental commands caused by default values.

### 8.3 Ownership Manager

The Ownership Manager determines which component has authority to control each managed equipment function.

Initial priority model:

```text
SAFETY
  > MANUAL
  > POOL_MANAGER
  > NONE
```

Ownership must be explicit, inspectable, and restart-safe. A safety owner may override normal operation only while the safety condition exists.

### 8.4 Execution Engine

The Execution Engine is the only component permitted to send commands to the Pentair controller once the Command Center command path is implemented.

All command requests, including manual Command Center actions, must flow through it.

The Execution Engine will:

- Compare current state with desired state
- Enforce ownership
- Suppress redundant commands
- Apply safety constraints
- Order dependent commands correctly
- Dispatch commands through one audited path
- Record command results and failures
- Trigger reevaluation when appropriate

It must be idempotent: applying the same desired state repeatedly should not repeatedly send the same command.

### 8.5 Safety Manager

The Safety Manager evaluates safety conditions and creates the highest-priority safety constraints.

Planned safety reasons include:

- Power outage
- Freeze protection
- Critical equipment fault
- Pump failure
- Water loss
- Emergency shutdown

Safety modes should temporarily override normal operation and release ownership immediately when the safety condition clears.

## 9. Power Outage Safety Mode

Power outage handling belongs above the immutable API.

Authoritative trigger:

```text
binary_sensor.1_powerwall_grid_status
```

The separate three-Powerwall system is not authoritative for the pool equipment panel and must not control this safety mode.

Activation condition:

```text
Grid status = off for 2 seconds
```

While active:

- Spa must be off
- Waterfall must be off
- Jets must be off
- Slide must be off
- Pool light must be off
- The Decision Engine still decides whether circulation should run
- If circulation should be off, it remains off
- If circulation should be on, actual commanded pump speed is limited to 1800 RPM

Actual pump speed is observed from:

```text
sensor.buch_family_vs_rpm
```

Pentair RPM preset entities are configuration values and must not be treated as actual pump speed.

When utility power returns, the system must not restore a pre-outage snapshot. It must release safety ownership and immediately perform a complete Decision Engine reevaluation using current conditions.

## 10. Command and State Rules

1. Read state from the immutable API, not from Home Assistant entity state.
2. Do not use preset RPM configuration entities as actual pump-speed telemetry.
3. Do not restore stale equipment snapshots after temporary overrides.
4. Reevaluate current conditions whenever an override ends.
5. Avoid commands when current state already matches desired state.
6. Preserve unknown values instead of coercing them to normal values.
7. Keep command ordering deterministic and testable.
8. Log enough context to explain why each command was or was not sent.

## 11. Restart Safety

After a Home Assistant or integration restart:

- The coordinator reconnects and rebuilds authoritative state
- The immutable API exposes the rebuilt snapshot
- Safety conditions are reevaluated immediately
- Ownership is recomputed from current facts
- The Decision Engine produces a new desired state
- The Execution Engine reconciles current and desired state

Correct behavior must not depend on in-memory snapshots from before the restart.

## 12. Observability

The integration should eventually expose diagnostic information for:

- Current operating mode
- Active safety reason
- Current owner by equipment function
- Desired equipment state
- Last evaluation time and reason
- Last command and result
- Suppressed duplicate commands
- Current controller availability

These diagnostics must not expose secrets or authentication material.

## 13. Testing Strategy

Testing is layered:

1. Immutable API unit tests
2. Entity/API contract tests
3. Decision Engine pure-function tests
4. Ownership priority tests
5. Execution Engine reconciliation tests
6. Restart and recovery tests
7. Home Assistant runtime validation before release

A repository build is not deployment-ready merely because API unit tests pass. Entity imports and contracts must also be validated.

## 14. Deployment Strategy

The Git repository is the development source of truth. Home Assistant is a deployment target.

During Milestone 1:

- Changes are made and tested in the repository
- Complete files are committed and pushed to GitHub
- The installed Home Assistant integration is not updated file-by-file
- A full integration package is deployed only when the repository is internally consistent
- The existing Home Assistant integration backup remains available for rollback

## 15. Future Separation

The Command Center may later become a separate `pool_manager` integration when all of the following are true:

- Its public contracts are stable
- It no longer depends on private IntelliCenter internals
- It can consume the immutable API through a supported boundary
- Separate versioning and deployment provide clear value

Until then, physical separation is deferred while architectural separation is maintained.


## Runtime Environment Safety Boundary

PoolOS startup composition is represented by an immutable
`PoolRuntimeEnvironment`. Simulation, shadow, and live modes admit different
writable endpoint classifications before the command gateway is constructed.
Observation access is independent: simulation may read approved live sensors
while remaining structurally unable to deliver physical commands. See
[ADR-009](adr/ADR-009-runtime-environment-safety-boundary.md).

## Canonical Observation Type

PoolOS has one canonical observation model: `PoolObservation`, owned by the
`poolos.observations` package. The historic `poolos.domain.Observation` symbol
is retained temporarily as an exact compatibility alias, not as a second type
or subclass. New code must import and use `PoolObservation`; existing callers
may migrate incrementally without changing runtime type identity.
