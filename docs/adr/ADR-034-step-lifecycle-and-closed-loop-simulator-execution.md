# ADR-034: Separate Step Lifecycle and Closed-Loop Simulator Execution

**Status:** Accepted  
**Milestone:** 10.14D

## Context

The execution state machine created in Epic 10.13 described the lifecycle of an
entire plan. Simulator delivery initially reused that plan lifecycle for
`DELIVERING`, `DELIVERED`, and verification states. That works for one-step
plans but conflicts with the coordinator, which must keep the plan in
`EXECUTING` while additional steps remain.

## Decision

PoolOS now maintains two explicit lifecycles:

- **Plan lifecycle:** `AUTHORIZED -> PLANNED -> EXECUTING -> COMPLETED`.
- **Step lifecycle:** `PENDING -> DELIVERING -> DELIVERED -> VERIFYING -> VERIFIED`,
  with terminal failure, timeout, and abort paths.

Simulator delivery operates only on the step lifecycle. The coordinator owns the
plan lifecycle and advances its cursor only after successful verification. The
plan reaches `COMPLETED` only after every step has been verified and acknowledged.

The closed-loop simulator engine composes existing boundaries:

1. select the current coordinator step;
2. translate and deliver through the simulator-only gateway;
3. mutate deterministic simulated equipment state;
4. publish canonical simulated observations;
5. verify expected observations;
6. acknowledge the verified step;
7. complete the plan after all steps are exhausted.

## Safety consequences

- Plan lifecycle never moves backward to execute another step.
- Delivery acceptance is not treated as verification success.
- Coordinator advancement cannot occur before verification.
- Home Assistant, physical Pentair endpoints, retries, and restart resumption
  remain outside this milestone.
