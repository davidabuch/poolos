# Data Flow

## Purpose

This chapter follows information through PoolOS from external reality to verified outcome. It explains the meaning of each transformation and where authority changes.

## End-to-end flow

```text
External observations and operator intent
                    |
                    v
          Canonical observations
                    |
                    v
       Decision evaluation context
                    |
                    v
       Planning and alternatives
                    |
                    v
         Orchestrated decision
                    |
                    v
       Operational disposition
                    |
                    v
       Command-free routing intent
                    |
                    v
   Authorized deterministic execution plan
                    |
                    v
      Adapter delivery and receipt
                    |
                    v
       Verification observations
                    |
                    v
      Completion, failure, or recovery
                    |
                    v
             Flight records
```

## 1. External facts become canonical observations

External systems provide entity states, controller telemetry, forecasts, configuration, and operator requests. Adapters normalize those values into vendor-independent observations.

The transformation must preserve:

- source;
- observation time;
- receipt time where relevant;
- freshness;
- quality;
- canonical subject identity;
- original provenance needed for diagnosis.

No decision is made at this stage.

## 2. Observations become evaluation context

A decision cycle assembles the facts needed for one evaluation:

- current observations;
- forecast evidence;
- goals and objectives;
- active policies;
- blockers;
- runtime mode;
- prior-decision evidence;
- explicit evaluation time;
- trigger provenance.

The context is an immutable snapshot. Later external changes do not retroactively alter it.

## 3. Planning produces alternatives

Planning converts goals and current facts into candidate plans or alternatives. Alternatives describe possible outcomes and trade-offs without yet authorizing equipment work.

Typical evidence includes:

- objective identity;
- candidate plan identity;
- expected benefits and costs;
- policy or constraint results;
- feasibility and blockers.

## 4. Decision orchestration selects an outcome

The decision system evaluates the current context and alternatives. It may:

- complete a new decision;
- retain a stable prior decision;
- block because required context is incomplete.

The result includes technical and human explanation evidence and remains command-free.

## 5. Operational disposition interprets the decision

A decision is compared with the current execution-plan summary. The operational disposition states what should happen next at the plan-management level:

- wait;
- schedule reevaluation;
- submit a plan;
- retain a plan;
- replace a plan;
- cancel a plan;
- block or request review.

This stage does not invoke the next action.

## 6. Routing identifies the downstream boundary

Command-free routing evidence identifies the logical destination for the disposition. It preserves traceability while keeping supervisory composition free of queues, background workers, and execution side effects.

## 7. Execution converts accepted intent into work

The execution system performs several distinct transformations:

```text
Accepted intent
    -> execution proposal
    -> authorization
    -> deterministic plan
    -> lifecycle transitions
    -> step delivery requests
```

Authority and runtime-mode checks occur before delivery. A valid decision is necessary but not sufficient for actuation.

## 8. Adapters deliver canonical steps

A delivery adapter translates an approved canonical step into a platform-specific operation. Examples may eventually include Home Assistant services or Pentair-specific commands.

The adapter returns a receipt containing enough evidence to distinguish:

- accepted delivery;
- rejected delivery;
- timeout;
- transport failure;
- unsupported capability;
- duplicate or already-satisfied operation.

The adapter does not decide whether the original goal was correct.

## 9. Verification closes the loop

Observed state after delivery is compared with the expected result. Verification may confirm success, identify drift, or produce recovery evidence.

Delivery success and physical success are different facts. A service call can be accepted while equipment fails to reach the expected state.

## 10. Recording preserves the chain

Decision and execution flight records preserve the important transformations and identities. Recording is observational: it must not silently alter the outcome it records.

## Time in the data flow

PoolOS uses explicit timezone-aware times. Different stages may have different timestamps:

- observed at;
- received at;
- evaluated at;
- assembled at;
- invoked at;
- authorized at;
- delivered at;
- verified at.

Logical identity should include time only where time is part of the represented fact. Operational audit timestamps may be recorded without redefining replay identity.

## Stale and unavailable data

Connectivity loss does not erase the last known fact, but it changes its quality and freshness. Higher layers must not treat stale evidence as current merely because a cached value exists.

The correct flow is:

```text
Source unavailable
    -> observation marked stale or unavailable
    -> evaluation context preserves that status
    -> policy may block, defer, or degrade
    -> execution remains fail-closed when current truth is required
```

## Failure flow

Failures remain attributable to the boundary that produced them:

- malformed observation -> observation failure;
- incomplete context -> blocked decision context;
- rejected authority -> execution authorization failure;
- transport outage -> adapter delivery failure;
- unexpected physical state -> verification or reconciliation failure.

A lower-layer failure must not be rewritten as a different higher-layer decision.

## Responsibilities

This chapter defines the canonical movement and transformation of information through PoolOS.

## Non-responsibilities

It does not specify transport protocols, retry timing, or vendor commissioning procedures.

## Future evolution

Later chapters will describe safety, subsystem internals, and integration-specific degraded operation in greater detail.
