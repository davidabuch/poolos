# ADR-106: Authoritative Filtration Accounting and Observability

Status: accepted

## Context

ADR-101 defined temperature-based daily filtration obligations, two retained
debt days, oldest-first credit, and command-free TOU scheduling. The policy
models were not connected to a production accounting owner. Phase 3 thermal
runtime therefore supplied a constant zero filtration debt to opportunistic
Spa policy, and Home Assistant exposed no authoritative required, credited, or
remaining runtime. A similarly named diagnostic value could not establish
daily obligation truth.

## Decision

PoolOS adds one deterministic `FiltrationAccountingTracker` in the filtration
policy boundary. It consumes explicit timezone-aware authoritative observation
evidence and owns the derived two-operational-day ledger in memory. A filtration
operational day begins at 08:00 local time and is labeled by its start date;
local midnight is not a ledger boundary. Every operational day is immediately
materialized with a six-hour minimum obligation. Its requirement follows that
day's highest validated Pool temperature and may only increase. A temperature
is validated only after at least two continuous minutes
of usable Pool-routed circulation with Spa inactive and positive observed RPM.
This bounded timestamp-derived stabilization rejects retained and shared-plumbing
temperature after an inactive or Spa-routed interval without delaying filtration
credit itself. The 90 F boundary begins the 12-hour band; lower bands remain 6,
8, 9, and 10 hours. Existing credit is preserved when a target increases.

The tracker credits only confirmed Pool-routed circulation and derives the
credit factor solely from actual observed RPM: below 800 earns none, 800 to
below 1200 earns one-half, 1200 to below 1901 earns two-thirds, and 1901 or
above earns full credit. The factors use exact rational arithmetic. Outage,
probe, and requested-mode labels do not independently alter credit. Credit is
available immediately against the six-hour minimum, including during the
two-minute temperature-stabilization interval; no provisional credit bucket
exists. Debt is repaid oldest-first. The 2600-RPM ordinary-filtration baseline
remains a planning input, not accounting truth. Hydraulic stabilization may
continue across midnight or 08:00 while routing remains valid, but the daily
maximum resets at 08:00.

Once the tracker has accepted chronological evidence, advancing across an
operational-day boundary also materializes the immediately previous retained
day if it had no observations. Such a missed day receives only its six-hour
minimum: no temperature maximum, credit, runtime, or stabilization state is
fabricated. The first-ever accepted observation creates only its own day, so a
new installation does not invent pre-accounting debt. Replay reads one extra
operational-day seed window to distinguish an established timeline from first
initialization while the authoritative ledger remains bounded to two days.

The tracker uses aggregate evaluation time as its canonical chronology: live
accounting uses the authoritative snapshot `generated_at`, while replay uses
the recorder event `recorded_at`. The coordinator passes that same aggregate
snapshot time into the recorder; `recorded_at` is therefore evidence evaluation
time, not filesystem-write time. Individual observation timestamps remain
source-freshness evidence and are not substituted for the coherent aggregate
sample time.

The tracker rejects duplicate timestamps and ignores temporal regressions before
they can mutate stabilization or daily-maximum state. An unusable or stale
circulation interval breaks credit and hydraulic-stabilization continuity.
Elapsed time is calculated in UTC so DST transitions preserve real duration.
Replay retains an explicit accounted-through high-water mark. An overlapping first live sample may
establish continuity only at that mark, so previously replayed seconds cannot
be credited twice. Without overlap, the first newer live sample is a zero-credit
baseline, so the unobserved restart gap is never credited. After that one-time
handoff, ordinary duplicate and temporal-regression protection applies
unchanged.

The coordinator is the single owner of live chronological advancement. All
periodic, native-event, and mapped-entity triggers serialize current-state
sampling through the observation lock. Aggregate `generated_at` is captured
after that lock is acquired. A mapped Home Assistant event's `time_fired` is
trigger provenance, not aggregate evidence time: a queued event may execute
after a newer native refresh, while the snapshot it builds reads current state.
Presentation publication, including delayed publication of an older coordinator
result, does not reapply evidence to the filtration tracker.

Broad system health and filtration-specific evidence sufficiency are distinct.
Circulation credit requires present, individually `GOOD`, fresh Pool activity,
Spa activity, and observed pump RPM evidence. Daily target selection separately
requires usable Pool temperature evidence. Unrelated missing, unavailable, or stale
observations do not erase otherwise provable filtration work, while uncertainty
in any filtration-critical concept fails closed and breaks interval continuity.

The existing persistent observation recorder remains the durable evidence
owner. Home Assistant startup replays at most the current and prior local day
from that append-only history off the event loop and reconstructs the same
bounded stabilization and daily-maximum state, then breaks unproven restart
continuity before accepting a live snapshot. No second persistence file, Home
Assistant restore attribute, or parallel ledger is created. If the final pre-failure interval was
not durably recorded, replay may conservatively under-credit it; it never
invents completed work. Live snapshots and recorded events use the same
filtration-specific qualification function; recorded per-observation quality,
source identity, and stale-source evidence are sufficient for equivalent replay.

One bounded Control Center diagnostic exposes the current operational day and
its start and next-boundary timestamps,
required, credited, remaining, prior-day debt, total remaining, disposition,
TOU tier, rationale, next suitable time, ordinary filtration baseline, highest
validated Pool temperature, actual observed RPM, credit factor/band, and compact
stabilization state/timing. These
attributes are a view of the core tracker and are not a ledger.

Disposition describes the current relationship to the obligation. Valid Pool
circulation with remaining debt is `CREDITING`, including circulation that is
simultaneously serving Pool Solar or gas heating. `DEFERRED_HIGHER_PRIORITY`
is reserved for an operation such as Spa hydraulic mode that prevents Pool
filtration credit, while `DEFERRED_TOU` requires both outstanding debt and no
current valid Pool circulation. A completed obligation remains `SATISFIED`.

The authoritative total remaining debt now supplies ADR-101 opportunistic Spa
eligibility. Unknown accounting evidence is not treated as zero debt.

## Preserved boundaries

- Thermal source Off remains distinct from pump Off and does not erase or
  modify filtration accounting.
- The filtration runtime creates no execution proposal, delivery task, Home
  Assistant service call, or equipment command.
- ADR-103 still requires an already-active target body and satisfied hydraulic
  evidence. Opportunistic inactive-Hot-Tub activation is not designed or
  authorized by this decision.
- ADR-101's explicit Spa maintenance source boundary remains unchanged. This
  decision adds no sleeps, debounce, or guessed source hysteresis.
- Authority remains `NONE` and command delivery remains disabled.

## Consequences

Operators can audit daily filtration from normal PoolOS state, and policy can
distinguish real remaining debt from a placeholder. Replay is deterministic,
bounded, and derived from the same durable observations used elsewhere. The
two-day retention rule intentionally limits detailed debt attribution to the
current and immediately prior operational day.
