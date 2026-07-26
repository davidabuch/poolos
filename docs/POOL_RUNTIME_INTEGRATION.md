# PoolOS Runtime Integration

Milestone 9.6 closes the PoolOS control loop without merging subsystem
responsibilities.

## Deterministic cycle

Each cycle performs the same ordered phases:

1. Capture the cycle-start context and drain prior events.
2. Reconcile previously executed commands against observed state.
3. Evaluate active scheduled plans.
4. Evaluate policies.
5. Resolve command authority.
6. Apply constraints.
7. Submit approved commands to the execution engine.
8. Execute queued commands when enabled.
9. Track successful and failed executions for reconciliation.
10. Record operational memory and publish a cycle summary.

Authority decides whose request is eligible. Constraints decide whether the
eligible request is safe. Only the execution engine invokes adapters.

## Runtime context

`RuntimeContext` is an immutable snapshot of cycle number, time, runtime
status, active plans, pending work, captured events, and diagnostic metadata.
It is intended for diagnostics and future subsystem extension points, not for
hardware control.

## Event contract

`RuntimeEventPublisher` standardizes integration-level topics while retaining
the kernel `EventBus` as the single event transport.

## Explainability

`PoolRuntime.explain()` returns a structured `RuntimeExplanation` describing
the latest cycle, including authority blocks, constraint modifications,
execution outcomes, reconciliation state, and learned cycle timing.

The explanation is observational only and cannot execute commands.
