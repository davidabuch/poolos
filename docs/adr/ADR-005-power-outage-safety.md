# ADR-005: Model Power Outage Handling as a Safety Mode

- Status: Accepted
- Date: 2026-07-24

## Context

The pool equipment panel is backed by one Powerwall system. During an outage, optional high-load features should stop and required circulation should use reduced power. Independent Home Assistant automations would create multiple sources of truth and could restore stale state after utility power returns.

## Decision

Implement power outage handling as a highest-priority safety mode managed by the Command Center.

Use only:

```text
binary_sensor.1_powerwall_grid_status
```

Confirm an actual outage only after the sensor is continuously off for exactly
two seconds. The configured sensor is a persistent, event-driven Home Assistant
state source; PoolOS may establish elapsed continuity on a later evaluation of
the same fresh current state without scheduling a two-second timer.

Do not use:

```text
binary_sensor.3_powerwalls_grid_status
```

While active:

- Spa off
- Waterfall off
- Jets off
- Slide off
- Pool light off
- Normal Decision Engine determines whether circulation is required
- If circulation is required, use the configured reduced-power baseline
  (currently 1500 RPM)
- If circulation is not required, do not create circulation; externally owned
  circulation is left unchanged unless another provenance-safe contract can
  independently relinquish it

Observe actual pump speed from:

```text
sensor.buch_family_vs_rpm
```

Do not alter Pentair RPM preset configuration values.

This ADR records the intended safety behavior, not current runtime authority.
The HA observation adapter maps the configured grid-status entity to the raw
`grid.outage_active` observation. The core `GridOutageConfirmationTracker` is
the single canonical command-free boundary between that raw observation and a
confirmed actual outage. It distinguishes authoritative `ON_GRID`,
`OFF_GRID_PENDING`, `CONFIRMED_OUTAGE`, and `UNKNOWN` dispositions. Missing,
stale, future, contradictory, or otherwise unusable evidence cannot confirm a
pending outage and cannot manufacture proof that a confirmed outage ended.
Only usable positive on-grid evidence ends a confirmed outage epoch.

The tracker is in-memory and deliberately does not reconstruct confirmation
from an old matching state after restart. A first off-grid evaluation after
restart begins a new two-second evidentiary epoch. It uses no sleep, polling,
timer, persistence, replay, or command path. The logical threshold time and the
later time at which PoolOS evaluates and knows confirmation are retained as
separate timestamps.

Expected-outage acknowledgments remain retrospective operator annotations.
They cannot establish or accelerate actual outage confirmation.

The production thermal runtime orchestrator owns one tracker per config entry
and consumes its typed assessment as a command-free lifecycle gate. Pending,
unknown, and confirmed-outage states block a new thermal candidate. They also
end any existing in-memory thermal ownership entitlement without issuing a
cleanup, restoration, pump, body, or heat-source command. Authoritative
`ON_GRID` evidence permits only a fresh evaluation; it never restores a prior
plan, session, ownership lease, RPM, source, or body state.

Physical outage response is a separate, reduction-only authority domain with a
dedicated **Grid Outage Physical Safety** gate. The gate is independent from
Automatic Thermal, Thermal Live, and normal body commissioning scope; it is
off by default, is never restored on, and enabling it requires a later fresh
authoritative frame. Maintenance, controller Auto mode, transport readiness,
current evidence, and the final shared command-lock check remain mandatory.

The command-free circulation assessment answers only whether already-established
Pool circulation must remain active now. `CREDITING` and `RUN_NOW` filtration,
or an incomplete source/Spa shutdown, may require retention. Debt or deferment
alone does not. `REQUIRED` never activates a body or starts a pump. Missing,
stale, contradictory, or unusable hydraulic, source, freeze, or filtration
evidence blocks hydraulic reduction.

For each confirmed-outage frame, reduction priority is: Spa source Off, Pool
source Off, Pool Light Off, Jets Off, Slide Off, Waterfall Off, Spa body Off,
then circulation reassessment and an eligible pump reduction. Active-body Gas
or Solar is deselected only by the exact native HEATER value `00000`; inactive
body source configuration is not rewritten. Unknown active-body source values
block dependent hydraulic work. Freeze permits source deselection and Pool
Light Off, but blocks circuit, body, and pump reductions.

The only outage pump target is the configured outage baseline on `p0102`. It is
a reduction ceiling for already-established, positively required Pool
circulation: a configured value above the baseline may be reduced to it, an
equal value is already safe, and a lower value is never increased. Zero actual
RPM never authorizes a start. This numeric baseline is semantically distinct
from the Pool temperature-probe baseline even when both values are equal.

At most one new operation is delivered from one authoritative frame. Accepted
delivery is not completion. A strictly later authoritative native observation
must verify the exact body, circuit, source, or configured-speed consequence;
pump reduction additionally verifies actual RPM within the canonical tolerance
and continuous safe Pool hydraulics. No retry worker, polling, sleep, command
queue, or restoration exists. Unload and restart reconstruct neither gate,
candidate, attempt, ownership, nor outage epoch.

Canonical external-change classification remains the source of command
attribution and takeover evidence. A correlated expected consequence does not
preempt its own outage operation, while an uncorrelated outage-relevant change
within the confirmed epoch invalidates stale work before verification. A final
authority denial that proves transport never started invalidates only that
frame; a later fresh frame may reevaluate without retrying the stale request.
If transport may have started or its outcome is ambiguous, the outage epoch
fails closed and PoolOS does not resend the command. Dispatched consequence
attribution remains bounded by the central correlation TTL even across
unrelated normal-thermal frame churn.

After a confirmed outage, `UNKNOWN` continues blocking normal execution but
cannot authorize a new outage reduction or verify an existing attempt. Only
usable authoritative `ON_GRID` ends the outage domain. Grid return invalidates
outage authority and triggers fresh normal evaluation without restoring any
prior equipment state.

When grid power returns, release safety ownership and immediately reevaluate current conditions. Do not restore a pre-outage snapshot.

## Consequences

### Positive

- One source of truth
- Restart-safe behavior
- No stale-state restoration
- Extensible safety framework
- Predictable Powerwall consumption reduction

### Negative

- Depends on availability and correctness of the authoritative grid-status entity
- Requires clear behavior when the grid sensor is unavailable
- Full correctness depends on Decision Engine and Execution Engine maturity

## Rejected alternatives

### Independent Home Assistant automations

Rejected because they can conflict with normal control and are harder to make restart-safe.

### Force the pool pump on at a reduced RPM

Rejected because outage mode should constrain required circulation, not create a new circulation requirement.

### Restore previous equipment states after the outage

Rejected because previous state may be stale or inappropriate when power returns.
