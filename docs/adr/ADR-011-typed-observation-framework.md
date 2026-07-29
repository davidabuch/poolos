# ADR-011: Typed Observation Framework

- Status: Accepted
- Milestone: 10.5B

## Context

PoolOS requires live, simulated, and derived observations to coexist without
exposing Home Assistant entity IDs to supervisory logic. Observation freshness
must remain deterministic in simulation, and equal timestamps from one source
must not silently overwrite accepted state.

The runtime environment already used `ObservationSourceKind`, but that enum was
owned by `poolos.environment` rather than by the canonical observation package.

## Decision

`poolos.observations` owns the complete canonical observation vocabulary:

- `PoolObservation`
- `ObservationSourceKind`
- `ObservationQuality`
- `ObservationFreshness`
- `FreshnessPolicy`
- `Evidence`, `TruthLevel`, and `ConfidenceBand`
- `ObservationStore` and its timestamp-ordering exceptions

`poolos.environment` imports and re-exports the exact canonical
`ObservationSourceKind` object for compatibility. No duplicate enum is defined.

Canonical observations use PoolOS-native `observation_id` values such as:

```text
actual.pool.water_temperature
simulated.pool.water_temperature
actual.environment.roof_temperature
actual.energy.grid_available
```

The historic constructor keywords `name` and `source` remain compatibility
aliases for `observation_id` and `source_id`. The historic class name remains an
exact alias:

```python
Observation = PoolObservation
```

Freshness is computed dynamically from `observed_at` with an injected PoolOS
`Clock` and `FreshnessPolicy`. Freshness is not persisted on the observation.
Quality and confidence remain independent fields.

`ObservationStore` retains the newest record per canonical observation and
source identity. For the same source:

- a newer timestamp replaces the prior record;
- an equal timestamp is rejected as ambiguous;
- an older timestamp is rejected as out of order.

Equal timestamps from different sources are allowed. Actual and simulated
observations coexist because their PoolOS-native IDs are distinct.

Untimestamped legacy observations may still be constructed, but they cannot be
accepted into `ObservationStore`.

## Consequences

- Observation provenance has one owner and one enum identity.
- Runtime policies remain backward compatible.
- Freshness is deterministic under fixed and simulation clocks.
- Silent same-source timestamp replacement is impossible.
- Home Assistant entity IDs remain confined to the future binding layer.
- Milestone 10.5C can translate bound Home Assistant states into canonical
  observations without changing the supervisory model.
