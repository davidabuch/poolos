# ADR-081 — Operator Recommendations

## Status
Accepted

## Context
PoolOS can now arbitrate operational intents and calculate a deterministic pump-operation recommendation, but the optimization result is an engineering artifact rather than an operator-facing explanation. Commissioning requires a stable advisory representation that can be inspected in Home Assistant without granting PoolOS control authority.

## Decision
Introduce a canonical `OperatorRecommendation` produced only from already-selected operational intents and a completed pump optimization result. The recommendation preserves intent provenance, optimization rationale, effective constraints, expected effect, deterministic identity, and an explicit advisory status.

The Home Assistant integration may publish the latest recommendation as a diagnostic sensor. If no recommendation has been produced, the sensor reports `NOT_AVAILABLE`; it must never invent a recommendation from incomplete data.

Recommendations are evidence, not commands. They carry `authority: none` and `command_delivery_enabled: false`. This milestone adds no execution proposal, service call, control entity, vendor request, or physical actuation path.

## Consequences
- Operators receive a concise explanation of what PoolOS would recommend and why.
- Infeasible optimization becomes a visible blocked recommendation rather than a fallback command.
- Recommendation identity is deterministic and tied to selected-intent provenance.
- Home Assistant remains read-only during commissioning.
