# ADR-010: Canonical PoolObservation Type

- Status: Accepted
- Milestone: 10.5A.1

## Context

PoolOS already exposed `poolos.domain.Observation`. The typed observation
framework planned for Milestone 10.5B requires a richer operational model.
Introducing another class named `Observation` would create two competing
canonical representations and ambiguous contracts between the planner,
simulator, replay, analytics, and ingestion layers.

## Decision

PoolOS establishes `poolos.observations.PoolObservation` as its single
canonical observation type.

The existing fields and behavior move without semantic change into the
`poolos.observations` package. The symbols `TruthLevel`, `ConfidenceBand`, and
`Evidence` move with the model because they are part of its vocabulary.

`poolos.domain` re-exports those symbols and defines no competing
implementation. The historic name remains available as the exact alias:

```python
Observation = PoolObservation
```

The alias is not a subclass. Objects created through old and new imports have
identical runtime type identity. New code uses `PoolObservation`; existing code
may migrate gradually.

## Consequences

- PoolOS has one observation model and one type identity.
- Existing imports and constructor calls remain compatible.
- Milestone 10.5B can evolve the canonical model without merging parallel
  implementations.
- The compatibility alias must be removed only through a later explicit
  deprecation and migration decision.
