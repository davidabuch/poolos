# ADR-012: Hybrid Home Assistant Observation Bridge

## Status

Accepted — Milestone 10.5C

## Context

PoolOS must consume selected Home Assistant entity states without making Home
Assistant entity IDs part of the PoolOS domain model. The runtime must also be
able to retain live and simulated observations concurrently during simulation
and shadow operation.

## Decision

The `poolos.homeassistant` package owns a one-way observation adapter composed
of transport-neutral HA state snapshots, explicit entity bindings, a mapper,
and an ingestion bridge.

Each binding maps one Home Assistant entity (or one attribute on that entity)
to a PoolOS-native observation ID and declares the value conversion, unit,
provenance, truth level, and confidence. The mapper uses Home Assistant's
`last_updated` timestamp as `observed_at` and never invents a timestamp.

`unknown`, `unavailable`, missing attributes, and failed conversions produce an
`INVALID` observation with zero confidence rather than being discarded or
coerced into a plausible value. Unrelated HA entities are ignored.

The bridge writes canonical `PoolObservation` instances into
`ObservationStore`. Source identity includes the HA entity only inside the HA
adapter. Store keys allow live and simulated observations for the same
canonical observation ID to coexist.

The bridge accepts already-received HA state payloads. Network polling,
subscriptions, reconnection, and authentication remain transport concerns and
are intentionally deferred.

## Consequences

- HA entity IDs do not leak into planners, policies, or the canonical domain.
- Conversion and unavailable-state behavior are explicit and testable.
- Live and simulated evidence can coexist during shadow operation.
- A later REST or WebSocket subscriber can feed this bridge without changing
  observation semantics.
