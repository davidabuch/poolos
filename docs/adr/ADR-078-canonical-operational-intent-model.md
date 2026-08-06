# ADR-078: Canonical Operational Intent Model

- **Status:** Accepted
- **Milestone:** 11.2A
- **Date:** 2026-08-06

## Context

PoolOS can observe a live Home Assistant system and run its deterministic shadow runtime, but it does not yet have a canonical, platform-independent way to represent why an operator or trusted subsystem wants the pool to behave differently. Existing plans and decisions describe possible actions; they do not provide a reusable declaration of operational purpose.

## Decision

Introduce one immutable `OperationalIntent` model. An intent declares desired operational purpose and preserves its type, source, priority, lifecycle, safety classification, provenance, preconditions, constraints, success criteria, failure criteria, expiry, and explanation template.

Intent identity is derived deterministically from canonical content. Lifecycle changes preserve the original identity because they describe the status of the same request rather than a new request. Canonical ordering sorts by priority, request time, and identity but does not arbitrate conflicts.

Initial intent types cover circulation, sanitation, chemistry, pool and spa heating, solar use, energy conservation, freeze protection, equipment protection, quiet hours, schedules, operator requests, maintenance, and commissioning. Intent sources distinguish operator, schedule, Home Assistant automation, weather, chemistry, equipment, safety, commissioning, and future deterministic learning evidence.

Safety-originated intents must use the highest priority and safety-critical classification. Lifecycle transitions are explicit and fail closed.

## Consequences

- Future arbitration can reason over multiple simultaneous intents without coupling intent creation to planning.
- Explanations and provenance can identify what was requested and where it came from.
- Deterministic serialization and identity support replay, audit, and duplicate detection.
- The model performs no arbitration, optimization, planning, recommendation publication, Home Assistant call, command delivery, or physical actuation.
