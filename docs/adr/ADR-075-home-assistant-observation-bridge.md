# ADR-075: Home Assistant Observation Bridge Commissioning

- **Status:** Accepted
- **Milestone:** 11.1C
- **Date:** 2026-08-05

## Context

PoolOS has an installable Home Assistant integration skeleton and an existing vendor-neutral observation model. The first operational commissioning capability must connect PoolOS to the real Home Assistant state machine without assuming Pentair-specific entity IDs, changing Home Assistant state, or increasing authority beyond `OBSERVE`.

The repository already contains canonical `PoolObservation`, `HomeAssistantState`, binding, mapping, freshness, quality, and provenance models. The Home Assistant custom integration should compose those models rather than create a second observation architecture.

## Decision

Add a configurable, read-only observation bridge to `custom_components/poolos`.

The config and options flows map existing Home Assistant entities to canonical concepts for pool activity, spa activity, pump RPM, pool temperature, spa temperature, heater activity, solar activity, and pump power. The five core mappings are required; heater, solar, and pump-power mappings are optional.

The coordinator reads only from `hass.states`, translates snapshots through the existing canonical Home Assistant observation mapper, evaluates availability and freshness, and exposes an immutable observation snapshot. Diagnostics report mapping and health evidence but omit observed state values.

The bridge operates only in `OBSERVE`. It registers no entity platforms, services, event listeners, commands, decisions, learning behavior, or actuation path.

## Consequences

- PoolOS can observe the user's existing IntelliCenter-backed Home Assistant entities without hardcoded IDs.
- The mapping remains vendor-neutral and can later support other pool controllers.
- Missing, unavailable, invalid, and stale evidence becomes explicit commissioning data.
- Options changes reload the entry and rebuild the observation mapping.
- A normal coordinator refresh provides bounded state sampling without external network I/O.
- Home Assistant remains the immediate source of live entity state; PoolOS does not bypass the installed controller integration.
- No Home Assistant service call or physical equipment command is possible in this milestone.
