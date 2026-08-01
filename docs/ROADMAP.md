# Buch IntelliCenter Development Roadmap

## Status Legend

- `DONE` — implemented and validated in the repository
- `IN PROGRESS` — active work item
- `READY` — defined and ready to begin
- `BLOCKED` — waiting on another work item or external dependency
- `PLANNED` — accepted but not yet ready

## Milestone 0 — Immutable API Foundation

| ID | Work item | Status |
|---|---|---|
| M0-001 | Body immutable model | DONE |
| M0-002 | Circuit immutable model | DONE |
| M0-003 | Pump and pump-program immutable models | DONE |
| M0-004 | Chemistry immutable model | DONE |
| M0-005 | Cover immutable model | DONE |
| M0-006 | System immutable model | DONE |
| M0-007 | Full snapshot API | DONE |
| M0-008 | Immutable API unit-test suite | DONE |

Milestone exit condition: immutable read models exist and their current unit tests pass.

## Milestone 1 — Repository Stabilization and Entity Migration

| ID | Work item | Status |
|---|---|---|
| M1-001 | Architecture and development documentation | IN PROGRESS |
| M1-002 | Stabilize climate immutable API contract | READY |
| M1-003 | Migrate climate platform fully to immutable API | PLANNED |
| M1-004 | Migrate sensor platform | PLANNED |
| M1-005 | Migrate binary sensor platform | PLANNED |
| M1-006 | Migrate switch platform | PLANNED |
| M1-007 | Migrate light platform | PLANNED |
| M1-008 | Migrate number platform | PLANNED |
| M1-009 | Migrate cover platform | PLANNED |
| M1-010 | Migrate select platform | PLANNED |
| M1-011 | Add entity import and contract tests | PLANNED |
| M1-012 | Add repository-wide compile and test checks | PLANNED |
| M1-013 | Verify entity identity and compatibility | PLANNED |
| M1-014 | Build complete deployment package | BLOCKED |
| M1-015 | Deploy complete integration to Home Assistant | BLOCKED |
| M1-016 | Runtime regression validation and rollback review | BLOCKED |

### Milestone 1 exit conditions

- Every supported entity platform imports successfully
- Every migrated platform reads through the immutable API where a model exists
- No platform references missing API methods
- Existing entity IDs and behavior are preserved unless a migration is documented
- Repository-wide tests pass in GitHub Actions
- The entire integration can be deployed as one matching package
- Home Assistant runtime validation succeeds

## Milestone 2 — Command Center Core

| ID | Work item | Status |
|---|---|---|
| M2-001 | Define strongly typed Command Center models | PLANNED |
| M2-002 | Define complete `DesiredEquipmentState` semantics | PLANNED |
| M2-003 | Build deterministic Decision Engine skeleton | PLANNED |
| M2-004 | Build Ownership Manager | PLANNED |
| M2-005 | Build Execution Engine reconciliation loop | PLANNED |
| M2-006 | Build single Command Dispatcher | PLANNED |
| M2-007 | Add command deduplication and ordering | PLANNED |
| M2-008 | Add restart-safe reevaluation | PLANNED |
| M2-009 | Add command and decision diagnostics | PLANNED |
| M2-010 | Route Command Center manual actions through Execution Engine | PLANNED |

### Milestone 2 exit conditions

- Decision logic produces desired state without sending commands
- Ownership is explicit and testable
- Execution Engine is the only Command Center path to controller writes
- Repeated reconciliation is idempotent
- Restart reconstructs correct state from current facts

## Milestone 3 — Safety Framework

| ID | Work item | Status |
|---|---|---|
| M3-001 | Define safety reason model and priority behavior | PLANNED |
| M3-002 | Build Safety Manager | PLANNED |
| M3-003 | Implement Power Outage safety mode | PLANNED |
| M3-004 | Implement grid restoration reevaluation | PLANNED |
| M3-005 | Add freeze-protection framework | PLANNED |
| M3-006 | Add critical-equipment-fault framework | PLANNED |
| M3-007 | Add emergency shutdown framework | PLANNED |

### Power Outage acceptance criteria

- Uses only `binary_sensor.1_powerwall_grid_status`
- Activates after two seconds off-grid
- Does not use `binary_sensor.3_powerwalls_grid_status`
- Turns off spa, waterfall, jets, slide, and pool light
- Does not force circulation on
- Limits commanded circulation to 1800 RPM when circulation is required
- Uses `sensor.buch_family_vs_rpm` as actual-speed telemetry
- Does not modify Pentair RPM preset configuration values
- Does not restore stale pre-outage state
- Releases safety ownership and reevaluates immediately when grid power returns
- Correct behavior is restored after a Home Assistant restart during an outage

## Milestone 4 — Normal Operations and Scheduling

| ID | Work item | Status |
|---|---|---|
| M4-001 | Formalize filtration scheduling | PLANNED |
| M4-002 | Formalize spa operation | PLANNED |
| M4-003 | Formalize heater coordination | PLANNED |
| M4-004 | Formalize solar coordination | PLANNED |
| M4-005 | Formalize water-feature coordination | PLANNED |
| M4-006 | Formalize lighting coordination | PLANNED |
| M4-007 | Add maintenance mode | PLANNED |
| M4-008 | Add vacation mode | PLANNED |

## Milestone 5 — Operations Center and Observability

| ID | Work item | Status |
|---|---|---|
| M5-001 | Expose operating mode diagnostics | PLANNED |
| M5-002 | Expose ownership diagnostics | PLANNED |
| M5-003 | Expose desired-state diagnostics | PLANNED |
| M5-004 | Integrate flight recorder | PLANNED |
| M5-005 | Build Home Assistant dashboard views | PLANNED |
| M5-006 | Add failure and recovery reporting | PLANNED |

## Deferred Decisions

The following are intentionally deferred:

- Splitting Command Center into a separate `pool_manager` integration
- Replacing Pentair RPM preset entities
- Automated deployment from GitHub to Home Assistant
- Public release or upstream merge strategy

Each deferred decision should receive an Architecture Decision Record before implementation.


## PoolOS Supervisory Runtime Milestones

| ID | Work item | Status |
|---|---|---|
| 10.5A | Immutable simulation/shadow/live runtime safety boundary | DONE |
| 10.5A.1 | Canonical `PoolObservation` type and compatibility alias | DONE |
| 10.5B | Typed observations, provenance, quality, and freshness | DONE |
| 10.5C | Hybrid Home Assistant observation bridge | DONE |
| 10.5D | Sim Pool state publication to Home Assistant | DONE |
| 10.5E | Home Assistant entity catalog and publication registry | DONE |
| 10.5F | Sim Pool dashboard and multi-day soak workflow | DONE |
| 10.6 | Decision validation and golden rule verification | DONE |
| 10.7 | Policy library and deterministic operating profiles | DONE |
| 10.8 | Goal-oriented planning facade | DONE |
| 10.9 | Deterministic energy and cost optimization | DONE |
| 10.10 | Canonical forecast intelligence and predictive planning signals | DONE |
| 10.11A | Immutable decision intelligence and explanation graph model | DONE |
| 10.11B | Deterministic alternative ranking engine | DONE |
| 10.11C | Human-readable explanation renderer | DONE |
| 10.11D | Technical explanation renderer | DONE |
| 10.11E | Explainable planner integration | DONE |
| 10.11F | Flight Recorder decision-intelligence integration | DONE |
| 10.11G | Home Assistant explanation entities and dashboard | DONE |
| 10.12A | Immutable decision evaluation context | DONE |
| 10.12B | Deterministic command-free decision orchestrator | DONE |
| 10.12C | Typed reevaluation trigger model | DONE |
| 10.12D | Decision stability and churn control | DONE |
| 10.12E | Restart recovery and deterministic replay | DONE |
| 10.12F | Home Assistant orchestration diagnostics | DONE |
| 10.12G | Integrated soak and golden scenarios | DONE |

## PoolOS Simulator Execution Milestones

| ID | Work item | Status |
|---|---|---|
| 10.13A-J | Supervisory execution framework | DONE |
| 10.14A | Simulator-only execution gateway composition | DONE |
| 10.14B | Execution-step to simulator-gateway integration | DONE |
| 10.14C | Execution-level delivery receipts and lifecycle evidence | DONE |
| 10.14D | Closed-loop simulator execution | DONE |
| 10.14E | Simulator fault injection and recovery | DONE |
| 10.14F | Golden simulator execution scenarios | DONE |

Epic 10.14 remains simulator-only. Home Assistant service calls, physical
Pentair delivery, RS-485 delivery, and live equipment actuation remain outside
this epic.

### 10.14B-C - Execution delivery integration and receipts

Status: implemented pending validation. Connects one canonical execution step
to simulator-only translation and delivery, with immutable ordered receipts and
explicit lifecycle outcomes. Closed-loop verification remains in 10.14D.

### Epic 10.14D - Closed-loop simulator execution

- Separate plan lifecycle from per-step delivery and verification lifecycle.
- Mutate deterministic simulated equipment state after accepted delivery.
- Publish canonical typed simulated observations.
- Advance the coordinator only after successful verification.
- Complete the plan only after every step is verified.
- Keep fault injection and recovery deferred to Epic 10.14E.

### Epic 10.14E — Simulator Fault Injection and Recovery

Status: complete pending local validation.

- deterministic delivery rejection, failure, and timeout injection;
- missing, stale, mismatched, and timed-out verification evidence;
- immutable fault records and recovery recommendations;
- safe step and plan termination without coordinator advancement;
- no automatic retry, restart continuation, Home Assistant call, or physical actuation.

### Epic 10.14F — Golden Simulator Execution Scenarios

Status: complete.

- permanent single-step and multi-step closed-loop success scenarios;
- deterministic delivery rejection, failure, and timeout scenarios;
- missing, stale, mismatched, and timed-out verification scenarios;
- externally meaningful lifecycle, advancement, recovery, and command-count assertions;
- deterministic replay equivalence through a stable outcome fingerprint;
- reusable production scenario runner with simulator-only composition.

## PoolOS Operational Intelligence Milestones

| ID | Work item | Status |
|---|---|---|
| 10.15A | Immutable operational disposition model | DONE |
| 10.15B | Command-free operational disposition orchestrator | DONE |
| 10.15C | Canonical operational context model | DONE |

### Epic 10.15A — Operational Disposition Model

Status: complete.

- preserves the Decision Orchestrator as the single supervisory evaluation authority;
- converts accepted decision intent and minimal active-plan state into one immutable recommendation;
- supports wait, reevaluate, submit, keep, cancel, replace, and block dispositions;
- emits stable reason codes and deterministic diagnostics;
- performs no plan mutation, proposal generation, authorization, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15B — Operational Disposition Orchestrator

Status: complete.

- converts each immutable operational disposition into one canonical next-action instruction;
- maps wait, reevaluate, submit, keep, cancel, replace, and block to stable logical subsystem targets;
- preserves decision, context, and plan identity without invoking any target;
- enforces action-specific invariants and immutable diagnostics;
- performs no scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15C — Canonical Operational Context Model

Status: implemented pending local validation.

- introduces one immutable operational-state snapshot for each routing evaluation;
- isolates active-plan identity and progress in a minimal `ActivePlanSummary`;
- centralizes pending action, reevaluation, execution summary, operational mode, and safety posture;
- provides one deterministic construction authority with explicit mode precedence;
- preserves execution encapsulation and deterministic replay;
- performs no routing side effects, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.
