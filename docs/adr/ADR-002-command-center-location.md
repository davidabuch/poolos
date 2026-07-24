# ADR-002: Develop the Command Center Inside the Existing Integration

- Status: Accepted
- Date: 2026-07-24

## Context

The future Pool Manager requires a Decision Engine, Ownership Manager, Execution Engine, Safety Manager, scheduling, and diagnostics. A separate Home Assistant integration could enforce a strong package boundary, but the architecture and public contracts are not yet mature.

## Decision

Develop the Command Center under the existing `intellicenter` package, initially in an `intellicenter/command_center/` subpackage.

Maintain logical separation between hardware integration and policy even though they share one package and release.

Consider a later split into a separate `pool_manager` integration only after contracts are stable and the split provides clear operational value.

## Consequences

### Positive

- Simpler development and deployment during rapid design
- Direct access to typed internal contracts without premature public APIs
- Easier coordinated testing
- Avoids version skew between two immature integrations

### Negative

- Architectural boundaries must be enforced by convention and tests
- The package will temporarily contain both hardware and policy layers
- A later split may require migration work

## Rejected alternatives

### Split immediately into a separate integration

Rejected because it would create deployment and versioning complexity before the interfaces are stable.

### Put policy directly into entity platforms

Rejected because it would mix presentation, hardware access, and operational decisions.
