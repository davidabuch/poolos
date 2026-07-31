# ADR-026: Home Assistant Decision Intelligence Projection

## Status

Accepted

## Context

Milestones 10.11A through 10.11F created an immutable decision graph, deterministic
ranking, human and technical renderers, explainable planning, and append-only Flight
Recorder entries. Home Assistant needs a stable, read-only view of the latest decision
without importing Home Assistant concerns into the planner or confusing live decisions
with simulated telemetry.

## Decision

PoolOS will expose a transport-neutral Home Assistant projection with six stable entities:

- `sensor.poolos_last_decision`
- `sensor.poolos_last_decision_summary`
- `sensor.poolos_last_selected_alternative`
- `sensor.poolos_last_decision_confidence`
- `sensor.poolos_last_decision_next_change`
- `binary_sensor.poolos_last_decision_blocked`

Every entity carries traceability attributes including decision, plan, objective, sequence,
timestamps, counts, ranked alternatives, and both rendered explanations. A compact
immutable dashboard projection is generated from the same Flight Recorder entry.

Decision entities use the live `poolos_` namespace and explicitly reject `poolos_sim_`.
The projector is pure and deterministic. The publisher is idempotent and only caches
accepted state updates.

## Consequences

- Home Assistant can display and automate against current PoolOS reasoning.
- The core decision model remains independent of Home Assistant.
- Simulated telemetry and live decision intelligence remain visibly distinct.
- A REST or WebSocket adapter can implement the executor protocol without changing the
  planner or projector.
- Historical exploration remains a Flight Recorder responsibility; these entities expose
  the latest record only.
