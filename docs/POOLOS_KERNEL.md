# PoolOS Kernel

Milestone 2 establishes the hardware-independent runtime foundation for PoolOS.

The `PoolKernel` is the composition root and owns:

- the canonical equipment registry;
- the body registry for one installation;
- normalized runtime state;
- a synchronous internal event bus;
- an injectable clock for deterministic tests and simulations; and
- installation-level configuration.

Adapters may translate Pentair, Home Assistant, simulated, or future hardware
state into these models. Policies, planners, advisors, and execution components
must consume the kernel models rather than hardware-specific entities.

State updates validate registry membership before being accepted. Meaningful
changes publish immutable events. Identical repeated observations do not emit
additional events unless `emit_unchanged_state_events` is enabled.

The event bus is intentionally synchronous in this milestone. It provides a
small deterministic contract and can later be wrapped by an asynchronous host
without changing the PoolOS domain model.
