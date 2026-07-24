# ADR-001: Use an Immutable API as the Internal Read Boundary

- Status: Accepted
- Date: 2026-07-24

## Context

Home Assistant entity platforms historically read Pentair `PoolObject` attributes directly. Raw objects are mutable, Pentair-specific, and easy to use inconsistently. Higher-level automation also needs stable state that does not depend on Home Assistant entity IDs or registry state.

## Decision

The integration will expose normalized immutable snapshot models through an `IntelliCenterAPI` facade.

Home Assistant entities and future Command Center components should read through this API whenever an appropriate model exists.

The immutable API will not send hardware commands or make operational decisions.

## Consequences

### Positive

- Stable typed contracts
- Reduced dependence on Pentair implementation details
- Easier unit testing
- Clear distinction between unknown, unavailable, and normal values
- A reusable state boundary for future Command Center code

### Negative

- Entity platforms require migration
- API changes require contract discipline
- Temporary duplication may exist during migration

## Rejected alternatives

### Read Home Assistant entity state

Rejected because entity state is a presentation layer and may be delayed, renamed, disabled, or unavailable.

### Continue using raw `PoolObject` instances everywhere

Rejected because it couples all consumers to mutable, Pentair-specific internals and makes safe evolution difficult.
