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
| 10.15D | Canonical operational action pipeline | DONE |
| 10.15E | Declarative operational action registry | DONE |
| 10.15F | Deterministic operational action exchange | SUPERSEDED |
| 10.15G | Operational action architecture consolidation | DONE |
| 10.15H | Downstream operational action adapter contract | DONE |
| 10.15I | Deterministic reevaluation scheduling boundary | DONE |
| 10.15J | Due reevaluation trigger boundary | DONE |
| 10.15K | Persistent reevaluation state and restart recovery | DONE |
| 10.15L | Reevaluation runtime submission boundary | DONE |
| 10.15M | Persistent runtime-submission identities | DONE |
| 10.15N | Runtime trigger coalescing boundary | DONE |
| 10.15O | Supervisory evaluation input assembly | DONE |

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

Status: complete.

- introduces one immutable operational-state snapshot for each routing evaluation;
- isolates active-plan identity and progress in a minimal `ActivePlanSummary`;
- centralizes pending action, reevaluation, execution summary, operational mode, and safety posture;
- provides one deterministic construction authority with explicit mode precedence;
- preserves execution encapsulation and deterministic replay;
- performs no routing side effects, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15D — Canonical Operational Action Pipeline

Status: complete.

- converts one orchestration instruction into one immutable canonical action request;
- assigns a deterministic action ID derived from stable instruction identity;
- validates canonical action-to-target routing and duplicate action identity;
- returns immutable accepted or rejected pipeline evidence with stable reason codes;
- preserves the orchestrator as the sole routing-decision authority;
- performs no target invocation, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15E — Operational Action Registry

Status: complete.

- introduces one immutable declarative registry for operational action routes;
- validates duplicate and conflicting registrations at construction time;
- returns deterministic found or unsupported lookup evidence with stable reason codes;
- makes the registry the route authority consumed by the operational action pipeline;
- keeps registrations data-only and stores no callable handlers;
- performs no dispatch, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15F — Operational Action Exchange

Status: superseded by Epic 10.15G and ADR-043.

- introduces one synchronous, deterministic exchange boundary for accepted operational actions;
- requires accepted pipeline evidence and preserved action identity;
- resolves exactly one logical destination through the canonical action registry;
- verifies consistency among canonical action, pipeline route, and registry evidence;
- emits immutable ready or rejected exchange results with deterministic IDs and diagnostics;
- performs no destination invocation, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.


### Epic 10.15G — Operational Action Architecture Consolidation

Status: complete.

- removes the redundant operational action exchange runtime layer;
- resolves each operational route exactly once through the canonical registry;
- adds canonical `boundary_name` evidence to accepted pipeline results;
- enforces that rejected pipeline results expose no target or boundary;
- preserves immutable diagnostics, duplicate suppression, deterministic replay, and simulator-only safety;
- performs no downstream invocation, scheduling, proposal generation, authorization, plan mutation, delivery, Home Assistant call, Pentair communication, or physical actuation.

### Epic 10.15H — Downstream Operational Action Adapter Contract

Status: complete.

- introduces one vendor-neutral adapter contract that consumes only validated operational action pipeline results;
- adds a deterministic non-hardware adapter for no-op, reevaluation, and operator-review routes;
- emits immutable accepted, rejected, deferred, or no-op receipts with stable identity and provenance;
- rejects unvalidated evidence and unsupported execution proposal or execution plan targets;
- invokes no scheduler, operator-review service, execution subsystem, Home Assistant integration, vendor transport, or physical equipment;
- preserves simulation-first safety and leaves reviewed execution adapters to future milestones.

### Epic 10.15I — Deterministic Reevaluation Scheduling Boundary

Status: complete.

- consumes only immutable deferred reevaluation receipts from the downstream adapter boundary;
- creates deterministic scheduling requests from explicit caller-supplied timezone-aware times;
- emits immutable scheduled, rejected, duplicate, or cancelled results with stable provenance;
- stores current scheduling records in memory without invoking the decision runtime;
- keeps supervisory reevaluation separate from execution-plan scheduling;
- performs no Home Assistant call, vendor communication, command delivery, network operation, or physical actuation.

### Epic 10.15J — Due Reevaluation Trigger Boundary

Status: complete.

- deterministically sorts and evaluates immutable reevaluation schedule records at an explicit `as_of` time;
- converts valid due records into typed `EXPECTED_CHANGE_REACHED` evaluation-trigger requests;
- emits immutable emitted, not-due, rejected, duplicate, or cancelled evidence;
- carries explicit sorted completion identities so duplicate records emit at most one trigger;
- preserves action, schedule, context, decision, correlation, hint, timing, and replay provenance;
- does not invoke the runtime, Decision Orchestrator, Home Assistant, vendor delivery, networking, or physical equipment.

### Epic 10.15K — Persistent Reevaluation State and Restart Recovery

Status: complete.

- captures immutable current scheduling records and completed trigger-request identities in one versioned snapshot;
- serializes complete identity and provenance evidence as deterministic canonical JSON;
- restores equivalent typed state in deterministic order after restart;
- rejects malformed, unsupported, duplicate, future-dated, or inconsistent persisted evidence fail-closed;
- preserves cancelled, future, and completed request behavior across restart;
- provides a vendor-neutral persistence boundary without file, database, Home Assistant, runtime, or network I/O;
- does not invoke the Decision Orchestrator, submit evaluation triggers, deliver commands, or actuate physical equipment.

### Epic 10.15L — Reevaluation Runtime Submission Boundary

Status: complete.

- wraps emitted typed reevaluation triggers with immutable schedule, action, context, decision, correlation, and provenance evidence;
- validates deterministic runtime-handoff suitability at an explicit timezone-aware submission time;
- emits immutable accepted, rejected, or duplicate results with stable reason codes and identities;
- carries explicit sorted accepted-submission identities for duplicate suppression and replay;
- consumes equivalently restored ADR-047 evidence without changing submission results;
- introduces no queue, bus, dispatcher, publisher, worker, runtime adapter, timer, clock polling, or hidden mutable state;
- does not invoke the trigger coalescer, runtime, Decision Orchestrator, Home Assistant, vendor delivery, networking, or physical equipment.

### Epic 10.15M — Persistent Runtime-Submission Identities

Status: complete.

- evolves the existing reevaluation snapshot from schema version 1 to version 2;
- persists explicit sorted ADR-048 accepted-submission identities alongside scheduling and trigger-emission completion evidence;
- includes accepted identities in deterministic canonical serialization and snapshot identity;
- restores accepted identities for restart-safe submission duplicate suppression;
- rejects version 1, missing, malformed, duplicate, noncanonical, or impossible acceptance evidence fail-closed;
- keeps trigger-emission completion and runtime-submission acceptance as distinct lifecycle evidence;
- does not connect to the trigger coalescer, runtime, Decision Orchestrator, Home Assistant, vendor delivery, networking, or physical equipment.

### Epic 10.15N — Runtime Trigger Coalescing Boundary

Status: complete.

- consumes only accepted reevaluation runtime-submission evidence;
- validates submission identity, trigger evidence, provenance, timing, and prior-consumption state;
- invokes the existing deterministic `EvaluationTriggerCoalescer` rather than creating a second queue, bus, or coalescer;
- emits one immutable coalescing batch with stable result and batch identities;
- carries explicit sorted consumed-submission identities for replay and duplicate suppression;
- rejects non-accepted, inconsistent, future-dated, duplicate, or previously consumed evidence fail-closed;
- does not construct evaluation contexts or invoke the Decision Orchestrator;
- performs no persistence I/O, scheduling, background work, networking, vendor communication, or physical actuation.

### Epic 10.15O — Supervisory Evaluation Input Assembly

Status: complete pending local validation.

- consumes successful immutable runtime-trigger coalescing evidence plus explicit current planning facts;
- reuses the existing `DecisionEvaluationContext` and `DecisionOrchestrationRequest` models;
- derives deterministic context and assembly identities from canonical evidence;
- normalizes order-insensitive goals, policies, and blockers;
- preserves coalescing, submission, context, planning, and prior-decision traceability;
- rejects missing, future-dated, inconsistent, or noncanonical evidence fail-closed;
- does not invoke the Decision Orchestrator, PoolRuntime, planning evaluation, persistence I/O, networking, vendor communication, or physical actuation.

## PoolOS Execution Delivery Milestones

| ID | Work item | Status |
|---|---|---|
| 10.16A-I | Execution preparation pipeline | DONE |
| 10.17A | Home Assistant transport adapter | DONE |
| 10.17B | Home Assistant delivery acknowledgement | DONE |
| 10.18A | Execution receipt and Flight Recorder integration | DONE |
| 10.18B | End-to-end execution validation | DONE |
| 10.19A | Home Assistant REST executor | DONE |
| 10.19B | Post-delivery observation verification | DONE |
| 10.19C | Execution reconciliation and recovery planning | DONE |

### Epic 10.19A — Home Assistant REST Executor

Status: complete pending local validation.

- adds an immutable URL, credential, and timeout configuration model with
  secret-safe representations;
- provides one synchronous callable compatible with the existing Home Assistant
  transport-adapter executor contract;
- performs one authenticated REST service request through an injectable HTTP
  sender;
- normalizes authentication, authorization, service rejection, server failure,
  timeout, connection failure, and malformed-response outcomes;
- returns transport acknowledgement evidence while preserving the distinction
  between delivery and physical-state verification;
- adds no retry, backoff, WebSocket lifecycle, background task, reconciliation,
  commissioning, or automatic live actuation.

### Epic 10.19B — Post-Delivery Observation Verification

Status: complete pending local validation.

- gates observation verification on a completed execution receipt;
- validates available execution plan and step identity provenance;
- translates explicit Home Assistant state snapshots through the existing
  canonical observation bridge;
- reuses the existing execution verification engine for value comparison,
  freshness, timeout, and deterministic evidence;
- classifies verified, pending, mismatched, unavailable, stale, timed-out, and
  rejected outcomes;
- performs no polling, event subscription, retry, reconciliation, recovery,
  background work, or physical actuation.


### Epic 10.19C — Execution Reconciliation and Recovery Planning

Status: complete pending local validation.

- consumes immutable post-delivery verification results plus explicit current
  assumptions and retry-policy facts;
- recommends satisfied, reevaluate, retry-recommended, operator-intervention,
  or abort outcomes with deterministic identity and provenance;
- treats rejected evidence as fail-closed and verified evidence as satisfied;
- requires explicit caller evidence before classifying a mismatch as persistent
  or a retry as policy-permitted;
- keeps recommendations separate from command generation, retry execution,
  coordinator advancement, and supervisory reevaluation submission;
- performs no polling, Home Assistant communication, background work, state
  mutation, command delivery, or physical actuation.
