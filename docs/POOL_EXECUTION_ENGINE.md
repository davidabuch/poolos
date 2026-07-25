# PoolOS Execution Engine

The execution engine is the only hardware-independent path from PoolOS intent to an adapter.

## Responsibilities

- accept immutable `Command` objects
- run pluggable validators before queueing
- reject duplicate command identifiers
- order pending work by command priority and submission order
- apply latest-command-wins deduplication for the same target and action
- prevent accidental executor replacement
- dispatch through a target-specific `CommandExecutor`
- retain immutable lifecycle audit records using the shared PoolOS clock abstraction
- convert validation and adapter failures into explicit statuses

## Boundary

The engine does not call Home Assistant, Pentair, Hayward, or Jandy APIs directly. An adapter registers an executor for each logical PoolOS target and translates the normalized command at the boundary.

## Deliberate limits

This first execution engine is synchronous and in-memory. Persistence, retries, timeouts, cancellation, and asynchronous transport belong in later milestones after the adapter contract is proven.
