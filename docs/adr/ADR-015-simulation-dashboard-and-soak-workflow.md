# ADR-015: Simulation Dashboard and Multi-Day Soak Workflow

## Status

Accepted

## Context

PoolOS can ingest typed Home Assistant observations, publish simulated observations to protected Home Assistant entities, and derive both directions from one entity catalog. The next safety requirement is a repeatable way to compare live and simulated state and to run accelerated multi-day simulations before any control strategy reaches real equipment.

The deterministic simulation engine already owns simulated time, snapshots, events, and equipment behavior. Dashboard and soak behavior must therefore remain supervisory and must not create another execution path.

## Decision

PoolOS adds two independent supervisory components:

1. `HomeAssistantSimulationDashboard` builds catalog-driven live-versus-simulated comparison rows from `ObservationStore`. Numeric comparisons use explicit per-observation tolerances. Missing and incompatible values remain visible as first-class statuses.
2. `SimulationSoakSession` runs one validated `SoakTestPlan` through the existing `Simulation` engine and produces an immutable `SoakTestReport` containing duration, snapshots, events, availability findings, and health.

The dashboard reads observations only. The soak session drives the simulator only. Neither component sends Home Assistant service calls or commands real equipment.

## Consequences

- Live and simulated entities can be presented side by side without conflating provenance.
- Drift thresholds are explicit, deterministic, and testable.
- Multi-day tests can run quickly using accelerated simulated time.
- A soak session is single-use, making reports unambiguous and replay-friendly.
- Future Home Assistant cards and diagnostics can consume stable comparison and report models.
- Real equipment remains outside the simulation publication and soak paths.
