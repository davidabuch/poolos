# ADR-108: Command-free thermal runtime ownership

## Status

Accepted as a command-free prerequisite for future event-driven thermal
orchestration. It grants no physical authority.

## Context

ADR-103 records accepted delivery provenance inside one live thermal execution
session. That provenance answers which body activation, pump setpoint, and heat
source operations PoolOS actually delivered. It does not by itself decide
whether PoolOS remains entitled to continue a thermal lifecycle after the
originating execution session or plan changes.

Native equipment state cannot answer that question. Pool, Spa, pump, and heater
state may have been established by a person, a native schedule, or another
automation. Equality with a PoolOS plan is confirmation evidence, never proof
that PoolOS caused the state.

## Decision

PoolOS provides a core, in-memory `ThermalRuntimeOwnershipManager`. It exposes
only side-effect-free ownership decisions and has no delivery, scheduling, Home
Assistant, or transport dependency.

A runtime lease may be established only from the existing immutable
`ThermalLiveExecutionOwnership` record for the current evaluation and thermal
plan. Typed leases additionally require the originating execution purpose and
explicit accepted/verified PoolOS progress; observation equivalence cannot fill
in missing progress. Each owned concept retains its exact operation, accepted
receipt, and delivery-correlation identities. Provenance remains concept-specific:

- accepted target-body activation may own body activation;
- accepted `p0102` thermal setpoint delivery may own the pump setpoint; and
- accepted target-body heater delivery may own heat-source selection.

An operation that was merely planned, authorized, observed, or verified does
not establish ownership. A session that did not deliver a concept cannot claim
it. Incomplete or non-current provenance is denied.

Current native evidence may retain or terminally invalidate an established
lease. Concrete evaluation and plan IDs remain audit identities, while continued
semantic currentness is decided by the shared stable execution-purpose and
progress-compatible residual-plan contract. Continued ownership also requires
chronological evidence, the originating requested mode, a fresh and usable
target-body topology, fresh and usable pump evidence for an owned setpoint, and
fresh and usable heater evidence for an owned source. Pump-setpoint ownership
distinguishes the authoritative `p0102.SPEED` configuration from actual
parent-pump RPM and requires both to remain aligned within the existing
inclusive 25-RPM tolerance.

Pool and Spa simultaneously active, target-body loss, other-body takeover,
missing or degraded relevant evidence, incompatible native values, and an
unattributed relevant external change fail closed. Expected native consequence
attribution is consumed from the existing external-change boundary. It is
concept-specific: one expected PoolOS consequence cannot hide an unrelated
external thermal or hydraulic change.

Waterfall, Jets, and Slide are treated as shared-hydraulic conflicts because
the native observation model classifies each as capable of requiring the
shared circulation pump. Pool Light is non-conflicting. An active unclassified
circuit or incomplete shared-hydraulic inventory is ambiguous and fails
closed. This classification issues no circuit command and does not claim exact
valve-routing knowledge.

Ownership never transfers automatically. A compatible same-body successor
requires an explicit handoff request naming the exact predecessor lease and
generation plus the current successor evaluation, thermal plan, and execution
plan. All retained owned concepts must remain compatible. A successful handoff
creates a distinct generation and lease identity. Cross-body, stale,
incompatible, preempted, relinquished, or restart-time handoffs are denied.

Relinquishment is also command-free. It ends the lease without stopping a
body, changing RPM, changing source, restoring an earlier value, or performing
cleanup. Preempted, superseded, and relinquished leases are terminal and cannot
silently become owned again.

Before selected in-runtime relinquishment or semantic supersession, the manager
may retain a separate residual termination entitlement copied from the lease's
accepted, concept-specific provenance. The entitlement cannot continue normal
execution. It is body-, lease-, and generation-bound, exists only in memory,
and is discarded on external/hydraulic takeover, successor handoff, a new
positively proven session, explicit consumption, unload, or restart. Matching
hardware and historical receipts never recreate it.

The bounded termination policy currently admits one physical reduction only:
Pool `HEATER` Solar/Gas to Off when the source remains attributable, current
policy requires Off, and current body, pump, source, shared-hydraulic, and
external-change evidence remains usable and aligned. Pump ownership is
relinquished without restoring an old RPM. Pool circulation remains active;
body deactivation and `StopPump` remain unauthorized because the repository
cannot yet prove exclusive circulation ownership or a filtration successor
executor. A current filtration debt is represented as a command-free successor
need, never as a duplicated filtration schedule or hard-coded RPM command.

Runtime ownership is not persisted. A new process or manager begins unowned,
even if current equipment and historical receipts match a former PoolOS
thermal lifecycle. Fresh accepted execution provenance or a valid explicit
handoff from a still-live predecessor is required.

The production thermal runtime orchestrator owns one
`ThermalRuntimeOwnershipManager` and one canonical
`GridOutageConfirmationTracker` per config entry. It receives the already-built
authoritative observation frame and current thermal assessment synchronously
from the existing serialized refresh path. It retains bounded lifecycle,
currentness, candidate, outage, and ownership diagnostics only.

The orchestrator starts unowned and cannot establish ownership from observation.
Matching Pool, Spa, pump, or heat-source state therefore remains
external/pre-existing after startup or restart. The explicit default-off driver
may promote only accepted typed provenance from its current live session. The
first accepted operation establishes a lease; later accepted operations from
that exact session may add concept-specific provenance and current execution
progress. A different session, body, originating context, or incomplete
receipt/correlation is denied. The ownership manager evaluates the resulting
lease against current plan identity, external-change evidence,
body topology, configured and actual RPM, heat source, and the complete
repository-classified shared-hydraulic inventory. Non-authoritative grid state
ends continuation entitlement command-free; authoritative grid return causes
only a fresh evaluation.

Duplicate or older authoritative snapshots cannot mutate lifecycle truth. The
orchestrator publishes both concrete evaluation/plan audit identities and the
stable purpose identity. A materially different purpose supersedes ownership;
a same-purpose residual plan may retain it only when the removed prefix is
proved by PoolOS execution progress. Unload unregisters the callback and
discards in-memory ownership and outage state without cleanup or restoration.
The orchestrator itself remains command-free. Automatic delivery is owned by a
separate lifecycle adapter and defaults Off. Promotion grants no operation; it
records provenance only after scoped live delivery has returned an accepted
receipt. Probe delivery and physical outage response remain separate work.

Orchestration evidence uses the same live verification boundary as thermal
execution: source kind must be `LIVE`, confidence must be at least `0.5`, and
quality must be `GOOD` or `DEGRADED`. Freshness remains concept-specific.
Canonical grid confirmation intentionally retains its stricter grid-evidence
contract. Low-confidence, non-live, stale, missing, suspect, or invalid body,
pump, source, or shared-hydraulic evidence cannot support candidacy or retain
runtime ownership.

Snapshot identity is a bounded deterministic fingerprint of the authoritative
generation time, orchestration-relevant observation identity/value/time/source/
quality/confidence, and current body evaluation, plan, requested-mode, and
authorization identities. An exact repeated frame is idempotent; an older frame
is ignored; a materially different frame with the same generation time is a
contradiction and transitions command-free readiness to blocked.

External events can preempt an ownership lease only when their authoritative
`observed_at` belongs to that lease epoch. Events before `established_at` are
ignored for the new lease. Equality is deliberately treated as relevant because
same-timestamp ordering cannot prove that the event preceded establishment.

Home Assistant isolates orchestration processing from authoritative thermal
publication. If orchestration processing raises, a separate bounded
fail-closed callback clears candidate readiness, relinquishes any current
in-memory lease without cleanup, and records a bounded reason. Only a newer
valid authoritative frame can recover candidacy.

## Consequences

- A future orchestrator can distinguish PoolOS-caused thermal state from
  matching manual, scheduled, external, or restart-discovered state.
- Ownership, handoff, supersession, preemption, and relinquishment are explicit,
  typed, deterministic, and auditable.
- Runtime thermal ownership does not imply filtration ownership and changes no
  filtration credit rule.
- Ownership promotion adds no RPM, heat-source, or body-deactivation authority.
  It performs no service call, persistence, polling, timer, or network activity.
