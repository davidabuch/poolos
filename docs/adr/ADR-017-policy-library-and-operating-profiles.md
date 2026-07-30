# ADR-017: Policy Library and Operating Profiles

## Status

Accepted — Milestone 10.7.

## Context

PoolOS already had a deterministic `PolicyEngine` that evaluates policies and resolves commands targeting the same equipment. It did not provide a higher-level mechanism for selecting a coherent operating strategy such as normal, vacation, outage, maintenance, or user-request operation.

## Decision

PoolOS adds a hardware-independent `PolicyLibrary` containing named `OperatingProfile` objects. Each profile contains:

- a stable identifier;
- a profile-selection priority;
- an immutable bundle of policies;
- a read-only activation rule;
- optional descriptive metadata.

Every evaluation records an activation decision and reason for every registered profile. The highest-priority active profile is selected, with registration order as the deterministic tie-breaker. Its policies are then evaluated through a fresh existing `PolicyEngine`.

The library never executes commands. It only selects a profile and returns the normal immutable policy evaluation.

## Consequences

- Operating strategies are reusable and independently testable.
- Profile selection is deterministic and auditable.
- Safety or emergency profiles can preempt normal optimization profiles.
- Existing command conflict resolution remains centralized in `PolicyEngine`.
- Home Assistant, Pentair, and physical command delivery remain outside this layer.
