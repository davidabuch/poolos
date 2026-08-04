# ADR-053: Supervisory Evaluation Runtime Composition

## Status

Accepted for Epic 10.15Q.

## Context

Epics 10.15O and 10.15P established deterministic input assembly and invocation of the existing `DecisionOrchestrator`. PoolOS already has canonical operational-disposition and command-free operational-routing boundaries.

The remaining supervisory responsibility is composition: execute one complete reviewed evaluation cycle without adding another decision engine, runtime queue, persistence layer, retry loop, or execution path.

Operational disposition also depends on the current execution-plan summary. That evidence must be supplied explicitly so the existing disposition engine can correctly distinguish submitting, retaining, replacing, cancelling, waiting, reevaluating, or blocking.

## Decision

Introduce one `SupervisoryEvaluationRuntime` composition boundary.

The runtime request contains:

- one existing `SupervisoryEvaluationAssemblyRequest`;
- an explicit timezone-aware invocation time;
- an optional existing `OperationalPlanSummary`.

The runtime composes, exactly once and in order:

1. `SupervisoryEvaluationInputAssembler`;
2. `SupervisoryEvaluationInvoker` and the existing `DecisionOrchestrator`;
3. `OperationalDecisionSnapshot.from_orchestration`;
4. `OperationalDispositionEngine`;
5. `OperationalDispositionOrchestrator`.

The runtime result preserves:

- assembly evidence;
- invocation evidence;
- the existing `DecisionOrchestrationResult` through invocation evidence;
- the existing `OperationalEvaluationResult`;
- the existing `OperationalOrchestrationInstruction`;
- stable deterministic runtime identity and complete provenance.

Runtime identity is derived from stable assembly, invocation, context, disposition, reason, plan, action, and target evidence. Wall-clock invocation time is recorded but does not redefine logical identity.

## Boundaries

Epic 10.15Q does not:

- create another orchestrator or disposition engine;
- perform duplicate suppression or retry handling;
- poll time, schedule work, or run background tasks;
- persist or recover state;
- route or invoke operational targets;
- authorize, create, mutate, submit, cancel, replace, or execute plans;
- call Home Assistant, Pentair, vendors, transports, or networks;
- actuate physical equipment.

## Consequences

PoolOS gains one reviewed, deterministic entry point for a complete command-free supervisory evaluation cycle. The supervisory cognitive path is now composable end to end while remaining isolated from execution and hardware concerns.

The next project activity should be an architecture review before expanding downstream execution or integration behavior.
