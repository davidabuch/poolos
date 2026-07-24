# ADR-004: Use Explicit Priority-Based Equipment Ownership

- Status: Accepted
- Date: 2026-07-24

## Context

Normal scheduling, user actions, and safety conditions can request incompatible states. The system needs a deterministic rule for deciding which request controls each equipment function.

## Decision

Use explicit equipment ownership with the initial priority order:

```text
SAFETY
  > MANUAL
  > POOL_MANAGER
  > NONE
```

Ownership is evaluated from current facts and must be inspectable. A temporary owner releases control when its condition or request ends. Releasing ownership triggers reevaluation rather than restoration of stale state.

Ownership may be tracked per equipment function rather than as one global value when needed.

## Consequences

### Positive

- Deterministic conflict resolution
- Safety always wins
- Manual intent can be represented explicitly
- Easier diagnostics
- Supports future partial ownership by equipment function

### Negative

- Manual-request lifetime must be defined carefully
- Ownership state adds modeling complexity
- Global and per-equipment ownership interactions require tests

## Rejected alternatives

### Last command wins

Rejected because timing would determine behavior and safety could be overwritten.

### Snapshot and restore

Rejected because restored state may no longer match schedules, current conditions, or current user intent.
