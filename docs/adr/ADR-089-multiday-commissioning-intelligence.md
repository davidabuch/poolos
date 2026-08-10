# ADR-089 — Multi-Day Commissioning Intelligence

## Status

Accepted for PoolOS milestone 11.6.

## Context

ADR-088 defines canonical per-day soak quality, neutral observation incidents,
solar episodes, and daily solar-learning evidence. Several completed days can now
be compared to decide whether the empirical commissioning evidence is mature
enough for a human engineering review.

Cross-day aggregation must not reinterpret daily quality, repeat solar transition
inference, reread raw observations in the core layer, or turn observed Pentair
behavior into an automatic control rule.

## Decision

PoolOS adds one vendor-neutral `MultiDayCommissioningIntelligence` boundary. It
consumes only completed immutable `DailyOperationalRetrospective` objects plus an
explicit inclusive `start_date` and `end_date`. It performs no wall-clock read.

The daily retrospective remains authoritative for per-day quality, incidents,
and learning eligibility. The behavioral inference engine remains authoritative
for solar transitions and episodes. The multi-day boundary only aggregates that
existing evidence:

- all daily report IDs remain provenance;
- only `GOOD` reports are included in the clean evidence base;
- `DEGRADED` and `EXCLUDED` reports remain counted and identified but contribute
  no clean solar samples;
- only `GOOD` reports whose canonical daily solar summary is usable contribute
  solar samples, episode counts, and cross-day descriptive statistics;
- incident burden is reported across every daily report using neutral incident
  semantics and calibrated supported unhealthy duration; and
- deterministic identity is derived from the explicit range, criteria, canonical
  source-report identities, status reasons, solar contributions, and incidents.

The Home Assistant coordinator rebuilds a bounded sequence of at most 14
completed local calendar-day retrospectives in its existing executor workflow.
It then supplies those typed reports to the core boundary. Current partial days
never enter the multi-day report. The core aggregator does not access observation
files, Home Assistant, or the system clock.

## Commissioning evidence status

`CommissioningEvidencePolicy` centralizes conservative initial defaults. They are
engineering review gates, not scientific truth:

- at least 5 `GOOD` days;
- at least 3 consecutive `GOOD` days ending at the most recent report;
- at least 3 `GOOD` days with usable solar-learning evidence;
- at least 5 complete solar episodes from those clean contributing days;
- no observation incident in the most recent 2 reporting dates;
- no open observation incident;
- no missing completed daily report inside the explicit range; and
- `DEGRADED` plus `EXCLUDED` days must not outnumber `GOOD` days.

If only evidence-volume gates are unmet, status is `ACCUMULATING`. Missing daily
reports, a recent/open incident, or quality concerns dominating the period yields
`REVIEW_REQUIRED`. Satisfying every gate yields
`SUFFICIENT_FOR_POLICY_REVIEW`.

That final status means only that a human may begin reviewing the empirical
evidence. It does not select a threshold, create or change policy, increase
authority, or authorize execution.

## Cross-day solar semantics

Contributing sample tuples remain grouped by report date and report identity.
Activation differentials, deactivation differentials, and activation roof
temperatures are also aggregated into deterministic sample sequences. Median,
minimum, maximum, and range require at least two samples. Cross-day hysteresis is
the difference between supported empirical activation and deactivation medians
and remains explicitly provisional.

Observed Pentair behavior is evidence of what occurred, not proof that the
behavior is optimal or suitable as a PoolOS controller policy.

## Safety boundary

Milestone 11.6:

- creates no policy, threshold, command, proposal, plan, retry, or action;
- performs no Home Assistant service call;
- performs no Pentair, HAL, RS-485, vendor, delivery, network, or physical
  equipment operation;
- makes no authority change and keeps command delivery disabled; and
- publishes only immutable reports and read-only diagnostic entities.

## Consequences

Commissioning evidence can progress deterministically from accumulation to human
review readiness while preserving daily authority boundaries and exact
provenance. Operational policy design remains a separate explicitly reviewed
future milestone.
