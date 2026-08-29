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
evidence and owns the derived two-day ledger in memory. It creates each local
day's obligation from the first usable trusted Pool temperature, credits only
confirmed Pool-routed circulation with positive observed RPM, applies the
existing confirmed-outage credit rule, repays the oldest retained debt first,
and uses the existing LADWP profile and 2600-RPM filtration baseline.

The tracker rejects duplicate timestamps and ignores temporal regressions. An
unusable or stale interval breaks credit continuity. Elapsed time is calculated
in UTC so DST transitions preserve real duration. Restart never credits the
unobserved restart gap.

Broad system health and filtration-specific evidence sufficiency are distinct.
Circulation credit requires present, individually `GOOD`, fresh Pool activity,
Spa activity, and observed pump RPM evidence. Daily target selection separately
requires usable Pool temperature evidence. A confirmed outage affects credit
only when its own evidence is usable. Unrelated missing, unavailable, or stale
observations do not erase otherwise provable filtration work, while uncertainty
in any filtration-critical concept fails closed and breaks interval continuity.

The existing persistent observation recorder remains the durable evidence
owner. Home Assistant startup replays at most the current and prior local day
from that append-only history off the event loop, then breaks continuity before
accepting a live snapshot. No second persistence file, Home Assistant restore
attribute, or parallel ledger is created. If the final pre-failure interval was
not durably recorded, replay may conservatively under-credit it; it never
invents completed work. Live snapshots and recorded events use the same
filtration-specific qualification function; recorded per-observation quality,
source identity, and stale-source evidence are sufficient for equivalent replay.

One bounded Control Center diagnostic exposes the current obligation day,
required, credited, remaining, prior-day debt, total remaining, disposition,
TOU tier, rationale, next suitable time, and ordinary filtration baseline.
These attributes are a view of the core tracker and are not a ledger.

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
current and immediately prior local day.
