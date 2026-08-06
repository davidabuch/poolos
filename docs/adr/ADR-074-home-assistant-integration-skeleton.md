# ADR-074: Home Assistant Integration Skeleton

- **Status:** Accepted
- **Milestone:** 11.1B
- **Date:** 2026-08-05

## Context

ADR-073 requires PoolOS to enter a real installation through explicit commissioning stages, beginning with observation-only authority. Before PoolOS can ingest IntelliCenter entities, it needs a minimal Home Assistant custom integration with a stable config-entry lifecycle, diagnostics, system health, translations, and options support.

Adding entity discovery, observations, decisions, or commands in the same milestone would make installation failures difficult to distinguish from runtime behavior and would violate the incremental commissioning model.

## Decision

Create an installable `custom_components/poolos` integration skeleton with one UI-created config entry. The entry loads an idle `DataUpdateCoordinator`, stores typed runtime data on `ConfigEntry.runtime_data`, exposes secret-safe diagnostics and system health information, and offers only a diagnostics option.

The initial entry records `OBSERVE` as its declared operating mode, but observation is not yet enabled. The integration explicitly reports that observation and command delivery are disabled.

The integration supports one config entry. It performs no entity discovery, polling, subscriptions, IntelliCenter communication, decision evaluation, learning, service registration, command delivery, or physical actuation.

## Consequences

- PoolOS can be installed and lifecycle-tested independently of operational behavior.
- Home Assistant setup, unload, diagnostics, translations, and system-health contracts become explicit.
- Authority-changing controls remain absent until later commissioning milestones.
- Milestone 11.1C can add read-only IntelliCenter observation without redesigning the config-entry boundary.
