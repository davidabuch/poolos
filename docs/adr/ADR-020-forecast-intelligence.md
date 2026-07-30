# ADR-020: Canonical Forecast Intelligence

## Status

Accepted for PoolOS milestone 10.10.

## Context

Goal planning and energy optimization need future environmental facts, but direct weather-provider calls inside planning would make decisions nondeterministic, difficult to simulate, and coupled to external APIs. Raw provider fields also differ in naming, confidence scoring, and validity semantics.

## Decision

Introduce two boundaries:

1. `ForecastSnapshot` is the immutable, provider-independent environmental forecast contract. It records issuance and validity windows, optional normalized weather and solar facts, provider confidence, and copied immutable metadata.
2. `ForecastIntelligence` converts one snapshot into typed planning facts: freshness, confidence, heating penalty, solar opportunity, cooling risk, and a deterministic recommendation.

Forecast recommendations are advisory. They do not issue commands, contact Home Assistant, or bypass the goal planner, energy optimizer, policy engine, or execution path. Stale and expired forecasts explicitly recommend waiting for refreshed data rather than silently influencing a plan.

## Consequences

- Forecast providers can be added later as adapters without changing planning logic.
- Forecast scenarios are reproducible in tests and simulation.
- Planning consumes semantic facts instead of provider-specific payloads.
- Missing data remains explicit through `UNKNOWN` classifications.
- Provider ingestion, forecast fusion, thermal calibration, and automatic replanning remain separate milestones.
