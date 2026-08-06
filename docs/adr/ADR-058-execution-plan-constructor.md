# ADR-058: Execution Plan Constructor

## Status

Accepted for Epic 10.16D.

## Context

Epics 10.16B and 10.16C introduced command-free execution proposal and execution-plan request boundaries. PoolOS already contains the canonical `ExecutionPlan`, `ExecutionAuthorization`, and deterministic execution-plan builder established by the simulator execution architecture.

Creating a second plan model or bypassing authorization would duplicate established execution semantics and weaken the safety boundary. The next step must therefore connect the new request evidence to the existing canonical builder without granting authorization or invoking execution.

## Decision

Introduce `ExecutionPlanConstructor` as a deterministic composition boundary.

The constructor consumes:

- one accepted `ExecutionPlanBoundaryResult`; and
- one caller-supplied `ExecutionPlanBuildRequest` containing an existing proposal, explicit authorization, and step specifications.

It validates that the plan request and build request preserve the same proposal, decision, and context identities. It then delegates exactly once to `DeterministicExecutionPlanBuilder`.

The constructor emits immutable construction evidence containing:

- a deterministic construction ID;
- the source plan-boundary result;
- the existing build result;
- the canonical `ExecutionPlan` when construction succeeds; and
- complete provenance and stable rejection reasons.

## Safety boundaries

Epic 10.16D does not:

- create or imply authorization;
- accept an unauthorized proposal as executable;
- schedule, submit, retain, cancel, replace, or execute a plan;
- mutate coordinator or runtime state;
- translate or deliver operations;
- call Home Assistant, Pentair, vendors, transports, or networks;
- actuate physical equipment.

## Consequences

PoolOS gains a reviewed bridge from the new supervisory request path to the existing canonical execution-plan model. Existing authorization and plan invariants remain authoritative, and no duplicate plan representation is introduced.
