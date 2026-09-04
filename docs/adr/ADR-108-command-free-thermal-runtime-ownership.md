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
plan. Each owned concept retains its exact operation, accepted receipt, and
delivery-correlation identities. Provenance remains concept-specific:

- accepted target-body activation may own body activation;
- accepted `p0102` thermal setpoint delivery may own the pump setpoint; and
- accepted target-body heater delivery may own heat-source selection.

An operation that was merely planned, authorized, observed, or verified does
not establish ownership. A session that did not deliver a concept cannot claim
it. Incomplete or non-current provenance is denied.

Current native evidence may retain or terminally invalidate an established
lease. Continued ownership requires chronological evidence, the originating
requested mode and plan identity, a fresh and usable target-body topology,
fresh and usable pump evidence for an owned setpoint, and fresh and usable
heater evidence for an owned source. Pump-setpoint ownership distinguishes the
authoritative `p0102.SPEED` configuration from actual parent-pump RPM and
requires both to remain aligned within the existing inclusive 25-RPM
tolerance.

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

Runtime ownership is not persisted. A new process or manager begins unowned,
even if current equipment and historical receipts match a former PoolOS
thermal lifecycle. Fresh accepted execution provenance or a valid explicit
handoff from a still-live predecessor is required.

The repository currently exposes only raw, unconfirmed grid-outage evidence;
the canonical two-second-confirmed outage signal described by ADR-005 does not
yet exist in a production decision surface. Runtime ownership therefore does
not consume outage state in this change. That confirmation boundary remains a
prerequisite for safe outage preemption.

## Consequences

- A future orchestrator can distinguish PoolOS-caused thermal state from
  matching manual, scheduled, external, or restart-discovered state.
- Ownership, handoff, supersession, preemption, and relinquishment are explicit,
  typed, deterministic, and auditable.
- Runtime thermal ownership does not imply filtration ownership and changes no
  filtration credit rule.
- This decision adds no autonomous driver, RPM authorization, heat-source
  authority, body-deactivation authority, command, service call, persistence,
  polling, timer, task, or network activity.
