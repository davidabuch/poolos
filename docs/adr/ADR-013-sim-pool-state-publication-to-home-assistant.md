# ADR-013: Sim Pool State Publication to Home Assistant

- Status: Accepted
- Date: 2026-07-29
- Milestone: 10.5D

## Context

PoolOS can ingest Home Assistant state through the observation bridge, but simulation
results also need to be visible in Home Assistant for dashboards and soak testing.
Publication must never target real Pentair control entities or blur actual and simulated
state.

## Decision

PoolOS publishes canonical observations only when their provenance is
`ObservationSourceKind.SIMULATED`.

Each publication requires an explicit binding from a PoolOS observation ID to a dedicated
Home Assistant entity ID. Publication targets are restricted to `sensor` and
`binary_sensor`, and object IDs must begin with `poolos_sim_`. This namespace prevents
publication from writing to existing production control entities.

The bridge emits transport-neutral state publications. A concrete REST executor uses Home
Assistant's `/api/states/{entity_id}` endpoint. Published attributes include the canonical
observation ID, source, truth level, quality, confidence, observation timestamp, and an
explicit `poolos_simulated` marker.

The publisher is idempotent within its process: an accepted state is cached and an
identical subsequent publication is skipped. Rejected publications are not cached and may
be retried by the caller.

## Consequences

- Actual and simulated values can be displayed side by side.
- Simulation publication cannot call Home Assistant control services.
- Home Assistant entity IDs remain confined to the Home Assistant adapter.
- Publication state is best-effort and process-local; durable replay is deferred.
- Entity lifecycle and dashboard composition remain part of Milestone 10.5E.
