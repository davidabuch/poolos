# ADR-002: Develop the Command Center Inside the Existing Integration

- Status: Superseded by ADR-031
- Date: 2026-07-24
- Superseded: 2026-07-31

## Context

The future Pool Manager required a Decision Engine, Ownership Manager, Execution Engine, Safety
Manager, scheduling, and diagnostics. At the time, a separate package boundary appeared premature.

## Original Decision

Develop the Command Center under the existing `intellicenter` package, initially in an
`intellicenter/command_center/` subpackage.

Maintain logical separation between hardware integration and policy even though they share one
package and release.

## Supersession

Subsequent development established `poolos/` as the canonical vendor-independent package for
policy, planning, decisions, runtime behavior, explanations, recovery, diagnostics, and future
command delivery.

The root `intellicenter/` directory now remains the Home Assistant hardware integration, while
`intellicenter/api/` remains its internal immutable read-model package.

ADR-031 records the replacement repository boundary. This ADR is retained as architectural
history and must not guide new code placement.

## Original Consequences

### Positive

- Simpler early development and deployment
- Direct access to immature internal contracts
- Avoided premature versioning boundaries

### Negative

- Hardware and policy responsibilities would have shared one package
- Boundaries would have depended heavily on convention
- A later split would require migration

## Rejected Alternative at the Time

An immediate separate integration was rejected because it would have introduced deployment and
versioning complexity before interfaces were stable.
