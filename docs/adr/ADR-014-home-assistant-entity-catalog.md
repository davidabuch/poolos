# ADR-014: Canonical Home Assistant Entity Catalog

- Status: Accepted
- Date: 2026-07-29
- Milestone: 10.5E

## Context

The Home Assistant observation bridge and simulation publication bridge each use explicit,
typed bindings. Without a shared registry, the same canonical observation, unit, value type,
and entity metadata can drift across independently constructed profiles. Duplicate or
conflicting Home Assistant entity IDs would also be detected only within one direction.

## Decision

PoolOS defines a transport-neutral `HomeAssistantEntityCatalog` containing immutable
`HomeAssistantEntityDefinition` records. Each definition identifies one canonical PoolOS
observation and may declare an inbound Home Assistant entity, an outbound simulated entity,
or both.

The catalog validates uniqueness across canonical observation IDs and every Home Assistant
entity ID. It validates that inbound entity domains match their declared entity class and
that outbound entity IDs retain the protected `sensor.poolos_sim_*` or
`binary_sensor.poolos_sim_*` namespace established by ADR-013.

The catalog generates the existing observation and publication profiles. Both bridges expose
`from_catalog` constructors so callers can use one registry without coupling bridge internals
to catalog storage or configuration formats.

## Consequences

- Observation and publication mappings have one reviewable source of truth.
- Duplicate and conflicting entity IDs are rejected across both directions.
- Existing profile and binding APIs remain supported for focused tests and small adapters.
- Catalog metadata is immutable and available for future documentation and dashboard
  generation.
- Configuration-file loading and dashboard composition remain separate milestones.
