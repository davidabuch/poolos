# PoolRuntime Core — Milestone 9.1

`PoolRuntime` is the permanent, hardware-independent control loop for PoolOS.
It coordinates existing subsystems without absorbing their responsibilities.

## Cycle phases

1. Drain kernel events accumulated since the previous cycle.
2. Evaluate all active scheduled plans.
3. Evaluate all enabled policies.
4. Submit resulting commands to the single `ExecutionEngine` path.
5. Optionally execute queued commands and update scheduler progress.
6. Record an immutable `RuntimeCycle` audit result.

## Lifecycle

The runtime has explicit `STOPPED`, `RUNNING`, `PAUSED`, and `FAULTED` states.
Invalid lifecycle transitions raise `RuntimeLifecycleError`. Pausing preserves
active plans and queued events. Stopping preserves scheduler state so restart
recovery can be layered on later.

## Event pump

The runtime subscribes to the kernel event bus and drains a stable event batch
at the start of each cycle. Events generated during a cycle are intentionally
left for the next cycle, preventing re-entrant behavior and making each cycle
deterministic.

## Scope boundaries

Milestone 9.1 does **not** implement:

- control authority or service mode;
- hard safety constraints such as freeze or grid-loss limits;
- desired-state reconciliation and command verification;
- adaptive runtime memory.

Those capabilities are layered onto this control loop in Milestones 9.2–9.5.
The Runtime Core therefore provides the stable lifecycle and coordination
surface without prematurely mixing safety, authority, and hardware behavior.
