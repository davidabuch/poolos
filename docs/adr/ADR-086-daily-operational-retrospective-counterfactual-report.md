# ADR-086 — Daily Operational Retrospective and Counterfactual Report

## Status

Accepted for PoolOS milestone 11.3D.

## Context

Milestones 11.3B and 11.3C provide durable observed evidence and conservative behavioral inference. PoolOS also has a canonical 11.2A-E advisory stack that can produce read-only operator recommendations with selected-intent provenance, rationale, constraints, expected effect, and confidence.

Before live Home Assistant commissioning, operators need one daily view that answers two separate questions without conflating them:

1. What did the IntelliCenter-controlled system actually do?
2. What does available PoolOS advisory evidence support saying would have been different?

The second question is counterfactual, not historical fact. The current 11.2 recommendation contract specifies pump RPM recommendations but does not specify a complete daily runtime target, start/stop schedule, or interruption-recovery duration. PoolOS must not invent those missing dimensions merely to make the comparison look complete.

## Decision

PoolOS adds a vendor-independent `DailyOperationalRetrospectiveEngine` that deterministically reconstructs daily actual metrics from 11.3B durable observation events and consumes canonical 11.2 operator-recommendation evidence when it is available for the reporting window.

The actual retrospective includes:

- pump total runtime;
- pump runtime by inferred operating mode;
- inferred priming count and duration using the 11.3C evidence model;
- spa, solar, and heater runtime;
- completed filtration interruptions;
- time-weighted average running RPM;
- pump energy in kWh when power evidence is available in W/kW;
- time-weighted pool, spa, solar/roof, and air temperature summaries;
- evidence coverage and health coverage;
- exact durable source-event identities.

Runtime integration uses the Home Assistant installation timezone to define local calendar days. The engine accepts a short pre-window evidence seed so a state already active at local midnight can be represented without fabricating a midnight transition. Long recording gaps are not extrapolated indefinitely; the default evidence horizon is bounded to 15 minutes per durable frame.

Recommendation changes are also persisted as bounded append-only advisory-state evidence with the same 35-day retention horizon. Explicit recommendation clears are recorded so a stale recommendation is not carried forward after it has been withdrawn. This allows daily counterfactual provenance to survive Home Assistant restarts.

The counterfactual report:

- preserves advisory event identity and recommendation identity, status, selected intent IDs, rationale, constraints, expected effect, and confidence;
- reports exact observed-vs-recommended RPM difference when both are available;
- reports no recommendation when 11.2 evidence is absent;
- explicitly states when duration, timing, or recovery differences cannot be supported by the current advisory contract;
- never converts advisory evidence into commands or control authority.

The Home Assistant coordinator computes retrospective reports in the executor after a successful durable-history write. It exposes a current local-day partial report and a deterministically regenerated latest completed-day report. Two diagnostic sensors publish summary evidence in the PoolOS Control Center.

## Safety Boundary

11.3D remains read-only. It does not:

- create or authorize commands;
- create execution proposals or execution plans;
- register Home Assistant control services;
- call Home Assistant equipment services;
- communicate with Pentair or any vendor transport;
- increase authority beyond `NONE`;
- enable command delivery;
- infer missing daily runtime/schedule targets as facts.

## Consequences

PoolOS can now retain and summarize what the real system did each day while keeping counterfactual advisory claims evidence-bounded. Future milestones may enrich the 11.2 advisory contract with explicit duration or scheduling targets; when that occurs, the same retrospective model can add exact duration/timing differences without changing its fact-versus-counterfactual boundary.

ADR-088 extends this same canonical report with additive soak-quality, incident, solar-learning, and daily-assessment evidence while preserving existing actual and counterfactual fields.
