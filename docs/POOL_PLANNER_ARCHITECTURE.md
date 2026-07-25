# PoolOS Planner Architecture

## 1. Purpose

The Planner converts user goals and operating objectives into an ordered, time-aware plan of proposed PoolOS commands.

The Planner answers:

> What should happen, in what order, and over what time horizon to achieve the requested outcome?

The Planner does not execute commands, write to hardware, or bypass policy evaluation.

## 2. Architectural Position

```text
User intent / operating objective
              |
              v
           Planner
              |
              v
       Proposed Plan Steps
              |
              v
         Policy Engine
              |
              v
     Approved PoolOS Commands
              |
              v
       Execution Engine
              |
              v
        Hardware Adapter
```

The Scheduler wakes the Planner and makes plan steps eligible at the correct time. It does not decide pool behavior.

## 3. Core Decisions

The following decisions are authoritative for the first Planner implementation:

1. Plans may span minutes, hours, or multiple days.
2. The Planner is hardware-independent.
3. The Planner may only produce immutable plan data and proposed commands.
4. The Policy Engine remains the safety and conflict-resolution boundary.
5. The Execution Engine remains the only command path.
6. Plans are restart-safe and reconstructable from persisted plan state plus current kernel facts.
7. Replanning is expected whenever assumptions change.
8. A plan describes intent and sequencing, not direct device procedures.

## 4. Responsibilities

The Planner is responsible for:

- Accepting a typed objective
- Reading normalized state from the PoolOS Kernel
- Selecting a planning strategy
- Producing an immutable plan
- Sequencing dependent operations
- Defining timing windows and deadlines
- Declaring assumptions and constraints
- Estimating completion when possible
- Replanning when material facts change
- Explaining why each step exists

The Planner is not responsible for:

- Sending commands
- Talking to Home Assistant
- Talking to Pentair or any other vendor
- Enforcing final safety rules
- Retrying failed hardware commands
- Owning the real-time execution queue
- Defining wall-clock wake-up mechanics

## 5. Planning Inputs

A planning request should contain:

- Objective type
- Target body or equipment scope
- Requested outcome
- Earliest start time
- Desired completion time or deadline
- Optional maintenance duration
- User priority
- Optional cost or energy preference
- Optional cancellation conditions
- Request source and correlation metadata

Examples:

- Prepare the spa to 100°F by 7:00 PM
- Maintain the pool at 88°F from noon through 5:00 PM
- Complete filtration before sunrise
- Suspend normal operation during vacation mode
- Prepare for a chemical treatment over two days

## 6. Planning Model

### 6.1 PlanObjective

A `PlanObjective` is the normalized user or system intent.

Required characteristics:

- Immutable
- Uniquely identified
- Timezone-aware
- Serializable
- Independent of vendor entity IDs
- Explicit about requested outcome and deadline

### 6.2 Plan

A `Plan` is an immutable snapshot of the Planner's current solution.

A plan should contain:

- `plan_id`
- `objective_id`
- `created_at`
- `planning_horizon_start`
- `planning_horizon_end`
- `status`
- Ordered `steps`
- Assumptions
- Constraints
- Estimated completion
- Revision number
- Superseded plan ID when replanned
- Human-readable rationale

Plans are versioned rather than edited in place. Replanning creates a new revision.

### 6.3 PlanStep

A `PlanStep` represents one eligible unit of intended work.

A step should contain:

- `step_id`
- Sequence position
- Earliest eligible time
- Latest eligible time or deadline
- Optional dependency step IDs
- Proposed immutable commands
- Preconditions
- Completion conditions
- Cancellation conditions
- Failure behavior
- Rationale

A plan step never executes itself.

### 6.4 Preconditions and Completion Conditions

Conditions must be expressed against normalized PoolOS state.

Examples:

- Spa temperature is below target minus deadband
- Circulation capability is available
- Grid power is present
- Prior step completed
- Heating is no longer required
- Requested maintenance window has ended

Conditions should be typed and serializable. Arbitrary lambdas or non-serializable callables must not be embedded in persisted plans.

## 7. Plan Lifecycle

Recommended plan states:

```text
DRAFT
ACTIVE
PAUSED
COMPLETED
CANCELLED
FAILED
SUPERSEDED
```

Lifecycle behavior:

1. Planner creates a `DRAFT` plan.
2. Validation promotes it to `ACTIVE`.
3. Scheduler identifies eligible steps.
4. Policy Engine evaluates proposed commands.
5. Execution Engine dispatches approved commands.
6. Runtime results update plan progress.
7. Changed assumptions may trigger replanning.
8. A replacement revision marks the prior plan `SUPERSEDED`.

## 8. Replanning

Replanning is a normal operation, not an exceptional failure.

Material replanning triggers may include:

- Temperature changes faster or slower than expected
- Equipment becomes unavailable
- Grid outage or restoration
- User changes the objective
- Deadline changes
- Safety policy suppresses a required command
- A command fails repeatedly
- Solar or other preferred energy source becomes unavailable
- A higher-priority plan takes control of shared equipment

Replanning must preserve auditability. The system should retain the previous plan revision and the reason it was replaced.

## 9. Scheduler Boundary

The Scheduler answers:

> Which plan steps are eligible to be evaluated now?

The Scheduler may:

- Wake the Planner periodically
- Activate steps when their time window opens
- Request reevaluation when a deadline approaches
- Resume persisted plans after restart

The Scheduler must not:

- Invent commands
- Override policy decisions
- Send commands
- Contain pool-specific operating logic

## 10. Policy Engine Boundary

The Planner proposes. The Policy Engine decides whether proposed commands are currently allowable.

Examples:

- Planner proposes starting the heater
- Policy Engine adds required circulation
- Policy Engine suppresses heating during an outage
- Policy Engine resolves conflicts with freeze protection

The Planner must treat policy suppression as new information and may replan when the objective can still be achieved another way.

## 11. Execution Engine Boundary

Only the Execution Engine may dispatch approved commands.

The Planner must not:

- Access executors
- Access adapter methods
- Retry commands directly
- Modify the execution queue
- Assume a command succeeded merely because it was proposed

Execution results should be reported back through normalized events or result records.

## 12. Persistence and Restart Safety

Multi-hour and multi-day plans require persistence.

Persisted planner data should include:

- Objective
- Current plan revision
- Step states
- Relevant timestamps
- Completion evidence
- Last replan reason
- Correlation identifiers

On restart:

1. Load active objectives and plans.
2. Read current kernel state.
3. Reconcile completed and obsolete steps.
4. Replan when prior assumptions are no longer valid.
5. Do not replay commands solely because they appeared in a pre-restart plan.

## 13. Determinism and Time

The Planner must use the PoolOS clock abstraction rather than calling system time directly.

Given the same:

- Objective
- Kernel state
- Configuration
- Clock value

The Planner should produce the same plan.

This requirement supports reliable unit testing and simulation.

## 14. Initial Planning Strategies

The first implementation should provide a generic framework plus one useful end-to-end strategy.

Recommended first strategy:

### Prepare Body by Deadline

Example objective:

> Prepare the spa to 100°F by 7:00 PM and maintain it until 9:00 PM.

The strategy should:

- Determine whether the target is already satisfied
- Estimate when heating should begin
- Propose circulation before heating
- Propose target temperature control
- Define readiness and maintenance conditions
- Stop maintenance at the requested end time
- Replan when heating progress differs materially from expectation

This strategy provides a realistic proving ground without embedding Pentair-specific details.

## 15. Deferred Features

The following should not be included in the first Planner implementation:

- Weather forecasting integrations
- Utility-rate optimization
- Machine-learning temperature prediction
- Chemical dosing recommendations
- Cross-property or multi-installation optimization
- Direct Home Assistant services
- Vendor-specific pump programs
- Automatic natural-language interpretation

The architecture should allow these later without requiring a rewrite.

## 16. Proposed Package Layout

```text
poolos/
    planner/
        __init__.py
        enums.py
        models.py
        conditions.py
        engine.py
        strategies.py
        persistence.py

tests/
    test_poolos_planner_models.py
    test_poolos_planner_engine.py
    test_poolos_planner_replanning.py
    test_poolos_prepare_body_strategy.py
```

The exact file split may be adjusted during implementation, but the public responsibilities should remain stable.

## 17. Acceptance Criteria for the Planner Milestone

The first Planner milestone is complete when:

- Objectives, plans, and steps are immutable and serializable
- Plans support multi-day horizons
- Dependencies and eligibility windows are enforced
- Plans are versioned during replanning
- Planner uses the PoolOS clock abstraction
- Planner never executes commands
- Policy evaluation remains outside the Planner
- Restart reconciliation is covered by tests
- At least one end-to-end planning strategy is implemented
- Full repository tests pass in GitHub Actions

## 18. Recommended Implementation Order

1. Planner enums and immutable models
2. Serializable conditions
3. Planner engine and strategy protocol
4. Plan lifecycle and revision handling
5. Persistence interface
6. Restart reconciliation
7. Prepare-body-by-deadline strategy
8. Scheduler integration in a later milestone
