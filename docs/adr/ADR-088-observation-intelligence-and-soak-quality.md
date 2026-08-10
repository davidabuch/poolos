# ADR-088 — Observation Intelligence and Soak Quality

## Status

Accepted for PoolOS milestone 11.5.

## Context

Durable observation events, behavioral inference, and daily retrospectives now
provide enough canonical evidence to assess whether a local reporting day is
trustworthy for engineering learning. Raw availability failures, stale evidence,
solar transitions, and recovery are currently visible but not assembled into a
single deterministic daily quality contract.

PoolOS remains in real-world observation/shadow commissioning. Analysis must not
turn empirical Pentair behavior into a PoolOS policy or create another inference,
runtime, or control authority.

## Decision

The existing `DailyOperationalRetrospectiveEngine` becomes the canonical owner of
daily soak quality, continuous observation incidents, daily solar-learning
eligibility, and a concise engineering assessment. The durable observation event
remains the raw source of truth. `BehavioralInferenceEngine` remains the sole
owner of inferred solar transitions and now pairs activations with subsequent
deactivations into immutable solar episodes.

Observation incidents use the neutral type `UPSTREAM_OBSERVATION_FAILURE`.
Canonical `health.healthy` is authoritative because the live observation bridge
already applies context-aware freshness semantics. A healthy record may contain
diagnostic `stale_entities`; that tolerated metadata does not independently open
an incident or accrue degraded stale duration. An incident begins when durable
health evidence is unhealthy and preserves any accompanying unavailable,
missing, or stale details. It closes when a subsequent event is canonically
healthy. Consecutive affected records form one incident. Recovery evidence is kept
in provenance. An incident without recovery before the reporting-window end is
`OPEN`, has no fabricated end time, and reports elapsed duration only through the
explicit window end. Incident identity derives from its type, start boundary, and
first source event, so the same incident retains its identity when recovery is
later observed.

The quality model reports total and healthy coverage ratios, the largest
unsupported gap, supported unhealthy and unavailable/stale durations, incident
count, stable reason codes, baseline/startup evidence, and exact durable source
IDs. A durable `baseline` proves that a recorder startup window exists; it does
not by itself distinguish first installation from restart.

Each durable `baseline` starts a deterministic 60-second grace interval defined
centrally by `SoakQualityPolicy.startup_health_grace`. This mirrors the existing
live `STARTUP_HEALTH_GRACE` behavior without importing Home Assistant into the
vendor-independent report model. Initialization failures inside grace remain raw
provenance but do not open normal incidents, reduce healthy coverage, accrue
unhealthy/unavailable/stale duration, or independently degrade quality. If
supported unhealthy evidence crosses the grace boundary, suppression stops at
that boundary and a normal incident is created.

## Conservative classification policy

Coverage is calculated using the existing bounded-evidence rule: one durable
frame supports at most 15 minutes unless a newer frame arrives first. The
following initial engineering gates are centralized in `SoakQualityPolicy`, are
testable, and are deliberately not claimed as scientifically validated:

- `GOOD` requires at least 95% total and calibrated healthy coverage, no
  degrading incident reason, and no unsupported gap longer than 15 minutes.
  Informational startup provenance may be present on a `GOOD` window.
- `EXCLUDED` applies below 75% total or healthy coverage, at a gap of two hours
  or more, or at two hours or more of supported unhealthy duration.
- all other affected windows are `DEGRADED`.

Threshold changes require reviewed policy changes and corresponding tests.

## Solar evidence semantics

Solar transition evidence preserves observed roof, pool, water, and air
temperatures; roof-to-pool and roof-to-water differentials; pool target and
heating demand; pool, spa, heater, and Solar Preferred states; pump RPM, GPM,
power, power unit, and offset-aware time-of-day context when those observations
exist. Missing fields are omitted rather than imputed.

An activation is paired only with its subsequent observed deactivation. Open
episodes remain open and have no invented duration. Episode identity derives
from activation evidence and remains stable when deactivation later closes it.
Daily summaries include
transition counts, complete/open episode counts, observed solar runtime, first
and last transitions, sample arrays, and medians only when at least two samples
exist. Hysteresis is explicitly provisional empirical evidence.

`EXCLUDED` windows cannot support solar-learning conclusions. `DEGRADED` windows
remain visible and are marked as requiring review. A complete episode is required
before daily solar evidence is considered usable.

## Publication and export

The existing daily retrospective JSON representation gains additive soak-quality,
incident, solar-learning, and assessment fields. Existing fields are preserved.
The CSV export preserves existing columns and adds missing, unavailable, and stale
health evidence; JSONL continues to contain full raw observations and health.

The PoolOS Control Center adds a small set of read-only diagnostics for quality,
coverage, incident count, solar-transition count, and solar-learning quality.
Detailed evidence is exposed as attributes rather than one entity per metric.

## Safety boundary

Milestone 11.5:

- issues no Home Assistant service call;
- creates no command, execution proposal, plan, retry, or equipment action;
- performs no Pentair, HAL, RS-485, vendor, delivery, or network operation;
- adds no authority and invokes no live-control runtime;
- calls no wall clock from deterministic analysis; callers provide explicit,
  timezone-aware reporting windows; and
- publishes only evidence, diagnostics, inference, reports, exports, and
  read-only Home Assistant entities.

## Consequences

Engineers can distinguish good, degraded, and excluded days; inspect recovered
or open upstream incidents; and review solar episodes with their exact context
and provenance. Observed IntelliCenter behavior remains commissioning evidence,
not a production solar-control rule.

ADR-089 aggregates completed ADR-088 daily reports across explicit date ranges.
It does not change this ADR's per-day quality, incident, or solar authority.
